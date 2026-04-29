import csv
import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from ecoacoustics.classifiers.base import Detection

_console = Console()

_CLASSIFIER_COLOURS = {
    "bird": "green",
    "bat": "magenta",
    "insect": "yellow",
    "soil": "cyan",
}


class DetectionLogger:
    def __init__(
        self,
        console: bool = True,
        log_file: Optional[str] = None,
        min_confidence: float = 0.0,
    ):
        self._console = console
        self._min_confidence = min_confidence
        self._csv_path = Path(log_file) if log_file else None
        self._csv_file = None
        self._csv_writer = None

        if self._csv_path:
            self._csv_path.parent.mkdir(parents=True, exist_ok=True)
            self._csv_file = open(self._csv_path, "a", newline="")
            self._csv_writer = csv.writer(self._csv_file)
            if self._csv_path.stat().st_size == 0:
                self._csv_writer.writerow(
                    ["timestamp", "classifier", "label", "confidence", "metadata"]
                )

    def log(self, detections: list[Detection]) -> None:
        for det in detections:
            if det.confidence < self._min_confidence:
                continue
            self._write_console(det)
            self._write_csv(det)

    def close(self) -> None:
        if self._csv_file:
            self._csv_file.close()

    # ------------------------------------------------------------------

    def _write_console(self, det: Detection) -> None:
        if not self._console:
            return
        colour = _CLASSIFIER_COLOURS.get(det.classifier, "white")
        ts = datetime.datetime.fromtimestamp(det.timestamp).strftime("%H:%M:%S")
        _console.print(
            f"[dim]{ts}[/dim]  [{colour}]{det.classifier:8}[/{colour}]  "
            f"[bold]{det.label}[/bold]  [dim]{det.confidence:.0%}[/dim]"
        )

    def _write_csv(self, det: Detection) -> None:
        if not self._csv_writer:
            return
        self._csv_writer.writerow(
            [
                datetime.datetime.fromtimestamp(det.timestamp).isoformat(),
                det.classifier,
                det.label,
                f"{det.confidence:.4f}",
                str(det.metadata),
            ]
        )
        self._csv_file.flush()
