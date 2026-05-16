"""
Pipeline lifecycle manager for the web UI.

Runs the Pipeline in a background thread so FastAPI stays responsive.
Bridges sync detections to the async WebSocket broadcast queue via
asyncio.run_coroutine_threadsafe.

Author: David Green, Blenheim Palace
"""

import asyncio
import logging
import re
import threading
import time
from datetime import datetime
from typing import Callable, Optional

import yaml

_log = logging.getLogger(__name__)

from ecoacoustics.classifiers.base import Detection
from ecoacoustics.session import Session


class PipelineManager:
    """Manages start/stop of the Pipeline from the web API."""

    def __init__(self, config_path: str = "config/settings.yaml", device_index=None, device_name: str = "Default"):
        self._config_path = config_path
        self._device_index = device_index
        self._device_name = device_name
        self._pipeline = None
        self._thread: Optional[threading.Thread] = None
        self._state = "idle"          # idle | listening | scheduled
        self._window: Optional[str] = None
        self._started_at: Optional[str] = None
        self._next_window: Optional[str] = None
        self._error: Optional[str] = None
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._broadcast_queue: Optional[asyncio.Queue] = None

    def set_async_context(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        self._loop = loop
        self._broadcast_queue = queue

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def status_dict(self) -> dict:
        return {
            "state": self._state,
            "window": self._window,
            "started_at": self._started_at,
            "next_window": self._next_window,
            "error": self._error,
            "device_index": self._device_index,
            "device_name": self._device_name,
        }

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start_wake(self, duration_minutes: Optional[int] = None) -> bool:
        with self._lock:
            # Guard against stale "idle" state while the previous thread winds down
            if self._state != "idle" or (self._thread and self._thread.is_alive()):
                return False
            self._state = "listening"
            self._window = "manual"
            self._started_at = datetime.now().isoformat()
            self._error = None

        duration_seconds = duration_minutes * 60 if duration_minutes else None
        self._thread = threading.Thread(
            target=self._run_wake, args=(duration_seconds,), daemon=True
        )
        self._thread.start()
        return True

    def start_schedule(self) -> bool:
        with self._lock:
            if self._state != "idle" or (self._thread and self._thread.is_alive()):
                return False
            self._state = "scheduled"
            self._started_at = datetime.now().isoformat()
            self._error = None

        self._thread = threading.Thread(target=self._run_schedule, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        if self._state == "idle":
            return False
        if self._pipeline:
            self._pipeline._stop_event.set()
        with self._lock:
            self._state = "idle"
        return True

    # ------------------------------------------------------------------
    # Background runners
    # ------------------------------------------------------------------

    def _run_wake(self, duration_seconds: Optional[float]) -> None:
        from ecoacoustics.pipeline import Pipeline
        try:
            self._pipeline = Pipeline(
                config_path=self._config_path,
                detection_callback=self._on_detection,
                level_callback=self._on_level,
                device_override=self._device_index,
            )
            self._pipeline.run(window_name="manual", duration_seconds=duration_seconds)
        except Exception as exc:
            self._error = str(exc)
            _log.exception("Pipeline (wake) stopped with error: %s", exc)
        finally:
            if self._pipeline:
                self._pipeline.close()
                self._pipeline = None
            with self._lock:
                self._state = "idle"
                self._window = None
                self._started_at = None
            self._broadcast_pipeline_stopped()

    def _run_schedule(self) -> None:
        from ecoacoustics.pipeline import Pipeline
        from ecoacoustics.scheduler import Scheduler

        try:
            all_species: set[str] = set()

            while self._state == "scheduled":
                # Re-read config and rebuild scheduler/pipeline each iteration so
                # classifier and schedule changes saved via the UI take effect on
                # the next window, not on restart. adapt() is idempotent given
                # the cumulative species set, so re-applying it is safe.
                with open(self._config_path) as f:
                    cfg = yaml.safe_load(f)
                scheduler = Scheduler.from_config(cfg)
                adaptive_cfg = cfg.get("schedule", {}).get("adaptive", {})
                scheduler.adapt(all_species, adaptive_cfg)

                current = scheduler.current_window()
                if current:
                    start, end, name = current
                    remaining = (end - datetime.now(start.tzinfo)).total_seconds()
                    if remaining > 5:
                        self._window = name
                        self._pipeline = Pipeline(
                            config_path=self._config_path,
                            detection_callback=self._on_detection,
                            level_callback=self._on_level,
                            device_override=self._device_index,
                        )
                        try:
                            session = self._pipeline.run(
                                window_name=name, duration_seconds=remaining
                            )
                            all_species |= session.species_detected()
                        finally:
                            self._pipeline.close()
                            self._pipeline = None
                        continue

                nw = scheduler.next_window()
                self._window = "sleeping"
                self._next_window = nw[2] if nw else None
                time.sleep(min(scheduler.seconds_until_next(), 30))

        except Exception as exc:
            self._error = str(exc)
            _log.exception("Pipeline (schedule) stopped with error: %s", exc)
        finally:
            if self._pipeline:
                self._pipeline.close()
                self._pipeline = None
            with self._lock:
                self._state = "idle"
                self._window = None
                self._next_window = None
                self._started_at = None
            self._broadcast_pipeline_stopped()

    # ------------------------------------------------------------------
    # Detection bridge: sync thread → async WebSocket queue
    # ------------------------------------------------------------------

    def _broadcast_pipeline_stopped(self) -> None:
        """Tell the frontend to reset the VU meter when this pipeline finishes."""
        if not self._loop or not self._broadcast_queue:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_queue.put({"type": "pipeline_stopped", "device_name": self._device_name}),
                self._loop,
            )
        except Exception:
            pass

    def _on_level(self, db: float) -> None:
        if not self._loop or not self._broadcast_queue:
            print(f"[LEVEL_CB] no async context — loop={self._loop is not None}", flush=True)
            return
        now = time.time()
        if not hasattr(self, "_last_level_t") or now - self._last_level_t >= 1.0:
            self._last_level_t = now
            payload = {"type": "audio_level", "db": round(db, 1), "device_name": self._device_name}
            try:
                asyncio.run_coroutine_threadsafe(self._broadcast_queue.put(payload), self._loop)
                print(f"[LEVEL_CB] queued db={db:.1f}", flush=True)
            except Exception as e:
                print(f"[LEVEL_CB] queue error: {e}", flush=True)

    def _on_detection(self, det: Detection, session: Session, call_n: int) -> None:
        print(f"[CB] _on_detection called: {det.label} loop={self._loop is not None} queue={self._broadcast_queue is not None}", flush=True)
        if not self._loop or not self._broadcast_queue:
            print("[CB] WARNING: async context not set — cannot broadcast", flush=True)
            return
        ts = datetime.fromtimestamp(det.timestamp)
        try:
            with open(self._config_path) as _f:
                _cfg = yaml.safe_load(_f)
            _loc = _cfg.get("location", {})
            location_name = _loc.get("name", "")
        except Exception:
            location_name = ""

        payload = {
            "type": "detection",
            "session_id": session.session_id,
            "window_name": session.window_name,
            "date": ts.strftime("%Y-%m-%d"),
            "time": ts.strftime("%H:%M:%S"),
            "classifier": det.classifier,
            "species_common": det.label,
            "species_scientific": det.metadata.get("scientific_name", ""),
            "species_image": re.sub(r"[^a-z0-9]+", "_", det.label.lower().replace("'", "")).strip("_") + ".jpg",
            "confidence": round(det.confidence, 4),
            "call_number_in_session": call_n,
            "device_name": self._device_name,
            "device_index": self._device_index,
            "location_name": location_name,
        }
        try:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_queue.put(payload), self._loop
            )
            _log.debug("Broadcast queued: %s", det.label)
        except Exception as exc:
            _log.error("Failed to queue broadcast: %s", exc)
