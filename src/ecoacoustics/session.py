from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid

from ecoacoustics.classifiers.base import Detection


@dataclass
class Session:
    """Tracks all detections within a single listening window."""

    window_name: str
    start_time: datetime = field(default_factory=datetime.now)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    end_time: Optional[datetime] = None

    # per-species running counts  {common_name: count}
    _call_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # per-species max confidence
    _max_conf: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    # per-species confidence accumulator for averaging
    _conf_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def record(self, detection: Detection) -> int:
        """Add a detection; returns the call number for this species this session."""
        name = detection.label
        self._call_counts[name] += 1
        self._max_conf[name] = max(self._max_conf[name], detection.confidence)
        self._conf_sum[name] += detection.confidence
        return self._call_counts[name]

    def call_count(self, species: str) -> int:
        return self._call_counts.get(species, 0)

    def species_detected(self) -> set[str]:
        return set(self._call_counts.keys())

    def close(self) -> None:
        self.end_time = datetime.now()

    def duration_seconds(self) -> float:
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    def species_rows(self) -> list[dict]:
        """One summary row per detected species — for the sessions CSV."""
        rows = []
        for name, count in self._call_counts.items():
            avg_conf = self._conf_sum[name] / count if count else 0.0
            rows.append({
                "session_id": self.session_id,
                "window_name": self.window_name,
                "date": self.start_time.strftime("%Y-%m-%d"),
                "session_start": self.start_time.strftime("%H:%M:%S"),
                "session_end": self.end_time.strftime("%H:%M:%S") if self.end_time else "",
                "duration_mins": f"{self.duration_seconds() / 60:.1f}",
                "species": name,
                "total_calls": count,
                "max_confidence": f"{self._max_conf[name]:.3f}",
                "avg_confidence": f"{avg_conf:.3f}",
            })
        return sorted(rows, key=lambda r: -int(r["total_calls"]))
