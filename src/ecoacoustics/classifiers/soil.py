"""
Soil acoustics classifier — detects subsurface biological activity.

Soil hosts a rich acoustic environment produced by earthworms, nematodes,
fungal mycelium, root growth, and soil arthropods, all generating low-
frequency vibrations in the 50–2000 Hz band.

This is an emerging research area without large public labelled datasets,
so the current implementation uses a feature-based energy detector rather
than a trained neural network.  It flags anomalous acoustic events for
human review rather than identifying species directly.

Default implementation:
  RMS energy above a configurable threshold triggers a detection.
  The pseudo-confidence score is derived from the energy level.
  The spectral centroid is also computed and stored in metadata to help
  distinguish biological events from mechanical noise (e.g. digging).

Hardware note:
  A contact microphone or geophone placed in or on the soil surface
  captures significantly better signal than an air microphone pointing
  downward.  Geophones (e.g. SM-24) are particularly effective.

Upgrade path:
  - Collect labelled recordings from the estate soil.
  - Train a spectrogram CNN using pyts or cesium for feature extraction.
  - Contact Rothamsted Research (UK) for published soil bioacoustic datasets.

Author: David Green, Blenheim Palace
"""

from typing import Any

import numpy as np

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class SoilClassifier(BaseClassifier):
    """Energy-based soil activity detector in the 50–2000 Hz band.

    Returns a 'soil_activity' detection when RMS energy exceeds the
    configured threshold, with confidence derived from signal strength
    and spectral centroid stored in metadata for post-hoc analysis.
    """

    name = "soil"

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: Section from settings.yaml under the 'soil' key.
                min_confidence: Minimum score to report a detection (default 0.4).
                energy_threshold: RMS level below which audio is treated as
                    background; tune to your microphone and environment.
        """
        self._min_confidence: float = config.get("min_confidence", 0.4)
        # RMS energy threshold — tune for your microphone/environment
        self._energy_threshold: float = config.get("energy_threshold", 0.01)

    @property
    def sample_rate(self) -> int:
        """22.05 kHz is more than sufficient for the 50–2000 Hz band."""
        return 22050

    @property
    def freq_min_hz(self) -> int:
        """Lower edge of the soil-acoustics bandpass filter."""
        return 50

    @property
    def freq_max_hz(self) -> int:
        """Upper edge of the soil-acoustics bandpass filter."""
        return 2_000

    def load(self) -> None:
        """No model weights required for the baseline energy detector."""
        pass

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Detect anomalous soil acoustic activity via RMS energy.

        Args:
            chunk: Pre-processed audio at 22.05 kHz, bandpass 50–2000 Hz.

        Returns:
            A single 'soil_activity' Detection if energy exceeds threshold,
            otherwise an empty list.
        """
        rms = float(np.sqrt(np.mean(chunk.data ** 2)))
        if rms < self._energy_threshold:
            return []

        # Map RMS to a 0.4–1.0 pseudo-confidence range for downstream filtering
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
        """Compute the power-weighted mean frequency (Hz) of the audio spectrum."""
        spectrum = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
        if spectrum.sum() == 0:
            return 0.0
        return float(np.dot(freqs, spectrum) / spectrum.sum())
