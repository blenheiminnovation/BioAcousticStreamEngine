from typing import Optional

import numpy as np
import scipy.signal as signal

from ecoacoustics.audio.capture import AudioChunk


class AudioProcessor:
    """Resamples and bandpass-filters an AudioChunk for a target classifier."""

    def __init__(
        self,
        target_sample_rate: int,
        freq_min_hz: Optional[int] = None,
        freq_max_hz: Optional[int] = None,
    ):
        self.target_sample_rate = target_sample_rate
        self.freq_min_hz = freq_min_hz
        self.freq_max_hz = freq_max_hz

    def process(self, chunk: AudioChunk) -> AudioChunk:
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

    def _resample(self, audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        import librosa
        return librosa.resample(audio, orig_sr=src_rate, target_sr=dst_rate)

    def _bandpass(self, audio: np.ndarray, sr: int) -> np.ndarray:
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
