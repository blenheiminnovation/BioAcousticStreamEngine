import datetime
import io
import tempfile
from typing import Any

import numpy as np
import soundfile as sf

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class BirdClassifier(BaseClassifier):
    """
    Wraps BirdNET-Analyzer via birdnetlib for real-time bird species ID.
    BirdNET expects 3-second, 48 kHz mono float32 audio.
    """

    name = "bird"

    def __init__(self, config: dict[str, Any]):
        self._min_confidence: float = config.get("min_confidence", 0.5)
        self._latitude: float | None = config.get("latitude")
        self._longitude: float | None = config.get("longitude")
        self._week: int | None = config.get("week")
        self._analyzer = None

    @property
    def sample_rate(self) -> int:
        return 48000

    def load(self) -> None:
        from birdnetlib import Recording
        from birdnetlib.analyzer import Analyzer
        self._analyzer = Analyzer()
        self._Recording = Recording

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        if self._analyzer is None:
            raise RuntimeError("Call load() before classify()")

        week = self._week or self._current_week()

        # birdnetlib requires a file path or bytes-like object — write to a
        # temporary WAV file so we don't need to fork the birdnetlib API.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, chunk.data, chunk.sample_rate, subtype="PCM_16")
            recording = self._Recording(
                self._analyzer,
                tmp.name,
                lat=self._latitude,
                lon=self._longitude,
                week=week,
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
                    "start_time": d.get("start_time", 0),
                    "end_time": d.get("end_time", chunk.sample_rate / chunk.data.size),
                },
            )
            for d in recording.detections
            if d["confidence"] >= self._min_confidence
        ]

    @staticmethod
    def _current_week() -> int:
        return datetime.date.today().isocalendar().week
