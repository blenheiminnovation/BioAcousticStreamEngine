"""
Insect classifier — targets stridulating orthoptera (grasshoppers, crickets).

Orthoptera produce characteristic chirp patterns in the 2–20 kHz band,
detectable with a standard microphone.  This is a structured stub awaiting
a trained model.

Recommended model plug-ins:
  - AVES audio transformer (https://github.com/earthspecies/aves)
      Pre-trained on diverse animal vocalisations; fine-tune on labelled
      orthoptera recordings from Xeno-canto or your own field captures.
  - Spectral features + sklearn/XGBoost
      Extract MFCCs or mel-spectrograms and train a lightweight classifier;
      works well when labelled estate recordings are available.
  - BioSoundSegmenter
      Useful as a pre-processing step to detect and isolate individual
      chirp syllables before species-level classification.

To activate:
  1. Train or download a model for your target species.
  2. Implement load() and classify() below.
  3. Add "insect" to classifiers.active in config/settings.yaml.

Author: David Green, Blenheim Palace
"""

from typing import Any

import numpy as np

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class InsectClassifier(BaseClassifier):
    """Orthoptera classifier operating in the 2–20 kHz band.

    Currently a structured stub.  Returns an empty list until a model is
    wired into load() and classify().
    """

    name = "insect"

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: Section from settings.yaml under the 'insect' key.
                min_confidence: Minimum detection confidence (default 0.5).
        """
        self._min_confidence: float = config.get("min_confidence", 0.5)
        self._model = None

    @property
    def sample_rate(self) -> int:
        """44.1 kHz is sufficient to capture the full orthoptera call range."""
        return 44100

    @property
    def freq_min_hz(self) -> int:
        """Lower edge of the insect bandpass filter."""
        return 2_000

    @property
    def freq_max_hz(self) -> int:
        """Upper edge of the insect bandpass filter."""
        return 20_000

    def load(self) -> None:
        """Load the insect detection model.  Replace with real initialisation."""
        # TODO: load model
        pass

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Return insect detections; empty list until a model is loaded.

        Args:
            chunk: Pre-processed audio at 44.1 kHz, bandpass 2–20 kHz.

        Returns:
            List of Detection objects (empty until a model is wired in).
        """
        if self._model is None:
            return []

        # TODO: run inference
        return []
