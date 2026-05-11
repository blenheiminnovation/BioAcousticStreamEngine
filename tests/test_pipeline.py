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
    """v1 fallback: SoilClassifier with NDSI disabled should fire on plain
    audio energy. This documents the legacy code path used when
    ``ndsi.enabled: false`` in settings.yaml."""
    clf = SoilClassifier({"min_confidence": 0.4, "ndsi": {"enabled": False}})
    chunk = _make_chunk(rms=0.1)
    detections = clf.classify(chunk)
    assert len(detections) == 1
    assert detections[0].classifier == "soil"
    assert detections[0].confidence >= 0.4


def test_soil_classifier_silent_audio():
    """SoilClassifier should return no detections for near-silent audio.

    Holds for both v1 (low RMS) and v2 (zero bio_rms → zero score)."""
    clf = SoilClassifier({"min_confidence": 0.4})
    chunk = _make_chunk(rms=0.0001)
    assert clf.classify(chunk) == []


def test_soil_v2_rejects_low_frequency_rumble():
    """v2 SAI should suppress traffic/footstep rumble even at high RMS.

    A pure 50–150 Hz signal mimics traffic, footsteps, aircraft, HVAC. NDSI
    must drive sai_v2 toward zero so the rod doesn't report soil activity
    when only surface seismic noise is present.
    """
    sr = 22050
    t = np.arange(int(sr * 3.0)) / sr
    rumble = (np.sin(2 * np.pi * 45 * t)
              + 0.7 * np.sin(2 * np.pi * 80 * t)
              + 0.4 * np.sin(2 * np.pi * 130 * t)) * 0.05
    chunk = AudioChunk(data=rumble.astype(np.float32), sample_rate=sr, timestamp=0.0)

    clf = SoilClassifier({"min_confidence": 0.0})
    dets = clf.classify(chunk)
    assert dets, "min_confidence=0 should always emit a Detection so we can read v2"
    meta = dets[0].metadata
    assert meta["ndsi"] < -0.5, f"expected strongly anthropogenic NDSI, got {meta['ndsi']}"
    assert meta["sai_v2"] < 0.05, f"v2 should suppress pure rumble, got {meta['sai_v2']}"


def test_soil_v2_flags_worm_band_activity():
    """v2 SAI should reward energy in the 500-2000 Hz bio band when the
    anthropogenic band is quiet."""
    sr = 22050
    rng = np.random.default_rng(0)
    duration = 3.0
    n = int(sr * duration)
    audio = np.zeros(n)
    # 20 short tone bursts in the worm-rasp range
    for onset in rng.uniform(0, duration, 20):
        i = int(onset * sr)
        burst_len = int(0.03 * sr)
        env = np.exp(-np.arange(min(burst_len, n - i)) / (sr * 0.005))
        carrier = np.sin(2 * np.pi * rng.uniform(700, 1500)
                         * np.arange(len(env)) / sr)
        audio[i:i + len(env)] += carrier * env * 0.05
    chunk = AudioChunk(data=audio.astype(np.float32), sample_rate=sr, timestamp=0.0)

    clf = SoilClassifier({"min_confidence": 0.0})
    dets = clf.classify(chunk)
    assert dets
    meta = dets[0].metadata
    assert meta["ndsi"] > 0.5, f"expected strongly biological NDSI, got {meta['ndsi']}"
    assert meta["sai_v2"] > 0.1, f"v2 should flag worm-band activity, got {meta['sai_v2']}"


def test_soil_v2_rejects_propeller_plane():
    """v2 SAI must reject a propeller plane / helicopter overflight.

    Propeller harmonics extend into the bio band (80 Hz × 7 = 560 Hz, etc.)
    so band-power split alone is not enough. The transient gate notices
    that the signal is temporally continuous (low crest in the bio band)
    and forces the score to zero.
    """
    sr = 22050
    t = np.arange(int(sr * 3.0)) / sr
    # Simulate a propeller plane: 80 Hz fundamental + 25 harmonics
    prop = np.zeros_like(t)
    for n in range(1, 26):
        prop += np.sin(2 * np.pi * 80 * n * t) * (0.05 / n)
    chunk = AudioChunk(data=prop.astype(np.float32), sample_rate=sr, timestamp=0.0)

    clf = SoilClassifier({"min_confidence": 0.0})
    dets = clf.classify(chunk)
    assert dets
    meta = dets[0].metadata
    assert meta["bio_band_crest"] < 2.0, (
        f"propeller plane should be temporally continuous; "
        f"crest = {meta['bio_band_crest']}"
    )
    assert meta["transient_gate"] < 0.2, f"gate should be closed; got {meta['transient_gate']}"
    assert meta["sai_v2"] < 0.05, f"v2 should reject prop plane; got {meta['sai_v2']}"


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
