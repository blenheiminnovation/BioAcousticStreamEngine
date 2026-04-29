"""
Session tracking — per-species call counts and confidence statistics.

A Session is created at the start of each listening window and closed when
the window ends.  It accumulates every Detection produced during that window,
maintaining running counts and confidence statistics per species.  These
are used by the logger to write the sessions.csv summary and to print the
end-of-session table to the terminal.

Author: David Green, Blenheim Palace
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid

from ecoacoustics.classifiers.base import Detection


@dataclass
class Session:
    """Tracks all detections within a single listening window.

    Attributes:
        window_name: Name of the schedule window (e.g. 'dawn_chorus', 'manual').
        start_time: When the session began.
        session_id: Short unique hex ID used to link detections.csv rows.
        end_time: Set by close(); None while the session is still active.
    """

    window_name: str
    start_time: datetime = field(default_factory=datetime.now)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    end_time: Optional[datetime] = None

    # Running per-species accumulators (keyed by common name)
    _call_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _max_conf: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    _conf_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def record(self, detection: Detection) -> int:
        """Register a detection and return its call number for this species.

        Args:
            detection: A Detection produced by any classifier.

        Returns:
            1-based count of how many times this species has been detected
            in this session (e.g. 3 means this is the third call of this
            species during the current window).
        """
        name = detection.label
        self._call_counts[name] += 1
        self._max_conf[name] = max(self._max_conf[name], detection.confidence)
        self._conf_sum[name] += detection.confidence
        return self._call_counts[name]

    def call_count(self, species: str) -> int:
        """Return the number of times species has been detected this session."""
        return self._call_counts.get(species, 0)

    def species_detected(self) -> set[str]:
        """Return the set of all species common names detected this session."""
        return set(self._call_counts.keys())

    def close(self) -> None:
        """Mark the session as finished by recording the end time."""
        self.end_time = datetime.now()

    def duration_seconds(self) -> float:
        """Elapsed session time in seconds; uses now() if not yet closed."""
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    def species_rows(self) -> list[dict]:
        """Return one summary dict per detected species, sorted by call count.

        Each dict contains the fields required by the sessions CSV writer:
        session_id, window_name, date, session_start/end, duration_mins,
        species, total_calls, max_confidence, avg_confidence.
        """
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
