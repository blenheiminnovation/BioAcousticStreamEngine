"""
Detection logging — console output and CSV file writing.

DetectionLogger handles two output streams:

  detections.csv — one row per individual detection, written immediately
      as each detection arrives so data is never lost if the process exits.

  sessions.csv — one summary row per species per listening session, written
      at the end of each window with aggregate call counts and confidence stats.

The console output is colour-coded by organism group and shows species name,
scientific name, confidence, and the call number within the current session.

Author: David Green, Blenheim Palace
"""

import csv
import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console

from ecoacoustics.classifiers.base import Detection
from ecoacoustics.session import Session

_console = Console()

_CLASSIFIER_COLOURS = {
    "bird": "green",
    "bat": "magenta",
    "insect": "yellow",
    "soil": "cyan",
}

_DETECTION_FIELDS = [
    "session_id", "window_name", "date", "time",
    "classifier", "species_common", "species_scientific",
    "confidence", "call_number_in_session", "latitude", "longitude",
]

_SESSION_FIELDS = [
    "session_id", "window_name", "date", "session_start", "session_end",
    "duration_mins", "species", "total_calls", "max_confidence", "avg_confidence",
]


class DetectionLogger:
    """Writes detections to the terminal and to CSV log files.

    CSV files are opened in append mode so that data accumulates across
    multiple sessions and restarts without overwriting previous records.
    Both files are flushed immediately after every write so a crash or
    power loss will not result in lost data.
    """

    def __init__(
        self,
        console: bool = True,
        detections_csv: Optional[str] = None,
        sessions_csv: Optional[str] = None,
        min_confidence: float = 0.0,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ):
        """
        Args:
            console: If True, print detections to the terminal in real time.
            detections_csv: Path to the per-detection CSV; None disables file logging.
            sessions_csv: Path to the per-session summary CSV; None disables it.
            min_confidence: Detections below this score are not logged anywhere.
            latitude: Recording latitude written to every detection row.
            longitude: Recording longitude written to every detection row.
        """
        self._console = console
        self._min_confidence = min_confidence
        self._lat = latitude
        self._lon = longitude

        self._det_writer, self._det_file = self._open_csv(detections_csv, _DETECTION_FIELDS)
        self._sess_writer, self._sess_file = self._open_csv(sessions_csv, _SESSION_FIELDS)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def log(self, detections: list[Detection], session: Session) -> None:
        """Log a batch of detections from a single audio chunk.

        Filters by min_confidence, records each detection in the session,
        writes a row to detections.csv, and prints a console line.

        Args:
            detections: Detections returned by a classifier for one chunk.
            session: The active Session object (used for call numbering).
        """
        for det in detections:
            if det.confidence < self._min_confidence:
                continue
            call_n = session.record(det)
            self._write_detection_row(det, session, call_n)
            self._write_console(det, call_n)

    def write_session_summary(self, session: Session) -> None:
        """Append per-species summary rows to sessions.csv and print the table.

        Called once at the end of each listening window.
        """
        if not self._sess_writer:
            return
        for row in session.species_rows():
            self._sess_writer.writerow(row)
        self._sess_file.flush()
        if self._console:
            self._print_session_summary(session)

    def close(self) -> None:
        """Flush and close both CSV files."""
        for f in (self._det_file, self._sess_file):
            if f:
                f.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_detection_row(self, det: Detection, session: Session, call_n: int) -> None:
        """Write one row to detections.csv and flush immediately."""
        if not self._det_writer:
            return
        ts = datetime.datetime.fromtimestamp(det.timestamp)
        self._det_writer.writerow({
            "session_id": session.session_id,
            "window_name": session.window_name,
            "date": ts.strftime("%Y-%m-%d"),
            "time": ts.strftime("%H:%M:%S"),
            "classifier": det.classifier,
            "species_common": det.label,
            "species_scientific": det.metadata.get("scientific_name", ""),
            "confidence": f"{det.confidence:.3f}",
            "call_number_in_session": call_n,
            "latitude": self._lat or "",
            "longitude": self._lon or "",
        })
        self._det_file.flush()

    def _write_console(self, det: Detection, call_n: int) -> None:
        """Print a colour-coded detection line to the terminal."""
        if not self._console:
            return
        colour = _CLASSIFIER_COLOURS.get(det.classifier, "white")
        ts = datetime.datetime.fromtimestamp(det.timestamp).strftime("%H:%M:%S")
        sci = det.metadata.get("scientific_name", "")
        _console.print(
            f"[dim]{ts}[/dim]  [{colour}]{det.label:<30}[/{colour}]"
            f"[dim]{sci:<35}[/dim]"
            f"conf [bold]{det.confidence:.0%}[/bold]  "
            f"call #{call_n}"
        )

    def _print_session_summary(self, session: Session) -> None:
        """Print a rich table summarising detections at the end of a session."""
        from rich.table import Table
        rows = session.species_rows()
        if not rows:
            _console.print("[dim]No detections this session.[/dim]")
            return
        table = Table(title=f"Session {session.session_id} — {session.window_name} summary")
        table.add_column("Species", style="green")
        table.add_column("Calls", justify="right")
        table.add_column("Max conf", justify="right")
        table.add_column("Avg conf", justify="right")
        for r in rows:
            table.add_row(r["species"], str(r["total_calls"]), r["max_confidence"], r["avg_confidence"])
        _console.print(table)

    @staticmethod
    def _open_csv(path_str: Optional[str], fields: list[str]):
        """Open (or create) a CSV file in append mode, writing the header if new.

        Returns (DictWriter, file_handle) or (None, None) if path_str is None.
        """
        if not path_str:
            return None, None
        p = Path(path_str)
        p.parent.mkdir(parents=True, exist_ok=True)
        write_header = not p.exists() or p.stat().st_size == 0
        f = open(p, "a", newline="")
        writer = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            writer.writeheader()
        return writer, f
