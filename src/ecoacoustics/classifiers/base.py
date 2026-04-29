from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ecoacoustics.audio.capture import AudioChunk


@dataclass
class Detection:
    label: str
    confidence: float
    classifier: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.classifier}] {self.label} ({self.confidence:.0%})"


class BaseClassifier(ABC):
    """
    Contract that every classifier must implement.

    Each classifier is responsible for its own required sample rate and
    frequency range — the pipeline will set up the appropriate AudioProcessor
    automatically based on the config values returned by these properties.
    """

    name: str = "base"

    @property
    @abstractmethod
    def sample_rate(self) -> int: ...

    @property
    def freq_min_hz(self) -> int | None:
        return None

    @property
    def freq_max_hz(self) -> int | None:
        return None

    @abstractmethod
    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Return zero or more detections for the given audio chunk."""
        ...

    def load(self) -> None:
        """Called once at startup to load models/weights into memory."""

    def cleanup(self) -> None:
        """Called on shutdown to release any resources (temp files, handles)."""
