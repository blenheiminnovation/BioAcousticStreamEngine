import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

# How many 3-second chunks to buffer before dropping. At 3s/chunk this is
# ~60s of headroom for the classifier to catch up before we start losing audio.
MAX_QUEUE_SIZE = 20


@dataclass
class AudioChunk:
    data: np.ndarray          # float32, shape (n_samples,)
    sample_rate: int
    timestamp: float          # seconds since epoch


class AudioCapture:
    """Streams audio from a microphone into a thread-safe bounded queue."""

    def __init__(
        self,
        sample_rate: int,
        chunk_duration: float,
        device: Optional[int | str] = None,
        channels: int = 1,
        max_queue_size: int = MAX_QUEUE_SIZE,
    ):
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_duration)
        self.device = device
        self.channels = channels

        self._queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=max_queue_size)
        self._queue_capacity = max_queue_size
        self._buffer = np.zeros(0, dtype=np.float32)
        self._stream = None
        self._lock = threading.Lock()

        self._dropped: int = 0          # chunks discarded when queue was full
        self._last_chunk_time: float = 0.0
        self._overflow_count: int = 0   # sounddevice input overflow events

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        import sounddevice as sd
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
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def restart(self) -> None:
        """Stop and restart the audio stream (e.g. after device error)."""
        self.stop()
        # Drain the queue so stale audio doesn't clog the classifier
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            self._buffer = np.zeros(0, dtype=np.float32)
        time.sleep(1.0)
        self.start()

    def get_chunk(self, timeout: float = 5.0) -> Optional[AudioChunk]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @staticmethod
    def list_devices() -> None:
        import sounddevice as sd
        print(sd.query_devices())

    # ------------------------------------------------------------------
    # Health properties (read by Watchdog)
    # ------------------------------------------------------------------

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def queue_capacity(self) -> int:
        return self._queue_capacity

    @property
    def dropped_chunks(self) -> int:
        return self._dropped

    @property
    def last_chunk_time(self) -> float:
        return self._last_chunk_time

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    # ------------------------------------------------------------------
    # Internal callback (runs in sounddevice thread)
    # ------------------------------------------------------------------

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status.input_overflow:
            self._overflow_count += 1

        mono = indata[:, 0] if indata.ndim > 1 else indata.ravel()

        with self._lock:
            self._buffer = np.concatenate([self._buffer, mono])
            while len(self._buffer) >= self.chunk_samples:
                chunk_data = self._buffer[: self.chunk_samples].copy()
                self._buffer = self._buffer[self.chunk_samples :]
                chunk = AudioChunk(
                    data=chunk_data,
                    sample_rate=self.sample_rate,
                    timestamp=time.time(),
                )
                try:
                    self._queue.put_nowait(chunk)
                    self._last_chunk_time = chunk.timestamp
                except queue.Full:
                    # Queue is full — discard this chunk rather than blocking
                    # the audio callback (which would cause a dropout).
                    self._dropped += 1
