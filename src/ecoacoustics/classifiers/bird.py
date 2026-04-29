import datetime
import os
import warnings
from typing import Any

import numpy as np
import soundfile as sf

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection

# Use RAM disk if available to avoid any physical disk I/O during analysis
_TMP_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


class BirdClassifier(BaseClassifier):
    """
    Wraps BirdNET-Analyzer via birdnetlib for real-time bird species ID.
    BirdNET expects 3-second, 48 kHz mono float32 audio.

    Efficiency notes:
    - Temp WAV written to /dev/shm (RAM disk) — zero physical disk I/O
    - Single reused temp file per instance — no repeated open/close overhead
    - RMS energy pre-filter skips inference on silent chunks
    """

    name = "bird"

    def __init__(self, config: dict[str, Any]):
        self._min_confidence: float = config.get("min_confidence", 0.35)
        self._latitude: float | None = config.get("latitude")
        self._longitude: float | None = config.get("longitude")
        # Chunks with RMS below this are silence — skip BirdNET entirely
        self._silence_threshold: float = config.get("silence_threshold", 0.001)
        self._analyzer = None
        self._Recording = None
        self._tmp_path: str | None = None

    @property
    def sample_rate(self) -> int:
        return 48000

    def load(self) -> None:
        import contextlib
        from rich.console import Console

        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from birdnetlib.analyzer import Analyzer
            from birdnetlib import Recording

        Console().print("[dim]Loading BirdNET model...[/dim]", end="")
        with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
            self._analyzer = Analyzer()
        Console().print("[dim] done[/dim]")
        self._Recording = Recording

        # Allocate the reusable temp file path once
        if _TMP_DIR:
            self._tmp_path = os.path.join(_TMP_DIR, f"ecoacoustics_bird_{os.getpid()}.wav")
        else:
            import tempfile
            self._tmp_path = os.path.join(tempfile.gettempdir(), f"ecoacoustics_bird_{os.getpid()}.wav")

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        if self._analyzer is None:
            raise RuntimeError("Call load() before classify()")

        # Fast path: skip inference on silent audio
        if np.sqrt(np.mean(chunk.data ** 2)) < self._silence_threshold:
            return []

        sf.write(self._tmp_path, chunk.data, chunk.sample_rate, subtype="PCM_16")

        recording = self._Recording(
            self._analyzer,
            self._tmp_path,
            lat=self._latitude,
            lon=self._longitude,
            date=datetime.date.today(),
            min_conf=self._min_confidence,
        )
        recording.analyze()

        return [
            Detection(
                label=d["common_name"],
                confidence=d["confidence"],
                classifier=self.name,
                timestamp=chunk.timestamp,
                metadata={
                    "scientific_name": d["scientific_name"],
                    "start_time": d.get("start_time", 0.0),
                    "end_time": d.get("end_time", 3.0),
                },
            )
            for d in recording.detections
            if d["confidence"] >= self._min_confidence
        ]

    def cleanup(self) -> None:
        """Remove the reused RAM-disk temp file on shutdown."""
        if self._tmp_path and os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)
