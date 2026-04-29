import queue
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import sounddevice as sd


@dataclass
class AudioChunk:
    data: np.ndarray          # float32, shape (n_samples,)
    sample_rate: int
    timestamp: float          # seconds since epoch


class AudioCapture:
    """Streams audio from a microphone into a thread-safe queue."""

    def __init__(
        self,
        sample_rate: int,
        chunk_duration: float,
        device: Optional[int | str] = None,
        channels: int = 1,
    ):
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_duration)
        self.device = device
        self.channels = channels

        self._queue: queue.Queue[AudioChunk] = queue.Queue()
        self._buffer = np.zeros(0, dtype=np.float32)
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def get_chunk(self, timeout: float = 5.0) -> Optional[AudioChunk]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @staticmethod
    def list_devices() -> None:
        print(sd.query_devices())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        import time as _time

        if status:
            # surfaced as a warning rather than crashing the stream
            print(f"[audio] {status}")

        mono = indata[:, 0] if indata.ndim > 1 else indata.ravel()

        with self._lock:
            self._buffer = np.concatenate([self._buffer, mono])
            while len(self._buffer) >= self.chunk_samples:
                chunk_data = self._buffer[: self.chunk_samples].copy()
                self._buffer = self._buffer[self.chunk_samples :]
                self._queue.put(
                    AudioChunk(
                        data=chunk_data,
                        sample_rate=self.sample_rate,
                        timestamp=_time.time(),
                    )
                )
