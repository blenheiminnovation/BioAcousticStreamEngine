"""
Abstract base classifier and Detection dataclass.

Every organism classifier (bird, bat, insect, soil) inherits from
BaseClassifier and implements classify().  The pipeline discovers
classifiers through the REGISTRY in classifiers/__init__.py and
calls load() once at startup, classify() for every audio chunk, and
cleanup() on shutdown.

Author: David Green, Blenheim Palace
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ecoacoustics.audio.capture import AudioChunk


@dataclass
class Detection:
    """A single species identification returned by a classifier.

    Attributes:
        label: Common name of the detected species (e.g. "Robin").
        confidence: Model confidence score in the range [0, 1].
        classifier: Name of the classifier that produced this detection.
        timestamp: Unix epoch time of the audio chunk that was analysed.
        metadata: Classifier-specific extras (e.g. scientific_name, start_time).
    """

    label: str
    confidence: float
    classifier: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.classifier}] {self.label} ({self.confidence:.0%})"


class BaseClassifier(ABC):
    """Contract that every organism classifier must implement.

    The pipeline sets up one AudioCapture stream per unique sample_rate
    and one AudioProcessor per classifier, so each subclass only needs to
    declare the rate and frequency band it requires — the infrastructure
    handles resampling and filtering automatically.
    """

    name: str = "base"

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Sample rate (Hz) this classifier's model was trained on."""
        ...

    @property
    def freq_min_hz(self) -> int | None:
        """Lower bandpass frequency (Hz); None means no high-pass filter."""
        return None

    @property
    def freq_max_hz(self) -> int | None:
        """Upper bandpass frequency (Hz); None means no low-pass filter."""
        return None

    @abstractmethod
    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Run inference on one audio chunk and return any detections found.

        Args:
            chunk: Pre-processed audio at this classifier's sample_rate.

        Returns:
            List of Detection objects (empty list if nothing detected).
        """
        ...

    def load(self) -> None:
        """Load model weights and allocate resources.

        Called once per session before the first call to classify().
        Subclasses that require heavy initialisation (e.g. loading a TFLite
        model) should perform that work here rather than in __init__.
        """

    def cleanup(self) -> None:
        """Release resources acquired in load() (temp files, handles, etc.).

        Called after the last classify() call in a session.
        """
