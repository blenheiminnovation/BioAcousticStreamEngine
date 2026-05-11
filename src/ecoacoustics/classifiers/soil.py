"""
Soil acoustics classifier — Soil Acoustic Index (SAI).

Hardware
--------
Designed for a carbon-fibre probe rod (20–30 cm into soil) with a contact
microphone on the surface end. The rod conducts sub-surface vibration up to
the mic. This pickup is highly sensitive to:
  • biological activity below ground (earthworm rasps, soil arthropods)
  • surface seismic noise (footsteps, traffic, aircraft rumble, HVAC, mains)

The two compete in the same time window, so the classifier's job is not
just to measure energy but to *discriminate* biological energy from
anthropogenic energy.

Soil Acoustic Index v2 (primary score from 2026-05)
---------------------------------------------------
v2 replaces a pure RMS+ACI+entropy composite with a multiplicative
combination of three terms:

  bio_rms_norm     RMS energy in the 500–2000 Hz band (the worm / soil-
                   arthropod range), normalised against ``bio_rms_scale``.
                   Answers: is anything happening?

  ndsi_01          Normalised Difference Soundscape Index, mapped to [0, 1].
                   NDSI = (P_bio − P_anthro) / (P_bio + P_anthro), where
                     P_anthro = power in 50–300 Hz (footsteps, traffic,
                                distant aircraft, HVAC rumble)
                     P_bio    = power in 500–2000 Hz (biology)
                   Answers: is what's happening biological, or rumble?

  transient_gate   Crest factor (peak/mean of short-time envelope) of the
                   bio-band-filtered signal. Bursty biological activity
                   (worm rasps, arthropod tunnelling) has high crest; the
                   continuous broadband / harmonic-comb signature of a
                   propeller plane, helicopter, or sustained background
                   noise has low crest. Mapped to [0, 1] by linear
                   interpolation between ``transient_gate.low`` and
                   ``transient_gate.high`` thresholds.
                   Answers: is this bursty (biology) or continuous (machine)?

  SAI_v2 = ndsi_01 × bio_rms_norm × transient_gate

This is multiplicative on purpose: a recording must be (a) audible in the
bio band, (b) biological in spectral balance, AND (c) bursty in time to
score high. Failure modes by case:

  silence                bio_rms ≈ 0           → score 0
  distant jet            NDSI strongly −ve     → score 0
  mains hum              notched out + NDSI −ve→ score 0
  propeller plane        transient_gate ≈ 0    → score 0  (continuous comb)
  helicopter             transient_gate ≈ 0    → score 0
  worm in quiet soil     all three terms high  → high score
  worm during overflight transient_gate ≈ 0    → score 0  (correctly: SNR
                                                            unrecoverable
                                                            without
                                                            multi-mic
                                                            denoising)

Mains hum
---------
A notch cascade at 50, 100, 150, 200 Hz (Q = 30) is applied before the
power-spectrum split, removing UK mains contamination that would otherwise
inflate the anthropogenic band.

Soil Acoustic Index v1 (legacy, retained for trend continuity)
--------------------------------------------------------------
The original composite (0.4 RMS + 0.4 ACI + 0.2 spectral entropy) is still
computed and reported in metadata as ``sai_v1`` so longitudinal comparisons
against historical detections.csv rows remain meaningful. To make v1 the
primary score again, set ``soil.ndsi.enabled: false`` in settings.yaml.

Activity levels (v2)
--------------------
  SAI_v2 ≥ 0.65  →  High Soil Activity
  SAI_v2 ≥ 0.35  →  Moderate Soil Activity
  SAI_v2 < 0.35  →  Low Soil Activity

These thresholds are inherited from v1 pending calibration against labelled
recordings from a probe rod in known-quiet and known-active soil.

Beta note
---------
SAI v2 is signal-processing-derived, not data-driven. Treat outputs as
indicative and useful for relative comparison across time on a single probe.
Absolute values should not be compared across different microphones or
locations without recalibration.

Author: David Green, Blenheim Palace
Acoustic indices after: Pieretti et al. (2011), Pijanowski et al. (2011)
"""

from typing import Any

import numpy as np
from scipy import signal as scisig

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection


class SoilClassifier(BaseClassifier):
    """Soil Acoustic Index (SAI) classifier — v2 primary, v1 alongside."""

    name = "soil"

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: Section from settings.yaml under the 'soil' key.

            min_confidence    Minimum SAI to report a detection. Default 0.1
                              (very low — beta mode logs all meaningful activity).
            rms_scale         v1 RMS scale (legacy, retained for trend continuity).
            aci_scale         v1 ACI scale (legacy).
            bio_rms_scale     v2: RMS in the bio band that maps to 1.0 contribution.
                              Tune to your probe's typical worm-activity level.
            ndsi.enabled      If False, fall back to v1 SAI as the primary score.
            ndsi.anthro_hz    [low, high] of the human-noise band (default [50, 300]).
            ndsi.bio_hz       [low, high] of the biological band   (default [500, 2000]).
            ndsi.mains_hz     Mains-harmonic centre frequencies to notch out.
            ndsi.mains_q      Notch sharpness (higher = narrower notch).
            ndsi.transient_gate.low   Crest factor at which gate is fully closed
                                      (continuous noise — aircraft, helicopter,
                                      sustained rumble). Default 1.5.
            ndsi.transient_gate.high  Crest factor at which gate is fully open
                                      (clearly bursty — worm rasps).
                                      Default 4.0.
            ndsi.transient_gate.win_ms  Short-time envelope window (ms).
                                        Default 30 (~ worm-rasp duration).
        """
        # v1 (legacy, unchanged)
        self._min_confidence: float = config.get("min_confidence", 0.1)
        self._rms_scale: float = config.get("rms_scale", 0.05)
        self._aci_scale: float = config.get("aci_scale", 0.5)

        # v2 (new)
        ndsi_cfg = config.get("ndsi") or {}
        self._v2_enabled: bool = bool(ndsi_cfg.get("enabled", True))
        self._anthro_hz: tuple[float, float] = tuple(ndsi_cfg.get("anthro_hz", [50, 300]))
        self._bio_hz: tuple[float, float] = tuple(ndsi_cfg.get("bio_hz", [500, 2000]))
        self._mains_hz: list[float] = list(ndsi_cfg.get("mains_hz", [50, 100, 150, 200]))
        self._mains_q: float = float(ndsi_cfg.get("mains_q", 30.0))
        self._bio_rms_scale: float = float(config.get("bio_rms_scale", 0.01))

        gate_cfg = ndsi_cfg.get("transient_gate") or {}
        self._gate_low: float = float(gate_cfg.get("low", 1.5))
        self._gate_high: float = float(gate_cfg.get("high", 4.0))
        self._gate_win_ms: float = float(gate_cfg.get("win_ms", 30.0))

        # Cached bio-band SOS filter (built lazily once sample rate is known)
        self._bio_sos: np.ndarray | None = None
        self._bio_sos_key: tuple | None = None

        # Built lazily on first chunk once sample rate is known
        self._notch_sos: np.ndarray | None = None
        self._notch_sr: int | None = None

    @property
    def sample_rate(self) -> int:
        return 22050

    @property
    def freq_min_hz(self) -> int:
        # Keep the processor pass wide enough that the anthro band is still
        # measurable when we split the spectrum below. The v2 notch cascade
        # handles mains contamination inside classify().
        return 50

    @property
    def freq_max_hz(self) -> int:
        return 2000

    def load(self) -> None:
        pass

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Compute SAI v1 + v2 from a bandpassed audio chunk and emit one Detection.

        Args:
            chunk: 22.05 kHz audio, 50–2000 Hz bandpass applied by AudioProcessor.

        Returns:
            A single Detection whose confidence IS the primary SAI (v2 by default,
            v1 if ``ndsi.enabled: false``), or an empty list if below min_confidence.
        """
        audio = chunk.data.astype(np.float64)
        if len(audio) == 0:
            return []

        # ── v1 SAI: unchanged from previous release, kept for trend continuity ──
        rms = float(np.sqrt(np.mean(audio ** 2)))
        aci = self._acoustic_complexity_index(audio)
        entropy = self._spectral_entropy(audio)
        rms_norm = min(rms / max(self._rms_scale, 1e-10), 1.0)
        aci_norm = min(aci / max(self._aci_scale, 1e-10), 1.0)
        sai_v1 = round(0.4 * rms_norm + 0.4 * aci_norm + 0.2 * entropy, 4)

        # ── v2 SAI: notch mains, split anthro/bio bands, NDSI × bio_rms ──
        sai_v2: float | None = None
        ndsi: float | None = None
        bio_rms: float | None = None
        bio_p: float | None = None
        anthro_p: float | None = None

        transient_crest: float | None = None
        transient_gate: float | None = None
        if self._v2_enabled:
            notched = self._apply_mains_notches(audio, chunk.sample_rate)
            freqs, psd = scisig.welch(
                notched,
                fs=chunk.sample_rate,
                nperseg=min(2048, len(notched)),
            )
            anthro_p = self._band_power(freqs, psd, *self._anthro_hz)
            bio_p = self._band_power(freqs, psd, *self._bio_hz)
            bio_rms = float(np.sqrt(bio_p)) if bio_p > 0 else 0.0

            denom = bio_p + anthro_p
            ndsi = float((bio_p - anthro_p) / denom) if denom > 1e-20 else 0.0
            ndsi_01 = (ndsi + 1.0) / 2.0
            bio_rms_norm = min(bio_rms / max(self._bio_rms_scale, 1e-10), 1.0)

            # Transient gate — separates bursty biology from continuous noise
            # (aircraft, helicopter, sustained rumble) inside the bio band.
            transient_crest = self._bio_band_crest(notched, chunk.sample_rate)
            span = max(self._gate_high - self._gate_low, 1e-6)
            transient_gate = float(np.clip(
                (transient_crest - self._gate_low) / span, 0.0, 1.0,
            ))

            sai_v2 = round(ndsi_01 * bio_rms_norm * transient_gate, 4)

        confidence = sai_v2 if sai_v2 is not None else sai_v1

        if confidence < self._min_confidence:
            return []

        if confidence >= 0.65:
            level = "High"
        elif confidence >= 0.35:
            level = "Moderate"
        else:
            level = "Low"

        metadata: dict[str, Any] = {
            "sai_v1": sai_v1,
            "rms_energy": round(rms, 6),
            "aci": round(aci, 4),
            "spectral_entropy": round(entropy, 4),
            "activity_level": level,
            "beta": True,
        }
        if sai_v2 is not None:
            metadata.update({
                "sai_v2": sai_v2,
                "ndsi": round(ndsi, 4),
                "bio_band_hz": list(self._bio_hz),
                "anthro_band_hz": list(self._anthro_hz),
                "bio_band_power": float(f"{bio_p:.6e}"),
                "anthro_band_power": float(f"{anthro_p:.6e}"),
                "bio_rms": round(bio_rms, 6),
                "bio_band_crest": round(transient_crest, 3) if transient_crest is not None else None,
                "transient_gate": round(transient_gate, 3) if transient_gate is not None else None,
            })
        # Mirror current primary into ``sai`` for backwards-compat consumers.
        metadata["sai"] = confidence

        return [Detection(
            label=f"Soil Activity — {level}",
            confidence=confidence,
            classifier=self.name,
            timestamp=chunk.timestamp,
            metadata=metadata,
        )]

    # ------------------------------------------------------------------
    # v2 helpers
    # ------------------------------------------------------------------

    def _apply_mains_notches(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Cascade IIR notches at the configured mains harmonics."""
        if self._notch_sos is None or self._notch_sr != sr:
            sections: list[np.ndarray] = []
            nyq = sr / 2.0
            for f0 in self._mains_hz:
                if 0 < f0 < nyq:
                    b, a = scisig.iirnotch(f0, self._mains_q, fs=sr)
                    sections.append(scisig.tf2sos(b, a))
            self._notch_sos = np.vstack(sections) if sections else None
            self._notch_sr = sr

        if self._notch_sos is None:
            return audio
        return scisig.sosfilt(self._notch_sos, audio)

    @staticmethod
    def _band_power(freqs: np.ndarray, psd: np.ndarray, low: float, high: float) -> float:
        """Integrate PSD over [low, high] Hz using the trapezoidal rule."""
        mask = (freqs >= low) & (freqs <= high)
        if not mask.any():
            return 0.0
        # ``np.trapezoid`` is the NumPy 2 replacement for the removed ``np.trapz``.
        integrate = getattr(np, "trapezoid", None) or np.trapz  # type: ignore[attr-defined]
        return float(integrate(psd[mask], freqs[mask]))

    def _bio_band_crest(self, audio: np.ndarray, sr: int) -> float:
        """Crest factor of the short-time envelope in the bio band.

        High (> ~4) for bursty, biological signals; low (~1) for continuous
        noise like aircraft, helicopters, sustained rumble.
        """
        low, high = float(self._bio_hz[0]), float(self._bio_hz[1])
        nyq = sr / 2.0
        if not (0 < low < high < nyq):
            return 1.0

        key = (sr, low, high)
        if self._bio_sos is None or self._bio_sos_key != key:
            self._bio_sos = scisig.butter(
                5, [low / nyq, high / nyq], btype="band", output="sos",
            )
            self._bio_sos_key = key

        band = scisig.sosfilt(self._bio_sos, audio)
        envelope = np.abs(scisig.hilbert(band))

        win = max(int(sr * self._gate_win_ms / 1000.0), 1)
        n_frames = len(envelope) // win
        if n_frames < 2:
            return 1.0
        frame_rms = np.sqrt(np.mean(
            envelope[: n_frames * win].reshape(n_frames, win) ** 2,
            axis=1,
        ))
        mean = float(frame_rms.mean())
        if mean <= 1e-12:
            return 1.0
        return float(frame_rms.max() / mean)

    # ------------------------------------------------------------------
    # v1 helpers (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def _acoustic_complexity_index(audio: np.ndarray, n_fft: int = 512, hop: int = 256) -> float:
        if len(audio) < n_fft:
            return 0.0
        n_frames = (len(audio) - n_fft) // hop + 1
        if n_frames < 2:
            return 0.0
        spectrogram = np.array([
            np.abs(np.fft.rfft(audio[i * hop: i * hop + n_fft]))
            for i in range(n_frames)
        ])
        diffs = np.abs(np.diff(spectrogram, axis=0))
        sums = spectrogram[:-1].sum(axis=0) + 1e-10
        aci_per_bin = diffs.sum(axis=0) / sums
        return float(aci_per_bin.mean())

    @staticmethod
    def _spectral_entropy(audio: np.ndarray) -> float:
        spectrum = np.abs(np.fft.rfft(audio)) ** 2
        total = spectrum.sum()
        if total == 0:
            return 0.0
        p = spectrum / total
        entropy = -np.sum(p * np.log2(p + 1e-12))
        max_entropy = np.log2(len(p))
        return float(entropy / max_entropy) if max_entropy > 0 else 0.0
