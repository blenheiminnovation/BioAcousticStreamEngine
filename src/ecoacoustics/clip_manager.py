"""
Manages on-disk audio clip storage with per-species limits and priority rules.

Save priority:
  1. New species (never seen before)  — always save, flag to console
  2. Rare locally (< 20 total detections) — save if conf >= min_confidence
  3. Common species — save if conf >= high_conf_threshold; rotate out weakest
     clips when the 100-clip limit is reached
"""

import json
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

DISK_MIN_FREE_MB = 200   # refuse to save new clips below this free-space level

from ecoacoustics.classifiers.base import Detection

_RARE_THRESHOLD = 20      # fewer total detections → treat as locally rare
_HIGH_CONF = 0.70         # common-species clips must beat this to be saved


class ClipManager:
    def __init__(
        self,
        clips_dir: str,
        species_db_path: str,
        max_clips_per_species: int = 100,
        min_confidence: float = 0.35,
    ):
        self._clips_dir = Path(clips_dir)
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = Path(species_db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_clips = max_clips_per_species
        self._min_conf = min_confidence
        self._lock = threading.Lock()
        self._db: dict = self._load_db()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def process(
        self, detection: Detection, audio: np.ndarray, sample_rate: int
    ) -> tuple[Optional[Path], bool]:
        """
        Record the detection and optionally save the audio clip.
        Returns (saved_path_or_None, is_new_species).
        Thread-safe.
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
        with self._lock:
            return len(self._db)

    def total_detections(self, species: str) -> int:
        with self._lock:
            return self._db.get(species, {}).get("total_detections", 0)

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def disk_free_mb(self) -> int:
        try:
            return shutil.disk_usage(self._clips_dir).free // (1024 ** 2)
        except OSError:
            return 0

    def emergency_cleanup(self, target_free_mb: int = 500) -> int:
        """
        Delete lowest-confidence clips across all species until target_free_mb
        is free, or until no more clips remain. Returns number of files removed.
        """
        removed = 0
        all_clips = sorted(self._clips_dir.rglob("*.wav"), key=_conf_from_path)
        for clip in all_clips:
            if self.disk_free_mb() >= target_free_mb:
                break
            clip.unlink(missing_ok=True)
            removed += 1
        return removed

    def _should_save(self, species: str, confidence: float, is_new: bool) -> bool:
        if confidence < self._min_conf:
            return False
        if self.disk_free_mb() < DISK_MIN_FREE_MB:
            return False
        if is_new:
            return True

        total = self._db[species]["total_detections"]
        n_clips = self._clip_count(species)

        if n_clips >= self._max_clips:
            # only save if it beats the weakest clip already stored
            worst = self._worst_confidence(species)
            return worst is not None and confidence > worst

        if total < _RARE_THRESHOLD:
            return True  # locally rare — always keep

        return confidence >= _HIGH_CONF  # common — quality bar

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _write_clip(
        self, audio: np.ndarray, sample_rate: int, species: str,
        confidence: float, timestamp: float,
    ) -> Path:
        species_dir = self._clips_dir / _safe_dirname(species)
        species_dir.mkdir(exist_ok=True)
        ts = datetime.fromtimestamp(timestamp).strftime("%Y%m%d_%H%M%S")
        conf_pct = int(confidence * 100)
        path = species_dir / f"{ts}_conf{conf_pct:02d}.wav"
        sf.write(str(path), audio, sample_rate)
        return path

    def _enforce_limit(self, species: str) -> None:
        species_dir = self._clips_dir / _safe_dirname(species)
        if not species_dir.exists():
            return
        clips = sorted(species_dir.glob("*.wav"))
        while len(clips) > self._max_clips:
            worst = min(clips, key=_conf_from_path)
            worst.unlink(missing_ok=True)
            clips.remove(worst)

    def _clip_count(self, species: str) -> int:
        d = self._clips_dir / _safe_dirname(species)
        return len(list(d.glob("*.wav"))) if d.exists() else 0

    def _worst_confidence(self, species: str) -> Optional[float]:
        d = self._clips_dir / _safe_dirname(species)
        if not d.exists():
            return None
        clips = list(d.glob("*.wav"))
        return _conf_from_path(min(clips, key=_conf_from_path)) if clips else None

    # ------------------------------------------------------------------
    # Species database
    # ------------------------------------------------------------------

    def _record_detection(self, species: str) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if species not in self._db:
            self._db[species] = {"first_seen": today, "total_detections": 0}
        self._db[species]["total_detections"] += 1
        self._db[species]["last_seen"] = today
        self._flush_db()

    def _load_db(self) -> dict:
        if self._db_path.exists():
            with open(self._db_path) as f:
                return json.load(f)
        return {}

    def _flush_db(self) -> None:
        with open(self._db_path, "w") as f:
            json.dump(self._db, f, indent=2, sort_keys=True)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _safe_dirname(species: str) -> str:
    return species.replace(" ", "_").replace("/", "-")


def _conf_from_path(path: Path) -> float:
    """Extract confidence from e.g. 20260429_091432_conf87.wav → 0.87"""
    try:
        return int(path.stem.split("_conf")[-1]) / 100.0
    except (ValueError, IndexError):
        return 0.0
