"""
Bat species classifier — stub awaiting an ultrasonic model plug-in.

Bats echolocate in the 15–150 kHz range, well above the Nyquist limit of a
standard microphone.  This classifier requires dedicated ultrasonic hardware
(e.g. Dodotronic Ultramic 384K, Pettersson M500-384) sampled at ≥192 kHz.

Recommended model plug-ins:
  - BatDetective2 (https://github.com/macaodha/bat-detective)
      Deep-learning detector with European species coverage; returns
      call-level predictions with species probabilities.
  - BatClassify (https://github.com/micbat/batclassify)
      Lighter UK-focused classifier; good for common UK bat species.
  - Custom AVES fine-tune — if labelled recordings from the estate are
      available, fine-tuning the AVES audio transformer gives good results
      for site-specific populations.

To activate:
  1. Install your chosen library.
  2. Implement _load_model() and _run_inference() in this file.
  3. Add "bat" to classifiers.active in config/settings.yaml.
  4. Set audio.device to your ultrasonic microphone's device index.

Author: David Green, Blenheim Palace
"""

from typing import Any

import numpy as np

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class BatClassifier(BaseClassifier):
    """Bat species classifier operating in the 15–150 kHz ultrasonic band.

    Currently a structured stub.  The classify() method returns an empty list
    until a model is wired in via _load_model() and _run_inference().
    """

    name = "bat"

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: Section from settings.yaml under the 'bat' key.
                min_confidence: Minimum detection confidence (default 0.6).
        """
        self._min_confidence: float = config.get("min_confidence", 0.6)
        self._model = None

    @property
    def sample_rate(self) -> int:
        """256 kHz satisfies Nyquist for 128 kHz bat calls; match your hardware."""
        return 256000

    @property
    def freq_min_hz(self) -> int:
        """Low edge of the ultrasonic bandpass filter."""
        return 15_000

    @property
    def freq_max_hz(self) -> int:
        """High edge of the ultrasonic bandpass filter."""
        return 150_000

    def load(self) -> None:
        """Load the bat detection model.  Replace with real initialisation."""
        # TODO: self._model = _load_model()
        pass

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Return bat detections; empty list until a model is loaded.

        Args:
            chunk: Pre-processed audio at 256 kHz, bandpass 15–150 kHz.

        Returns:
            List of Detection objects (empty until a model is wired in).
        """
        if self._model is None:
            return []

        # TODO: replace with real inference
        # raw = _run_inference(self._model, chunk.data, chunk.sample_rate)
        # return [Detection(...) for r in raw if r.confidence >= self._min_confidence]
        return []
