"""
Bat species classifier using BatDetect2.

BatDetect2 is a PyTorch deep-learning model developed by Oisin Mac Aodha
et al. (University of Edinburgh / Caltech) trained on 17 UK and European bat
species.  It analyses audio spectrograms in the 10–120 kHz ultrasonic band
and returns individual call detections with species probabilities.

Supported species (17 UK/European):
    Barbastellus barbastellus  — Barbastelle
    Eptesicus serotinus        — Serotine
    Myotis alcathoe            — Alcathoe Bat
    Myotis bechsteinii         — Bechstein's Bat
    Myotis brandtii            — Brandt's Bat
    Myotis daubentonii         — Daubenton's Bat
    Myotis mystacinus          — Whiskered Bat
    Myotis nattereri           — Natterer's Bat
    Nyctalus leisleri          — Leisler's Bat
    Nyctalus noctula           — Noctule
    Pipistrellus nathusii      — Nathusius' Pipistrelle
    Pipistrellus pipistrellus  — Common Pipistrelle
    Pipistrellus pygmaeus      — Soprano Pipistrelle
    Plecotus auritus           — Brown Long-eared Bat
    Plecotus austriacus        — Grey Long-eared Bat
    Rhinolophus ferrumequinum  — Greater Horseshoe Bat
    Rhinolophus hipposideros   — Lesser Horseshoe Bat

Hardware requirement:
    Bat echolocation calls range from ~15 kHz to ~120 kHz, far above the
    20 kHz ceiling of a standard microphone.  An ultrasonic detector is
    essential, for example:
        - Dodotronic Ultramic 384K (USB, 192 kHz)
        - Pettersson M500-384 (USB, 384 kHz)
        - AudioMoth with ultrasonic firmware (up to 384 kHz)
    Set audio.device in config/settings.yaml to the device index and
    bat.capture_rate to match your hardware's maximum sample rate.

Efficiency notes:
    - The BatDetect2 PyTorch model is loaded once and reused across chunks.
    - The temp WAV file is written to /dev/shm (RAM disk) — zero disk I/O.
    - RMS energy pre-filter skips inference on silent chunks.
    - Detections are filtered by both det_prob (call presence) and
      class_prob (species identity) thresholds independently.

Reference:
    Mac Aodha et al. (2022) — "Towards a General Approach for Bat
    Echolocation Detection and Classification", bioRxiv 2022.12.14.520490

Author: David Green, Blenheim Palace
"""

import os
import warnings
from typing import Any, Optional

import numpy as np
import soundfile as sf

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection

# Prefer RAM disk to avoid physical I/O; fall back to /tmp if unavailable
_TMP_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None

# Mapping from BatDetect2 scientific names to common names
_COMMON_NAMES: dict[str, str] = {
    "Barbastellus barbastellus": "Barbastelle",
    "Eptesicus serotinus": "Serotine",
    "Myotis alcathoe": "Alcathoe Bat",
    "Myotis bechsteinii": "Bechstein's Bat",
    "Myotis brandtii": "Brandt's Bat",
    "Myotis daubentonii": "Daubenton's Bat",
    "Myotis mystacinus": "Whiskered Bat",
    "Myotis nattereri": "Natterer's Bat",
    "Nyctalus leisleri": "Leisler's Bat",
    "Nyctalus noctula": "Noctule",
    "Pipistrellus nathusii": "Nathusius' Pipistrelle",
    "Pipistrellus pipistrellus": "Common Pipistrelle",
    "Pipistrellus pygmaeus": "Soprano Pipistrelle",
    "Plecotus auritus": "Brown Long-eared Bat",
    "Plecotus austriacus": "Grey Long-eared Bat",
    "Rhinolophus ferrumequinum": "Greater Horseshoe Bat",
    "Rhinolophus hipposideros": "Lesser Horseshoe Bat",
}


class BatClassifier(BaseClassifier):
    """Identifies bat species from ultrasonic audio using BatDetect2.

    Processes 3-second audio chunks at 256 kHz.  Each chunk may yield
    multiple call-level detections (bats often emit several pulses per
    second).  The detections are grouped by species and the highest-
    confidence call per species per chunk is returned to avoid flooding
    the log with hundreds of individual pulse events.

    Both a detection threshold (call presence) and a classification
    threshold (species identity) can be tuned independently in settings.yaml.
    """

    name = "bat"

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: Section from settings.yaml under the 'bat' key.
                capture_rate: Sample rate to request from the audio device (Hz).
                    Default 256000; set to 192000 for 192 kHz hardware.
                min_det_confidence: Minimum det_prob to report a call (default 0.5).
                min_class_confidence: Minimum class_prob for species ID (default 0.4).
                silence_threshold: RMS below this skips inference (default 0.0001).
        """
        self._capture_rate: int = config.get("capture_rate", 256000)
        self._min_det_conf: float = config.get("min_det_confidence", 0.5)
        self._min_class_conf: float = config.get("min_class_confidence", 0.4)
        self._silence_threshold: float = config.get("silence_threshold", 0.0001)
        self._model = None
        self._bd2_config: Optional[dict] = None
        self._tmp_path: Optional[str] = None

    @property
    def sample_rate(self) -> int:
        """Capture sample rate — set to match your ultrasonic microphone."""
        return self._capture_rate

    @property
    def freq_min_hz(self) -> int:
        """Lower edge of the ultrasonic bandpass filter."""
        return 10_000

    @property
    def freq_max_hz(self) -> int:
        """Upper edge of the ultrasonic bandpass filter (model ceiling is 120 kHz)."""
        return 120_000

    def load(self) -> None:
        """Load the BatDetect2 PyTorch model and prepare the processing config.

        The model weights (~50 MB) are bundled with the batdetect2 package and
        loaded once here.  Subsequent calls to classify() reuse the loaded model
        without any disk access.
        """
        from batdetect2 import api
        from rich.console import Console

        Console().print("[dim]Loading BatDetect2 model...[/dim]", end="")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._model, _ = api.load_model()

        # Build a processing config once — override only the fields we care about
        self._bd2_config = api.get_config()
        self._bd2_config["detection_threshold"] = self._min_det_conf
        self._bd2_config["quiet"] = True

        # Pre-import api for classify() — avoids re-import overhead per chunk
        self._api = api

        Console().print("[dim] done[/dim]")

        # Allocate one reusable temp file on RAM disk for the lifetime of the session
        if _TMP_DIR:
            self._tmp_path = os.path.join(_TMP_DIR, f"ecoacoustics_bat_{os.getpid()}.wav")
        else:
            import tempfile
            self._tmp_path = os.path.join(
                tempfile.gettempdir(), f"ecoacoustics_bat_{os.getpid()}.wav"
            )

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Run BatDetect2 inference on one 3-second ultrasonic audio chunk.

        Applies an energy pre-filter to skip silent chunks, writes the audio
        to the RAM-disk temp file, runs the model, then returns the best-
        confidence detection per species (to avoid duplicate entries for
        species that called multiple times in the same chunk).

        Args:
            chunk: Pre-processed audio at capture_rate Hz, bandpass 10–120 kHz.

        Returns:
            List of Detection objects, one per species detected in the chunk.
        """
        if self._model is None:
            raise RuntimeError("Call load() before classify()")

        # Fast path: skip inference on silent audio
        if np.sqrt(np.mean(chunk.data ** 2)) < self._silence_threshold:
            return []

        # Write to RAM disk (reusing same file path each call)
        sf.write(self._tmp_path, chunk.data, chunk.sample_rate, subtype="PCM_16")

        # Load at 256 kHz — BatDetect2's internal rate; resamples if needed
        audio = self._api.load_audio(self._tmp_path, target_samp_rate=256000)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw_detections, _, _ = self._api.process_audio(
                audio,
                samp_rate=256000,
                model=self._model,
                config=self._bd2_config,
            )

        # Filter by both thresholds and keep best-confidence call per species
        best: dict[str, Detection] = {}
        for d in raw_detections:
            if d["det_prob"] < self._min_det_conf:
                continue
            if d["class_prob"] < self._min_class_conf:
                continue

            scientific = d["class"]
            common = _COMMON_NAMES.get(scientific, scientific)

            # Use combined score (geometric mean) to rank calls for same species
            combined = (d["det_prob"] * d["class_prob"]) ** 0.5

            if scientific not in best or combined > best[scientific].confidence:
                best[scientific] = Detection(
                    label=common,
                    confidence=round(combined, 4),
                    classifier=self.name,
                    timestamp=chunk.timestamp,
                    metadata={
                        "scientific_name": scientific,
                        "det_prob": round(d["det_prob"], 4),
                        "class_prob": round(d["class_prob"], 4),
                        "low_freq_hz": d["low_freq"],
                        "high_freq_hz": d["high_freq"],
                        "start_time": d["start_time"],
                        "end_time": d["end_time"],
                    },
                )

        return list(best.values())

    def cleanup(self) -> None:
        """Delete the reusable RAM-disk temp file on session shutdown."""
        if self._tmp_path and os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)
