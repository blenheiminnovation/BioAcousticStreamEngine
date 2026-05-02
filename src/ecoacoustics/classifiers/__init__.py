"""
Classifier sub-package.

Contains the BaseClassifier contract and concrete implementations for each
organism group. New classifiers can be registered in REGISTRY and activated
via config/settings.yaml without touching the pipeline code.

Author: David Green, Blenheim Palace
"""

from ecoacoustics.classifiers.base import BaseClassifier, Detection
from ecoacoustics.classifiers.bird import BirdClassifier
from ecoacoustics.classifiers.bat import BatClassifier
from ecoacoustics.classifiers.bee import BeeClassifier
from ecoacoustics.classifiers.insect import InsectClassifier
from ecoacoustics.classifiers.soil import SoilClassifier

REGISTRY: dict[str, type[BaseClassifier]] = {
    "bird": BirdClassifier,
    "bat": BatClassifier,
    "bee": BeeClassifier,
    "insect": InsectClassifier,    # stub — grasshoppers, bush crickets (2–20 kHz)
    "soil": SoilClassifier,
}

__all__ = [
    "BaseClassifier",
    "Detection",
    "BirdClassifier",
    "BatClassifier",
    "BeeClassifier",
    "InsectClassifier",
    "SoilClassifier",
    "REGISTRY",
]
