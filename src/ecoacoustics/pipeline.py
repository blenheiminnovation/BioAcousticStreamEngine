import concurrent.futures
import signal
import threading
import time
from typing import Optional

import yaml
from rich.console import Console

from ecoacoustics.audio.capture import AudioCapture
from ecoacoustics.audio.processor import AudioProcessor
from ecoacoustics.classifiers import REGISTRY, BaseClassifier
from ecoacoustics.clip_manager import ClipManager
from ecoacoustics.output.logger import DetectionLogger
from ecoacoustics.session import Session
from ecoacoustics.watchdog import Watchdog

_console = Console()

# Consecutive classify() failures before attempting a model reload
_MAX_ERRORS_BEFORE_RELOAD = 5


class Pipeline:
    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path) as f:
            self._cfg = yaml.safe_load(f)

        self._classifiers: list[BaseClassifier] = self._build_classifiers()

        bird_cfg = self._cfg.get("bird", {})
        out_cfg = self._cfg.get("output", {})
        clips_cfg = self._cfg.get("clips", {})

        self._logger = DetectionLogger(
            console=out_cfg.get("console", True),
            detections_csv=out_cfg.get("detections_csv"),
            sessions_csv=out_cfg.get("sessions_csv"),
            min_confidence=out_cfg.get("min_confidence", 0.0),
            latitude=bird_cfg.get("latitude"),
            longitude=bird_cfg.get("longitude"),
        )
        self._clip_manager = ClipManager(
            clips_dir=clips_cfg.get("dir", "output/clips"),
            species_db_path=clips_cfg.get("species_db", "output/known_species.json"),
            max_clips_per_species=clips_cfg.get("max_per_species", 100),
            min_confidence=out_cfg.get("min_confidence", 0.35),
        )

        self._stop_event = threading.Event()
        self._captures: dict[int, AudioCapture] = {}
        self._processors: dict[str, AudioProcessor] = {}

        for clf in self._classifiers:
            if clf.sample_rate not in self._captures:
                self._captures[clf.sample_rate] = AudioCapture(
                    sample_rate=clf.sample_rate,
                    chunk_duration=self._cfg["audio"]["chunk_duration"],
                    device=self._cfg["audio"].get("device"),
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
        return self._cfg

    def run(self, window_name: str = "manual", duration_seconds: Optional[float] = None) -> Session:
        self._stop_event.clear()

        if duration_seconds:
            timer = threading.Timer(duration_seconds, self._stop_event.set)
            timer.daemon = True
            timer.start()

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
        self._logger.close()

    # ------------------------------------------------------------------
    # Classifier loop with auto-recovery
    # ------------------------------------------------------------------

    def _classifier_loop(self, clf: BaseClassifier, session: Session) -> None:
        capture = self._captures[clf.sample_rate]
        processor = self._processors[clf.name]
        consecutive_errors = 0

        while not self._stop_event.is_set():
            chunk = capture.get_chunk(timeout=1.0)
            if chunk is None:
                continue

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
                        return  # exit this thread; others continue

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_classifiers(self) -> list[BaseClassifier]:
        active = self._cfg["classifiers"]["active"]
        result = []
        for name in active:
            if name not in REGISTRY:
                raise ValueError(f"Unknown classifier '{name}'. Available: {list(REGISTRY)}")
            result.append(REGISTRY[name](self._cfg.get(name, {})))
        return result

    def _handle_sigint(self, *_) -> None:
        _console.print("\n[yellow]Stopping...[/yellow]")
        self._stop_event.set()
