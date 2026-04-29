"""
Unit tests for core pipeline components.

Tests cover the soil classifier's energy threshold logic, AudioProcessor
resampling and bandpass filtering, and the queue-drop behaviour of AudioCapture.
These tests are designed to run without a microphone or GPU.

Author: David Green, Blenheim Palace
"""

import numpy as np
import pytest

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.audio.processor import AudioProcessor
from ecoacoustics.classifiers.soil import SoilClassifier


def _make_chunk(sr: int = 22050, duration: float = 3.0, rms: float = 0.05) -> AudioChunk:
    """Create a synthetic AudioChunk filled with Gaussian noise at a given RMS level."""
    n = int(sr * duration)
    data = np.random.randn(n).astype(np.float32) * rms
    return AudioChunk(data=data, sample_rate=sr, timestamp=0.0)


def test_soil_classifier_detects_above_threshold():
    """SoilClassifier should return a detection when RMS exceeds the energy threshold."""
    clf = SoilClassifier({"min_confidence": 0.4, "energy_threshold": 0.01})
    chunk = _make_chunk(rms=0.1)
    detections = clf.classify(chunk)
    assert len(detections) == 1
    assert detections[0].classifier == "soil"
    assert detections[0].confidence >= 0.4


def test_soil_classifier_silent_audio():
    """SoilClassifier should return no detections for near-silent audio."""
    clf = SoilClassifier({"min_confidence": 0.4, "energy_threshold": 0.01})
    chunk = _make_chunk(rms=0.0001)
    assert clf.classify(chunk) == []


def test_audio_processor_bandpass():
    """AudioProcessor should apply a bandpass filter and preserve the sample rate."""
    processor = AudioProcessor(
        target_sample_rate=22050,
        freq_min_hz=100,
        freq_max_hz=1000,
    )
    chunk = _make_chunk(sr=22050, rms=0.1)
    result = processor.process(chunk)
    assert result.sample_rate == 22050
    assert result.data.dtype == np.float32


def test_audio_processor_resample():
    """AudioProcessor should resample audio to the target sample rate."""
    processor = AudioProcessor(target_sample_rate=22050)
    chunk = _make_chunk(sr=44100, rms=0.1)
    result = processor.process(chunk)
    assert result.sample_rate == 22050


def test_audio_capture_queue_drop():
    """AudioCapture should drop incoming chunks when the queue is full."""
    import time
    from ecoacoustics.audio.capture import AudioCapture

    cap = AudioCapture(sample_rate=48000, chunk_duration=3.0, max_queue_size=3)

    # Fill queue to capacity manually
    for _ in range(3):
        cap._queue.put_nowait(AudioChunk(np.zeros(144000, np.float32), 48000, time.time()))

    # Simulate callback with a full chunk — should trigger a drop
    audio = np.zeros((144000, 1), dtype="float32")
    status = type("S", (), {"input_overflow": False})()
    cap._callback(audio, 144000, None, status)

    assert cap.queue_depth == 3, "Queue should remain at capacity"
    assert cap.dropped_chunks == 1, "One chunk should have been dropped"
