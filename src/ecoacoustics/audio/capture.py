"""
Live microphone audio capture with a bounded, thread-safe chunk queue.

Wraps sounddevice.InputStream and accumulates raw PCM samples into fixed-
duration AudioChunk objects that downstream classifiers consume.  The queue
is bounded so that if a classifier runs slower than real time, old chunks
are dropped rather than consuming unbounded memory.

Author: David Green, Blenheim Palace
"""

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
    """A fixed-duration slice of mono float32 audio from the microphone.

    Attributes:
        data: PCM samples as float32, shape (n_samples,).
        sample_rate: Samples per second (e.g. 48000).
        timestamp: Unix epoch time at which the chunk was captured.
    """

    data: np.ndarray
    sample_rate: int
    timestamp: float


class AudioCapture:
    """Streams audio from a microphone into a thread-safe bounded queue.

    A sounddevice InputStream callback accumulates incoming PCM frames into
    an internal rolling buffer. Whenever the buffer contains enough samples
    for a complete chunk (sample_rate × chunk_duration), an AudioChunk is
    enqueued for the classifier threads to consume via get_chunk().

    If the queue is full (classifier is too slow), the incoming chunk is
    silently discarded and the dropped_chunks counter is incremented.  The
    Watchdog monitors this counter and warns the operator.
    """

    def __init__(
        self,
        sample_rate: int,
        chunk_duration: float,
        device: Optional[int | str] = None,
        channels: int = 1,
        max_queue_size: int = MAX_QUEUE_SIZE,
    ):
        """
        Args:
            sample_rate: Target sample rate in Hz (e.g. 48000 for BirdNET).
            chunk_duration: Length of each analysis window in seconds.
            device: sounddevice device index or name; None uses the system default.
            channels: Number of input channels (mono recordings use 1).
            max_queue_size: Maximum chunks held in the queue before dropping begins.
        """
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
        self._started_at: float = 0.0   # unix time when stream was last opened
        self._overflow_count: int = 0   # sounddevice input overflow events
        self._chunk_start_time: float = 0.0  # wall time when current chunk accumulation began
        self._last_rms: float = 0.0     # RMS of the most recent callback frame

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the sounddevice input stream, retrying up to 3 times on transient errors."""
        import sounddevice as sd
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="float32",
                    device=self.device,
                    callback=self._callback,
                )
                self._stream.start()
                self._last_chunk_time = 0.0    # reset so watchdog measures from now
                self._chunk_start_time = 0.0   # will be set on first callback
                self._started_at = time.time()
                return
            except Exception as exc:
                last_exc = exc
                if self._stream:
                    try:
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def stop(self) -> None:
        """Stop and close the audio stream, draining any unprocessed chunks.

        Draining ensures that if this capture is reused (or a new pipeline
        starts shortly after), no stale audio from the previous session
        lingers in the queue and gets processed out of context.
        """
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        drained = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                drained += 1
            except queue.Empty:
                break
        if drained:
            import logging
            logging.getLogger(__name__).debug(
                "AudioCapture.stop: drained %d stale chunks from queue", drained
            )
        self._started_at = 0.0

    def restart(self) -> None:
        """Stop the stream, drain stale queued audio, then restart.

        Called by the Watchdog when the stream appears to have gone silent
        unexpectedly (e.g. USB microphone briefly disconnected).
        stop() now handles queue draining, so we just reset the buffer and reopen.
        """
        self.stop()
        with self._lock:
            self._buffer = np.zeros(0, dtype=np.float32)
        time.sleep(1.0)
        self.start()

    def get_chunk(self, timeout: float = 5.0) -> Optional[AudioChunk]:
        """Block until a chunk is available or timeout elapses.

        Returns:
            The next AudioChunk, or None if no chunk arrived within timeout.
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @staticmethod
    def list_devices() -> None:
        """Print all available audio input/output devices to stdout."""
        import sounddevice as sd
        print(sd.query_devices())

    # ------------------------------------------------------------------
    # Health properties (read by Watchdog)
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True if the underlying sounddevice stream is open and running."""
        return self._stream is not None and self._stream.active

    @property
    def started_at(self) -> float:
        """Unix timestamp when the stream was last opened; 0 before first start."""
        return self._started_at

    @property
    def queue_depth(self) -> int:
        """Current number of chunks waiting in the queue."""
        return self._queue.qsize()

    @property
    def queue_capacity(self) -> int:
        """Maximum number of chunks the queue can hold before dropping."""
        return self._queue_capacity

    @property
    def dropped_chunks(self) -> int:
        """Cumulative count of chunks discarded due to a full queue."""
        return self._dropped

    @property
    def last_chunk_time(self) -> float:
        """Unix timestamp of the most recently enqueued chunk; 0 before first chunk."""
        return self._last_chunk_time

    @property
    def overflow_count(self) -> int:
        """Number of sounddevice input-overflow events since stream start."""
        return self._overflow_count

    @property
    def last_rms(self) -> float:
        """RMS amplitude of the most recently received audio frame (updated every callback)."""
        return self._last_rms

    # ------------------------------------------------------------------
    # Internal callback (runs in sounddevice thread)
    # ------------------------------------------------------------------

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        """Accumulate incoming PCM frames and emit complete chunks to the queue.

        Runs in the sounddevice audio thread — must not block.

        chunk.timestamp is the wall-clock time of the FIRST sample in the chunk
        (i.e. when the recording window opened), so detections are logged against
        when the animal called, not when the classifier finished processing.
        """
        if status.input_overflow:
            self._overflow_count += 1

        mono = indata[:, 0] if indata.ndim > 1 else indata.ravel()
        self._last_rms = float(np.sqrt(np.mean(mono ** 2)))
        now = time.time()

        with self._lock:
            if len(self._buffer) == 0:
                # First samples of a new chunk — record the wall time of this moment.
                self._chunk_start_time = now

            self._buffer = np.concatenate([self._buffer, mono])
            while len(self._buffer) >= self.chunk_samples:
                chunk_data = self._buffer[: self.chunk_samples].copy()
                self._buffer = self._buffer[self.chunk_samples :]
                chunk = AudioChunk(
                    data=chunk_data,
                    sample_rate=self.sample_rate,
                    timestamp=self._chunk_start_time,
                )
                # Advance start time for any back-to-back chunks extracted in
                # the same callback (rare, but possible on large frame sizes).
                self._chunk_start_time += self.chunk_samples / self.sample_rate
                try:
                    self._queue.put_nowait(chunk)
                    self._last_chunk_time = now  # wall clock for watchdog stale check
                except queue.Full:
                    # Queue is full — discard rather than blocking the callback,
                    # which would cause an audio dropout on the input stream.
                    self._dropped += 1
