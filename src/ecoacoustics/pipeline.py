"""
Central processing pipeline — connects audio capture to classifiers and logging.

The Pipeline is the top-level coordinator for a single listening session.
It owns:
  - One AudioCapture stream per unique classifier sample rate
  - One AudioProcessor per classifier
  - The DetectionLogger and ClipManager (shared across all classifiers)
  - A Watchdog daemon thread for health monitoring and recovery

Each active classifier runs in its own thread.  If a classifier raises
exceptions repeatedly, the pipeline reloads the model in-place.  If the
reload fails, that classifier thread exits cleanly while the others continue,
ensuring continuous recording is not interrupted by a single component failure.

Author: David Green, Blenheim Palace
"""

import concurrent.futures
import math
import signal
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

import yaml
from rich.console import Console

from ecoacoustics.audio.capture import AudioCapture
from ecoacoustics.audio.processor import AudioProcessor
from ecoacoustics.classifiers import REGISTRY, BaseClassifier
from ecoacoustics.clip_manager import ClipManager
from ecoacoustics.output.logger import DetectionLogger
from ecoacoustics.output.mqtt_publisher import MqttPublisher
from ecoacoustics.session import Session
from ecoacoustics.watchdog import Watchdog

_console = Console()

# Consecutive classify() failures before attempting an in-place model reload
_MAX_ERRORS_BEFORE_RELOAD = 5


class Pipeline:
    """Orchestrates the full detection loop for one listening session.

    Typical usage::

        pipeline = Pipeline("config/settings.yaml")
        session = pipeline.run(window_name="dawn_chorus", duration_seconds=5400)
        pipeline.close()
    """

    def __init__(self, config_path: str = "config/settings.yaml", detection_callback: Optional[Callable] = None, level_callback: Optional[Callable] = None, device_override=None):
        """Load configuration and prepare all subsystems.

        Args:
            config_path: Path to the YAML settings file.
        """
        with open(config_path) as f:
            self._cfg = yaml.safe_load(f)

        secrets_path = Path(config_path).parent / "secrets.yaml"
        if secrets_path.exists():
            with open(secrets_path) as f:
                secrets = yaml.safe_load(f) or {}
            for key, val in secrets.items():
                if isinstance(val, dict) and key in self._cfg:
                    self._cfg[key].update(val)
                else:
                    self._cfg[key] = val

        self._classifiers: list[BaseClassifier] = self._build_classifiers()

        bird_cfg = self._cfg.get("bird", {})
        out_cfg = self._cfg.get("output", {})
        clips_cfg = self._cfg.get("clips", {})
        mqtt_cfg = self._cfg.get("mqtt", {})
        loc_cfg = self._cfg.get("location", {})

        mqtt_publisher = None
        if mqtt_cfg.get("enabled", False):
            mqtt_publisher = MqttPublisher(
                host=mqtt_cfg.get("host", "localhost"),
                port=mqtt_cfg.get("port", 1883),
                topic_prefix=mqtt_cfg.get("topic_prefix", "bioacoustics"),
                tls=mqtt_cfg.get("tls", False),
                username=mqtt_cfg.get("username"),
                password=mqtt_cfg.get("password"),
                latitude=loc_cfg.get("latitude", bird_cfg.get("latitude")),
                longitude=loc_cfg.get("longitude", bird_cfg.get("longitude")),
                location_name=loc_cfg.get("name", ""),
            )

        self._logger = DetectionLogger(
            console=out_cfg.get("console", True),
            detections_csv=out_cfg.get("detections_csv"),
            sessions_csv=out_cfg.get("sessions_csv"),
            min_confidence=out_cfg.get("min_confidence", 0.0),
            latitude=loc_cfg.get("latitude", bird_cfg.get("latitude")),
            longitude=loc_cfg.get("longitude", bird_cfg.get("longitude")),
            location_name=loc_cfg.get("name", ""),
            mqtt_publisher=mqtt_publisher,
            detection_callback=detection_callback,
        )
        self._clip_manager = ClipManager(
            clips_dir=clips_cfg.get("dir", "output/clips"),
            species_db_path=clips_cfg.get("species_db", "output/known_species.json"),
            max_clips_per_species=clips_cfg.get("max_per_species", 100),
            min_confidence=out_cfg.get("min_confidence", 0.35),
        )

        self._stop_event = threading.Event()
        self._level_callback = level_callback
        # Keyed by (sample_rate, device) so each classifier can use a different mic
        self._captures: dict[tuple, AudioCapture] = {}
        self._clf_capture_key: dict[str, tuple] = {}
        self._processors: dict[str, AudioProcessor] = {}

        clf_devices = self._cfg.get("classifiers", {}).get("devices", {})
        default_device = device_override if device_override is not None else self._cfg["audio"].get("device")

        for clf in self._classifiers:
            _device = clf_devices.get(clf.name, default_device)
            _key = (clf.sample_rate, str(_device))
            self._clf_capture_key[clf.name] = _key
            if _key not in self._captures:
                self._captures[_key] = AudioCapture(
                    sample_rate=clf.sample_rate,
                    chunk_duration=self._cfg["audio"]["chunk_duration"],
                    device=_device,
                    channels=self._cfg["audio"].get("channels", 1),
                    max_queue_size=self._cfg["audio"].get("max_queue_size", 20),
                )
            self._processors[clf.name] = AudioProcessor(
                target_sample_rate=clf.sample_rate,
                freq_min_hz=clf.freq_min_hz,
                freq_max_hz=clf.freq_max_hz,
            )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @property
    def config(self) -> dict:
        """The loaded settings dictionary."""
        return self._cfg

    def run(self, window_name: str = "manual", duration_seconds: Optional[float] = None) -> Session:
        """Start listening and classifying until stopped or duration elapses.

        Loads all classifier models, starts audio capture streams, launches
        classifier threads and the Watchdog, then blocks until the session ends.
        Writes the session summary and cleans up on return.

        Args:
            window_name: Label for this listening session (e.g. 'dawn_chorus').
            duration_seconds: Stop automatically after this many seconds; None
                means run until Ctrl+C or SIGTERM.

        Returns:
            The completed Session object containing all detection statistics.
        """
        self._stop_event.clear()

        if duration_seconds:
            timer = threading.Timer(duration_seconds, self._stop_event.set)
            timer.daemon = True
            timer.start()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._handle_sigint)
            signal.signal(signal.SIGTERM, self._handle_sigint)

        for clf in self._classifiers:
            clf.load()

        for capture in self._captures.values():
            capture.start()

        watchdog = Watchdog(
            captures=self._captures,
            clip_manager=self._clip_manager,
            stop_event=self._stop_event,
            clips_dir=self._cfg.get("clips", {}).get("dir", "output/clips"),
        )
        watchdog.start()

        session = Session(window_name=window_name)
        dur_str = f" for {duration_seconds/60:.0f} min" if duration_seconds else ""
        _console.print(
            f"\n[bold green]Listening[/bold green] — window: [cyan]{window_name}[/cyan]{dur_str}\n"
            f"Classifiers: {[c.name for c in self._classifiers]}   "
            f"Press Ctrl+C to stop.\n"
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self._classifiers)) as pool:
            futures = [
                pool.submit(self._classifier_loop, clf, session)
                for clf in self._classifiers
            ]
            concurrent.futures.wait(futures)

        for capture in self._captures.values():
            capture.stop()
        for clf in self._classifiers:
            clf.cleanup()

        session.close()
        self._logger.write_session_summary(session)
        return session

    def close(self) -> None:
        """Flush and close the CSV log files."""
        self._logger.close()

    # ------------------------------------------------------------------
    # Classifier loop with auto-recovery
    # ------------------------------------------------------------------

    def _classifier_loop(self, clf: BaseClassifier, session: Session) -> None:
        """Continuously classify audio chunks from the capture queue.

        Resets the consecutive-error counter on every successful inference.
        After _MAX_ERRORS_BEFORE_RELOAD consecutive failures, attempts to
        reload the model; if the reload itself fails, exits the thread cleanly.

        Args:
            clf: The classifier to run.
            session: The active session for recording detections.
        """
        capture = self._captures[self._clf_capture_key[clf.name]]
        processor = self._processors[clf.name]
        consecutive_errors = 0

        while not self._stop_event.is_set():
            chunk = capture.get_chunk(timeout=1.0)
            if chunk is None:
                continue

            if self._level_callback:
                try:
                    rms = float(np.sqrt(np.mean(chunk.data ** 2)))
                    db = 20 * math.log10(max(rms, 1e-10))
                    print(f"[LEVEL] db={db:.1f} rms={rms:.6f}", flush=True)
                    self._level_callback(db)
                except Exception as _lev_exc:
                    print(f"[LEVEL] error: {_lev_exc}", flush=True)

            try:
                processed = processor.process(chunk)
                detections = clf.classify(processed)
                consecutive_errors = 0  # reset on any successful inference

                if not detections:
                    continue

                self._logger.log(detections, session)

                for det in detections:
                    saved_path, is_new = self._clip_manager.process(
                        det, processed.data, processed.sample_rate
                    )
                    if is_new:
                        _console.print(
                            f"\n[bold yellow] NEW SPECIES: {det.label} "
                            f"({det.metadata.get('scientific_name', '')}) "
                            f"conf {det.confidence:.0%}[/bold yellow]\n"
                        )
                    elif saved_path:
                        _console.print(f"[dim]  clip → {saved_path.name}[/dim]")

            except Exception as exc:
                consecutive_errors += 1
                _console.print(
                    f"[red][{clf.name}] error {consecutive_errors}/{_MAX_ERRORS_BEFORE_RELOAD}: "
                    f"{exc}[/red]"
                )

                if consecutive_errors >= _MAX_ERRORS_BEFORE_RELOAD:
                    _console.print(
                        f"[yellow][{clf.name}] reloading model after "
                        f"{consecutive_errors} consecutive errors...[/yellow]"
                    )
                    try:
                        clf.cleanup()
                        clf.load()
                        consecutive_errors = 0
                        _console.print(f"[green][{clf.name}] model reloaded successfully[/green]")
                    except Exception as reload_exc:
                        _console.print(
                            f"[bold red][{clf.name}] reload failed: {reload_exc}. "
                            f"Classifier stopped.[/bold red]"
                        )
                        return  # exit thread; other classifiers continue unaffected

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_classifiers(self) -> list[BaseClassifier]:
        """Instantiate classifiers listed in settings.yaml classifiers.active."""
        active = self._cfg["classifiers"]["active"]
        result = []
        for name in active:
            if name not in REGISTRY:
                raise ValueError(f"Unknown classifier '{name}'. Available: {list(REGISTRY)}")
            result.append(REGISTRY[name](self._cfg.get(name, {})))
        return result

    def _handle_sigint(self, *_) -> None:
        """Set the stop event on SIGINT or SIGTERM to allow clean shutdown."""
        _console.print("\n[yellow]Stopping...[/yellow]")
        self._stop_event.set()
