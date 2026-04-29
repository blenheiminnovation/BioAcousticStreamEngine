"""
Smart Ecoacoustics — real-time acoustic biodiversity monitoring.

Streams live microphone audio through AI classifiers to identify birds,
bats, insects, and soil organisms. Designed for continuous field deployment
at Blenheim Palace estate.

Author: David Green, Blenheim Palace
"""

from ecoacoustics.pipeline import Pipeline

__all__ = ["Pipeline"]
