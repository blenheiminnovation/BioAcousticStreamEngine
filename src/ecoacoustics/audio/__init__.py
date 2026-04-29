"""
Audio capture and preprocessing sub-package.

Provides AudioCapture for microphone streaming and AudioProcessor for
resampling and bandpass filtering raw audio before classification.

Author: David Green, Blenheim Palace
"""

from ecoacoustics.audio.capture import AudioCapture
from ecoacoustics.audio.processor import AudioProcessor

__all__ = ["AudioCapture", "AudioProcessor"]
