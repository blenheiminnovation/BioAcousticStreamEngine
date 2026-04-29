"""
Bird species classifier using BirdNET-Analyzer via the birdnetlib wrapper.

BirdNET is a deep-learning model developed by the Cornell Lab of Ornithology
and Chemnitz University of Technology, capable of identifying 6,000+ bird
species from 3-second audio clips at 48 kHz.

Efficiency design:
  - The temp WAV file is written to /dev/shm (Linux RAM disk) to avoid
    any physical disk I/O during inference — the file never touches storage.
  - A single temp file path is allocated once in load() and reused for every
    chunk, eliminating the overhead of repeated open/close/unlink syscalls.
  - An RMS energy pre-filter rejects silent chunks before the TFLite model
    is invoked, saving significant CPU during quiet periods.

Author: David Green, Blenheim Palace
"""

import datetime
import os
import warnings
from typing import Any

import numpy as np
import soundfile as sf

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection

# Prefer RAM disk to avoid physical I/O; fall back to /tmp if unavailable
_TMP_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


class BirdClassifier(BaseClassifier):
    """Identifies bird species in real time using BirdNET-Analyzer.

    Wraps birdnetlib's Recording + Analyzer API.  BirdNET uses a TFLite
    model to classify 3-second audio windows and returns species detections
    with confidence scores filtered by geographic location and season.
    """

    name = "bird"

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: Section from settings.yaml under the 'bird' key.
                min_confidence: Minimum score to report a detection (default 0.35).
                latitude: Recording latitude for species-range filtering.
                longitude: Recording longitude for species-range filtering.
                silence_threshold: RMS below this skips BirdNET inference (default 0.001).
        """
        self._min_confidence: float = config.get("min_confidence", 0.35)
        self._latitude: float | None = config.get("latitude")
        self._longitude: float | None = config.get("longitude")
        # Chunks with RMS below this are treated as silence — BirdNET skipped entirely
        self._silence_threshold: float = config.get("silence_threshold", 0.001)
        self._analyzer = None
        self._Recording = None
        self._tmp_path: str | None = None

    @property
    def sample_rate(self) -> int:
        """BirdNET requires 48 kHz mono audio."""
        return 48000

    def load(self) -> None:
        """Load the BirdNET TFLite model and allocate the reusable temp file.

        Suppresses noisy TF/pydub warnings and redirects birdnetlib's stdout
        print statements so only a clean one-line banner reaches the terminal.
        """
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

        # Allocate one reusable temp file for the lifetime of this session
        if _TMP_DIR:
            self._tmp_path = os.path.join(_TMP_DIR, f"ecoacoustics_bird_{os.getpid()}.wav")
        else:
            import tempfile
            self._tmp_path = os.path.join(tempfile.gettempdir(), f"ecoacoustics_bird_{os.getpid()}.wav")

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Run BirdNET inference on a single 3-second audio chunk.

        Returns an empty list if the chunk is silent or if no species meet
        the configured confidence threshold.
        """
        if self._analyzer is None:
            raise RuntimeError("Call load() before classify()")

        # Fast path: skip expensive TFLite inference on silent audio
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
        """Delete the reusable RAM-disk temp file on session shutdown."""
        if self._tmp_path and os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)
