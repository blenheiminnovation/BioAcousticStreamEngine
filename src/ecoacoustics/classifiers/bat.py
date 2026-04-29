"""
Bat classifier — requires an ultrasonic microphone (e.g. Dodotronic Ultramic,
Pettersson M500, or similar) sampled at ≥192 kHz.

Plug-in options:
  • BatDetective2 (https://github.com/macaodha/bat-detective) — deep learning,
    European species coverage, returns call-level predictions.
  • BatClassify (https://github.com/micbat/batclassify) — lighter, UK-focused.
  • echoStat / custom AVES model — if you train your own.

To activate: install your chosen library, implement _load_model() and
_run_inference() below, then add "bat" to config/settings.yaml → classifiers.active.
"""

from typing import Any

import numpy as np

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class BatClassifier(BaseClassifier):
    name = "bat"

    def __init__(self, config: dict[str, Any]):
        self._min_confidence: float = config.get("min_confidence", 0.6)
        self._model = None

    @property
    def sample_rate(self) -> int:
        # Nyquist for 150 kHz calls; match your hardware's max sample rate
        return 256000

    @property
    def freq_min_hz(self) -> int:
        return 15_000

    @property
    def freq_max_hz(self) -> int:
        return 150_000

    def load(self) -> None:
        # TODO: replace with actual model loading
        # self._model = _load_model()
        pass

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        if self._model is None:
            return []   # silently skip until a model is wired in

        # TODO: run inference and return Detection objects
        # raw = _run_inference(self._model, chunk.data, chunk.sample_rate)
        # return [Detection(...) for r in raw if r.confidence >= self._min_confidence]
        return []
