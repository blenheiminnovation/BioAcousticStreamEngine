import concurrent.futures
import signal
import threading
import time
from typing import Optional

import yaml

from ecoacoustics.audio.capture import AudioCapture
from ecoacoustics.audio.processor import AudioProcessor
from ecoacoustics.classifiers import REGISTRY, BaseClassifier
from ecoacoustics.output.logger import DetectionLogger
from ecoacoustics.session import Session


class Pipeline:
    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path) as f:
            self._cfg = yaml.safe_load(f)

        self._classifiers: list[BaseClassifier] = self._build_classifiers()
        bird_cfg = self._cfg.get("bird", {})
        self._logger = DetectionLogger(
            console=self._cfg["output"].get("console", True),
            detections_csv=self._cfg["output"].get("detections_csv"),
            sessions_csv=self._cfg["output"].get("sessions_csv"),
            min_confidence=self._cfg["output"].get("min_confidence", 0.0),
            latitude=bird_cfg.get("latitude"),
            longitude=bird_cfg.get("longitude"),
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
        """
        Listen and classify until Ctrl+C or duration_seconds elapses.
        Returns the completed Session.
        """
        self._stop_event.clear()

        if duration_seconds:
            timer = threading.Timer(duration_seconds, self._stop_event.set)
            timer.daemon = True
            timer.start()

        signal.signal(signal.SIGINT, self._handle_sigint)
        signal.signal(signal.SIGTERM, self._handle_sigint)

        session = Session(window_name=window_name)

        for clf in self._classifiers:
            clf.load()

        for capture in self._captures.values():
            capture.start()

        from rich.console import Console
        dur_str = f" for {duration_seconds/60:.0f} min" if duration_seconds else ""
        Console().print(
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

        session.close()
        self._logger.write_session_summary(session)
        return session

    def close(self) -> None:
        self._logger.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _classifier_loop(self, clf: BaseClassifier, session: Session) -> None:
        capture = self._captures[clf.sample_rate]
        processor = self._processors[clf.name]

        while not self._stop_event.is_set():
            chunk = capture.get_chunk(timeout=1.0)
            if chunk is None:
                continue
            try:
                processed = processor.process(chunk)
                detections = clf.classify(processed)
                if detections:
                    self._logger.log(detections, session)
            except Exception as exc:
                from rich.console import Console
                Console().print(f"[red][{clf.name}] error: {exc}[/red]")

    def _build_classifiers(self) -> list[BaseClassifier]:
        active = self._cfg["classifiers"]["active"]
        result = []
        for name in active:
            if name not in REGISTRY:
                raise ValueError(f"Unknown classifier '{name}'. Available: {list(REGISTRY)}")
            result.append(REGISTRY[name](self._cfg.get(name, {})))
        return result

    def _handle_sigint(self, *_) -> None:
        from rich.console import Console
        Console().print("\n[yellow]Stopping...[/yellow]")
        self._stop_event.set()
