"""
Core pipeline: one AudioCapture per active sample-rate group, one AudioProcessor
per classifier, all running on a shared thread pool.
"""

import concurrent.futures
import signal
import threading
import time
from typing import Any

import yaml

from ecoacoustics.audio.capture import AudioCapture, AudioChunk
from ecoacoustics.audio.processor import AudioProcessor
from ecoacoustics.classifiers import REGISTRY, BaseClassifier
from ecoacoustics.output.logger import DetectionLogger


class Pipeline:
    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path) as f:
            self._cfg = yaml.safe_load(f)

        self._classifiers: list[BaseClassifier] = self._build_classifiers()
        self._logger = DetectionLogger(
            console=self._cfg["output"].get("console", True),
            log_file=self._cfg["output"].get("log_file"),
            min_confidence=self._cfg["output"].get("min_confidence", 0.0),
        )
        self._stop_event = threading.Event()

        # Group classifiers by sample rate — one capture stream per rate
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

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._handle_sigint)
        signal.signal(signal.SIGTERM, self._handle_sigint)

        for clf in self._classifiers:
            clf.load()

        for capture in self._captures.values():
            capture.start()

        from rich.console import Console
        Console().print(
            f"\n[bold green]Ecoacoustics monitoring started[/bold green]  "
            f"classifiers: {[c.name for c in self._classifiers]}\n"
            "Press Ctrl+C to stop.\n"
        )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(self._classifiers) + 1
        ) as pool:
            futures = [
                pool.submit(self._classifier_loop, clf) for clf in self._classifiers
            ]
            concurrent.futures.wait(futures)

        for capture in self._captures.values():
            capture.stop()
        self._logger.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _classifier_loop(self, clf: BaseClassifier) -> None:
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
                    self._logger.log(detections)
            except Exception as exc:
                from rich.console import Console
                Console().print(f"[red][{clf.name}] error: {exc}[/red]")

    def _build_classifiers(self) -> list[BaseClassifier]:
        active = self._cfg["classifiers"]["active"]
        classifiers = []
        for name in active:
            if name not in REGISTRY:
                raise ValueError(f"Unknown classifier '{name}'. Available: {list(REGISTRY)}")
            clf_cfg = self._cfg.get(name, {})
            classifiers.append(REGISTRY[name](clf_cfg))
        return classifiers

    def _handle_sigint(self, *_) -> None:
        from rich.console import Console
        Console().print("\n[yellow]Stopping...[/yellow]")
        self._stop_event.set()
