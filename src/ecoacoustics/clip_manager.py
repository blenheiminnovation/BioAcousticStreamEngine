"""
Audio clip library with intelligent per-species retention and disk management.

Every confirmed detection can optionally be saved as a WAV file under
output/clips/<Species>/.  The ClipManager decides whether to save each clip
based on the species' rarity at this site, the detection confidence, and the
available disk space.  It enforces a configurable per-species clip limit by
rotating out the lowest-confidence clip whenever a better one arrives.

Save priority rules:
  1. New species (never detected here before) — always saved, console alert shown.
  2. Locally rare species (fewer than 20 total detections) — saved at min_confidence.
  3. Common species — saved only if confidence ≥ 0.70; limit enforced by rotating
     out the weakest clip when the 100-clip ceiling is reached.
  4. Any species — clip refused if free disk space is below DISK_MIN_FREE_MB.

The species registry (output/known_species.json) persists across restarts so
that "new species" detection works correctly over multiple sessions.

Author: David Green, Blenheim Palace
"""

import json
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from ecoacoustics.classifiers.base import Detection

DISK_MIN_FREE_MB = 200   # refuse to save new clips below this free-space level

_RARE_THRESHOLD = 20     # total detections below this → treat species as locally rare
_HIGH_CONF = 0.70        # common-species clips must beat this confidence to be saved


class ClipManager:
    """Thread-safe manager for the on-disk audio clip library.

    Maintains a JSON species registry and enforces per-species clip limits
    by removing the lowest-confidence file whenever a newer, better clip
    would push the count over the maximum.
    """

    def __init__(
        self,
        clips_dir: str,
        species_db_path: str,
        max_clips_per_species: int = 100,
        min_confidence: float = 0.35,
    ):
        """
        Args:
            clips_dir: Root directory for saved clips (one sub-folder per species).
            species_db_path: Path to the JSON species registry file.
            max_clips_per_species: Hard cap on WAV files kept per species.
            min_confidence: Global minimum confidence — clips below this are never saved.
        """
        self._clips_dir = Path(clips_dir)
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = Path(species_db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_clips = max_clips_per_species
        self._min_conf = min_confidence
        self._lock = threading.Lock()
        self._db: dict = self._load_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self, detection: Detection, audio: np.ndarray, sample_rate: int
    ) -> tuple[Optional[Path], bool]:
        """Record the detection and optionally save the audio clip.

        This is the primary entry point called by the pipeline after each
        detection.  It is fully thread-safe and handles the species registry
        update, save decision, file write, and limit enforcement atomically.

        Args:
            detection: The Detection returned by a classifier.
            audio: The float32 audio array for the chunk that produced this detection.
            sample_rate: Sample rate of audio (Hz).

        Returns:
            (saved_path, is_new_species) where saved_path is the Path of the
            written WAV file, or None if the clip was not saved.
        """
        with self._lock:
            species = detection.label
            is_new = species not in self._db
            self._record_detection(species)

            if not self._should_save(species, detection.confidence, is_new):
                return None, is_new

            path = self._write_clip(audio, sample_rate, species, detection.confidence, detection.timestamp)
            self._enforce_limit(species)
            return path, is_new

    def known_species_count(self) -> int:
        """Return the total number of distinct species ever detected at this site."""
        with self._lock:
            return len(self._db)

    def total_detections(self, species: str) -> int:
        """Return the all-time detection count for a species across all sessions."""
        with self._lock:
            return self._db.get(species, {}).get("total_detections", 0)

    def disk_free_mb(self) -> int:
        """Return free disk space (MB) on the volume holding the clips directory."""
        try:
            return shutil.disk_usage(self._clips_dir).free // (1024 ** 2)
        except OSError:
            return 0

    def emergency_cleanup(self, target_free_mb: int = 500) -> int:
        """Delete lowest-confidence clips across all species until disk is freed.

        Called by the Watchdog when free disk space falls to a critical level.
        Clips are removed in ascending confidence order so the most valuable
        recordings are always retained as long as possible.

        Args:
            target_free_mb: Stop removing files once this many MB are free.

        Returns:
            Number of WAV files removed.
        """
        removed = 0
        all_clips = sorted(self._clips_dir.rglob("*.wav"), key=_conf_from_path)
        for clip in all_clips:
            if self.disk_free_mb() >= target_free_mb:
                break
            clip.unlink(missing_ok=True)
            removed += 1
        return removed

    # ------------------------------------------------------------------
    # Save decision logic
    # ------------------------------------------------------------------

    def _should_save(self, species: str, confidence: float, is_new: bool) -> bool:
        """Return True if this clip should be written to disk."""
        if confidence < self._min_conf:
            return False
        if self.disk_free_mb() < DISK_MIN_FREE_MB:
            return False
        if is_new:
            return True

        total = self._db[species]["total_detections"]
        n_clips = self._clip_count(species)

        if n_clips >= self._max_clips:
            # Only save if this clip beats the worst one already stored
            worst = self._worst_confidence(species)
            return worst is not None and confidence > worst

        if total < _RARE_THRESHOLD:
            return True  # locally rare — preserve every confident detection

        return confidence >= _HIGH_CONF  # common species — quality bar applies

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _write_clip(
        self, audio: np.ndarray, sample_rate: int, species: str,
        confidence: float, timestamp: float,
    ) -> Path:
        """Write a WAV clip to disk and return its path.

        Filename encodes timestamp and confidence so clips can be sorted
        or filtered by confidence without reading the audio data.
        """
        species_dir = self._clips_dir / _safe_dirname(species)
        species_dir.mkdir(exist_ok=True)
        ts = datetime.fromtimestamp(timestamp).strftime("%Y%m%d_%H%M%S")
        conf_pct = int(confidence * 100)
        path = species_dir / f"{ts}_conf{conf_pct:02d}.wav"
        sf.write(str(path), audio, sample_rate)
        return path

    def _enforce_limit(self, species: str) -> None:
        """Remove the lowest-confidence clip(s) until the species is within the cap."""
        species_dir = self._clips_dir / _safe_dirname(species)
        if not species_dir.exists():
            return
        clips = sorted(species_dir.glob("*.wav"))
        while len(clips) > self._max_clips:
            worst = min(clips, key=_conf_from_path)
            worst.unlink(missing_ok=True)
            clips.remove(worst)

    def _clip_count(self, species: str) -> int:
        """Return the number of WAV files currently stored for a species."""
        d = self._clips_dir / _safe_dirname(species)
        return len(list(d.glob("*.wav"))) if d.exists() else 0

    def _worst_confidence(self, species: str) -> Optional[float]:
        """Return the lowest confidence score among stored clips for a species."""
        d = self._clips_dir / _safe_dirname(species)
        if not d.exists():
            return None
        clips = list(d.glob("*.wav"))
        return _conf_from_path(min(clips, key=_conf_from_path)) if clips else None

    # ------------------------------------------------------------------
    # Species registry
    # ------------------------------------------------------------------

    def _record_detection(self, species: str) -> None:
        """Increment the detection counter and persist the registry to disk."""
        today = datetime.now().strftime("%Y-%m-%d")
        if species not in self._db:
            self._db[species] = {"first_seen": today, "total_detections": 0}
        self._db[species]["total_detections"] += 1
        self._db[species]["last_seen"] = today
        self._flush_db()

    def _load_db(self) -> dict:
        """Load the species registry from JSON, returning an empty dict if absent."""
        if self._db_path.exists():
            with open(self._db_path) as f:
                return json.load(f)
        return {}

    def _flush_db(self) -> None:
        """Write the in-memory registry to disk (called after every detection)."""
        with open(self._db_path, "w") as f:
            json.dump(self._db, f, indent=2, sort_keys=True)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _safe_dirname(species: str) -> str:
    """Convert a species common name to a safe directory name."""
    return species.replace(" ", "_").replace("/", "-")


def _conf_from_path(path: Path) -> float:
    """Extract the confidence value encoded in a clip filename.

    Example: 20260429_091432_conf87.wav → 0.87
    Returns 0.0 if the filename does not match the expected format.
    """
    try:
        return int(path.stem.split("_conf")[-1]) / 100.0
    except (ValueError, IndexError):
        return 0.0
