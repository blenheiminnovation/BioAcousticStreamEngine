"""
Audio pre-processing: resampling and bandpass filtering.

Each classifier operates at a specific sample rate and frequency range.
AudioProcessor prepares a raw AudioChunk for a given classifier by
resampling to the target rate and optionally applying a Butterworth
bandpass filter to remove out-of-band noise before inference.

Author: David Green, Blenheim Palace
"""

from typing import Optional

import numpy as np
import scipy.signal as signal

from ecoacoustics.audio.capture import AudioChunk


class AudioProcessor:
    """Resamples and bandpass-filters an AudioChunk for a target classifier.

    One AudioProcessor is created per active classifier.  The pipeline calls
    process() on every incoming chunk before passing it to classify(), ensuring
    that each classifier always receives audio at the correct sample rate and
    with irrelevant frequency content suppressed.
    """

    def __init__(
        self,
        target_sample_rate: int,
        freq_min_hz: Optional[int] = None,
        freq_max_hz: Optional[int] = None,
    ):
        """
        Args:
            target_sample_rate: Sample rate the classifier expects (Hz).
            freq_min_hz: Lower edge of the bandpass filter (Hz). None = no high-pass.
            freq_max_hz: Upper edge of the bandpass filter (Hz). None = no low-pass.
        """
        self.target_sample_rate = target_sample_rate
        self.freq_min_hz = freq_min_hz
        self.freq_max_hz = freq_max_hz

    def process(self, chunk: AudioChunk) -> AudioChunk:
        """Resample then bandpass-filter the chunk.

        Returns a new AudioChunk at target_sample_rate.  The original chunk
        is not modified.
        """
        audio = chunk.data

        if chunk.sample_rate != self.target_sample_rate:
            audio = self._resample(audio, chunk.sample_rate, self.target_sample_rate)

        if self.freq_min_hz or self.freq_max_hz:
            audio = self._bandpass(audio, self.target_sample_rate)

        return AudioChunk(
            data=audio,
            sample_rate=self.target_sample_rate,
            timestamp=chunk.timestamp,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resample(self, audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        """Resample audio from src_rate to dst_rate using librosa."""
        import librosa
        return librosa.resample(audio, orig_sr=src_rate, target_sr=dst_rate)

    def _bandpass(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Apply a 5th-order Butterworth bandpass (or highpass/lowpass) filter."""
        nyq = sr / 2.0
        low = (self.freq_min_hz / nyq) if self.freq_min_hz else None
        high = (self.freq_max_hz / nyq) if self.freq_max_hz else None

        if low and high:
            b, a = signal.butter(5, [low, high], btype="band")
        elif low:
            b, a = signal.butter(5, low, btype="high")
        else:
            b, a = signal.butter(5, high, btype="low")

        return signal.lfilter(b, a, audio).astype(np.float32)
