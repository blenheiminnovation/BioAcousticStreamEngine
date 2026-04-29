"""
Insect classifier — targets grasshoppers, crickets, and other stridulating
orthoptera (2–20 kHz band, standard microphone).

Plug-in options:
  • AVES (https://github.com/earthspecies/aves) — transfer-learning backbone
    fine-tuned on insect audio, requires custom training data.
  • ecoacoustics-tools spectral features + sklearn/XGBoost classifier trained on
    labelled recordings from Xeno-canto or your own field captures.
  • BioSoundSegmenter — for detecting and segmenting individual chirps.

To activate: implement _load_model() and _run_inference(), then add "insect" to
config/settings.yaml → classifiers.active.
"""

from typing import Any

import numpy as np

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class InsectClassifier(BaseClassifier):
    name = "insect"

    def __init__(self, config: dict[str, Any]):
        self._min_confidence: float = config.get("min_confidence", 0.5)
        self._model = None

    @property
    def sample_rate(self) -> int:
        return 44100

    @property
    def freq_min_hz(self) -> int:
        return 2_000

    @property
    def freq_max_hz(self) -> int:
        return 20_000

    def load(self) -> None:
        pass  # TODO: load model

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        if self._model is None:
            return []

        # TODO: run inference
        return []
