from ecoacoustics.classifiers.base import BaseClassifier, Detection
from ecoacoustics.classifiers.bird import BirdClassifier
from ecoacoustics.classifiers.bat import BatClassifier
from ecoacoustics.classifiers.insect import InsectClassifier
from ecoacoustics.classifiers.soil import SoilClassifier

REGISTRY: dict[str, type[BaseClassifier]] = {
    "bird": BirdClassifier,
    "bat": BatClassifier,
    "insect": InsectClassifier,
    "soil": SoilClassifier,
}

__all__ = [
    "BaseClassifier",
    "Detection",
    "BirdClassifier",
    "BatClassifier",
    "InsectClassifier",
    "SoilClassifier",
    "REGISTRY",
]
