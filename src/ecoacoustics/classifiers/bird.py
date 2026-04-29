import datetime
import os
import tempfile
import warnings
from typing import Any

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
        self._min_confidence: float = config.get("min_confidence", 0.35)
        self._latitude: float | None = config.get("latitude")
        self._longitude: float | None = config.get("longitude")
        self._analyzer = None
        self._Recording = None

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

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        if self._analyzer is None:
            raise RuntimeError("Call load() before classify()")

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            sf.write(tmp_path, chunk.data, chunk.sample_rate, subtype="PCM_16")

            recording = self._Recording(
                self._analyzer,
                tmp_path,
                lat=self._latitude,
                lon=self._longitude,
                date=datetime.date.today(),
                min_conf=self._min_confidence,
            )
            recording.analyze()
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return [
            Detection(
                label=d["common_name"],
                confidence=d["confidence"],
                classifier=self.name,
                timestamp=chunk.timestamp,
                metadata={
                    "scientific_name": d["scientific_name"],
                    "start_time": d.get("start_time", 0.0),
                    "end_time": d.get("end_time", chunk.sample_rate / max(len(chunk.data), 1)),
                },
            )
            for d in recording.detections
            if d["confidence"] >= self._min_confidence
        ]
