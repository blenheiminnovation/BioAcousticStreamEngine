"""
Soil acoustics classifier — detects biological activity in soil via low-frequency
audio (earthworms, root growth, nematode movement, fungal networks).

This is an emerging research area. Current approaches are feature-based rather than
deep-learning because large labelled datasets don't yet exist publicly.

Default implementation: energy and spectral flux detection in the 50–2000 Hz band.
This flags anomalous acoustic events for human review rather than classifying species.

Plug-in options for future upgrade:
  • Train a custom CNN on spectrogram patches from your own sensor data.
  • Use pyts or cesium for time-series feature extraction + sklearn classifier.
  • Contact researchers at Rothamsted Research (UK) — they publish soil bioacoustic
    datasets that could support supervised training.

Hardware note: a contact microphone or geophone placed in/on soil captures
significantly better signal than an air microphone.
"""

from typing import Any

import numpy as np

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class SoilClassifier(BaseClassifier):
    name = "soil"

    def __init__(self, config: dict[str, Any]):
        self._min_confidence: float = config.get("min_confidence", 0.4)
        # RMS energy threshold — tune for your microphone/environment
        self._energy_threshold: float = config.get("energy_threshold", 0.01)

    @property
    def sample_rate(self) -> int:
        return 22050

    @property
    def freq_min_hz(self) -> int:
        return 50

    @property
    def freq_max_hz(self) -> int:
        return 2_000

    def load(self) -> None:
        pass  # no model weights needed for the baseline energy detector

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        rms = float(np.sqrt(np.mean(chunk.data ** 2)))
        if rms < self._energy_threshold:
            return []

        # Normalise RMS into a pseudo-confidence (0.4–1.0 range)
        confidence = min(1.0, 0.4 + rms / (self._energy_threshold * 10))
        if confidence < self._min_confidence:
            return []

        spectral_centroid = self._spectral_centroid(chunk.data, chunk.sample_rate)
        return [
            Detection(
                label="soil_activity",
                confidence=confidence,
                classifier=self.name,
                timestamp=chunk.timestamp,
                metadata={
                    "rms_energy": rms,
                    "spectral_centroid_hz": spectral_centroid,
                },
            )
        ]

    @staticmethod
    def _spectral_centroid(audio: np.ndarray, sr: int) -> float:
        spectrum = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
        if spectrum.sum() == 0:
            return 0.0
        return float(np.dot(freqs, spectrum) / spectrum.sum())
