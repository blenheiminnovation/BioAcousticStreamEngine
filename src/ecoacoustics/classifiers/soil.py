"""
Soil acoustics classifier — Soil Acoustic Index (SAI).

Based on early soil ecoacoustics work by the Blenheim Palace Innovation Team.
The pipeline applies a bandpass filter (50–2000 Hz) via AudioProcessor before
this classifier is called, replicating the cleaning step from bandpassFilter.py.
What remains is used to compute the SAI.

Soil Acoustic Index (SAI)
--------------------------
A composite 0–1 index derived from three acoustic measures:

  RMS energy         Signal power after cleaning. Scales with intensity of
                     activity (worm movement, root growth, soil arthropods).

  Acoustic Complexity Index (ACI)
                     Measures temporal variation in spectral intensity across
                     frequency bins. Biological signals (worms, roots) produce
                     complex, irregular patterns — high ACI. Mechanical
                     interference (vibration, rain) produces regular, repeating
                     patterns — low ACI.

  Spectral entropy   Biological broadband activity spreads energy across
                     many frequencies (high entropy). Tonal mechanical noise
                     concentrates energy (low entropy).

SAI = 0.4 × rms_norm + 0.4 × aci_norm + 0.2 × entropy

Detections fire when SAI exceeds min_confidence (default 0.1 — intentionally
low so the index is always reported for analysis during the beta phase).

Activity levels:
  SAI ≥ 0.65  →  High Soil Activity
  SAI ≥ 0.35  →  Moderate Soil Activity
  SAI < 0.35  →  Low Soil Activity

Hardware
--------
A contact microphone (geophone, SM-24, or piezo disk pressed to the soil
surface) gives significantly better sensitivity than an air microphone.
The frequency range and SAI calibration constants may need tuning per device.

Beta note
---------
SAI thresholds and weighting are uncalibrated — based on signal processing
principles rather than labelled Blenheim soil recordings. Treat all outputs
as indicative and useful for relative comparison across time. Absolute
values should not be compared across different microphones or locations
without recalibration.

Author: David Green, Blenheim Palace
Acoustic indices after: Pieretti et al. (2011), Pijanowski et al. (2011)
"""

from typing import Any

import numpy as np

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class SoilClassifier(BaseClassifier):
    """Soil Acoustic Index (SAI) classifier.

    Computes a composite index from RMS energy, Acoustic Complexity Index,
    and spectral entropy on bandpass-cleaned (50–2000 Hz) audio chunks.
    """

    name = "soil"

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: Section from settings.yaml under the 'soil' key.

            min_confidence  Minimum SAI to report a detection. Default 0.1
                            (very low — beta mode logs all meaningful activity).
            rms_scale       RMS value that maps to a full (1.0) RMS contribution.
                            Tune to your microphone's typical signal level.
            aci_scale       ACI value that maps to a full (1.0) ACI contribution.
        """
        self._min_confidence: float = config.get("min_confidence", 0.1)
        self._rms_scale: float = config.get("rms_scale", 0.05)
        self._aci_scale: float = config.get("aci_scale", 0.5)

    @property
    def sample_rate(self) -> int:
        return 22050

    @property
    def freq_min_hz(self) -> int:
        return 50

    @property
    def freq_max_hz(self) -> int:
        return 2000

    def load(self) -> None:
        pass

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Compute SAI from bandpass-cleaned audio and return a Detection.

        Args:
            chunk: Pre-processed audio at 22.05 kHz, bandpass-filtered 50–2000 Hz.

        Returns:
            A single Detection whose confidence IS the SAI (0–1), or empty list
            if SAI is below min_confidence.
        """
        audio = chunk.data.astype(np.float64)
        if len(audio) == 0:
            return []

        rms = float(np.sqrt(np.mean(audio ** 2)))
        aci = self._acoustic_complexity_index(audio)
        entropy = self._spectral_entropy(audio)

        rms_norm = min(rms / max(self._rms_scale, 1e-10), 1.0)
        aci_norm = min(aci / max(self._aci_scale, 1e-10), 1.0)

        sai = round(0.4 * rms_norm + 0.4 * aci_norm + 0.2 * entropy, 4)

        if sai < self._min_confidence:
            return []

        if sai >= 0.65:
            level = "High"
        elif sai >= 0.35:
            level = "Moderate"
        else:
            level = "Low"

        return [Detection(
            label=f"Soil Activity — {level}",
            confidence=sai,
            classifier=self.name,
            timestamp=chunk.timestamp,
            metadata={
                "sai": sai,
                "activity_level": level,
                "rms_energy": round(rms, 6),
                "aci": round(aci, 4),
                "spectral_entropy": round(entropy, 4),
                "beta": True,
            },
        )]

    @staticmethod
    def _acoustic_complexity_index(audio: np.ndarray, n_fft: int = 512, hop: int = 256) -> float:
        """Compute the Acoustic Complexity Index (ACI) after Pieretti et al. 2011.

        ACI measures temporal variation in spectral intensity. Biological
        sounds produce irregular, complex patterns (high ACI); mechanical
        interference produces regular, repeating patterns (low ACI).

        Returns a value typically in the range 0–2; normalised by the caller.
        """
        if len(audio) < n_fft:
            return 0.0

        n_frames = (len(audio) - n_fft) // hop + 1
        if n_frames < 2:
            return 0.0

        # Build power spectrogram frame-by-frame
        spectrogram = np.array([
            np.abs(np.fft.rfft(audio[i * hop: i * hop + n_fft]))
            for i in range(n_frames)
        ])  # shape: (n_frames, n_bins)

        # ACI per frequency bin: sum|diff| / sum
        diffs = np.abs(np.diff(spectrogram, axis=0))        # (n_frames-1, n_bins)
        sums  = spectrogram[:-1].sum(axis=0) + 1e-10        # (n_bins,)

        aci_per_bin = diffs.sum(axis=0) / sums              # (n_bins,)
        return float(aci_per_bin.mean())

    @staticmethod
    def _spectral_entropy(audio: np.ndarray) -> float:
        """Spectral entropy: 0 = tonal/mechanical, 1 = broadband/complex.

        Biological soil activity spreads energy broadly across frequencies,
        giving high entropy. Tonal mechanical noise concentrates energy,
        giving low entropy.
        """
        spectrum = np.abs(np.fft.rfft(audio)) ** 2
        total = spectrum.sum()
        if total == 0:
            return 0.0
        p = spectrum / total
        # Shannon entropy, normalised by log2(n_bins)
        entropy = -np.sum(p * np.log2(p + 1e-12))
        max_entropy = np.log2(len(p))
        return float(entropy / max_entropy) if max_entropy > 0 else 0.0
