import numpy as np
import pytest

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.audio.processor import AudioProcessor
from ecoacoustics.classifiers.soil import SoilClassifier


def _make_chunk(sr: int = 22050, duration: float = 3.0, rms: float = 0.05) -> AudioChunk:
    n = int(sr * duration)
    data = np.random.randn(n).astype(np.float32) * rms
    return AudioChunk(data=data, sample_rate=sr, timestamp=0.0)


def test_soil_classifier_detects_above_threshold():
    clf = SoilClassifier({"min_confidence": 0.4, "energy_threshold": 0.01})
    chunk = _make_chunk(rms=0.1)
    detections = clf.classify(chunk)
    assert len(detections) == 1
    assert detections[0].classifier == "soil"
    assert detections[0].confidence >= 0.4


def test_soil_classifier_silent_audio():
    clf = SoilClassifier({"min_confidence": 0.4, "energy_threshold": 0.01})
    chunk = _make_chunk(rms=0.0001)
    assert clf.classify(chunk) == []


def test_audio_processor_bandpass():
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
    processor = AudioProcessor(target_sample_rate=22050)
    chunk = _make_chunk(sr=44100, rms=0.1)
    result = processor.process(chunk)
    assert result.sample_rate == 22050
