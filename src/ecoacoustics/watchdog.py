"""
Background health monitor. Runs every CHECK_INTERVAL seconds and:
  - Warns when queues are backing up (processing can't keep pace)
  - Restarts audio streams that have gone silent unexpectedly
  - Monitors disk space and triggers emergency clip cleanup if critical
  - Prints a periodic status line so the operator knows things are alive
"""

import shutil
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from ecoacoustics.audio.capture import AudioCapture
    from ecoacoustics.clip_manager import ClipManager

_console = Console()

CHECK_INTERVAL = 30       # seconds between health checks
STATUS_INTERVAL = 300     # print a heartbeat line every 5 minutes
STREAM_STALE_SECS = 20    # seconds without a new chunk → assume stream stuck
DISK_WARNING_MB = 500
DISK_CRITICAL_MB = 150


class Watchdog(threading.Thread):
    def __init__(
        self,
        captures: "dict[int, AudioCapture]",
        clip_manager: "ClipManager",
        stop_event: threading.Event,
        clips_dir: str = "output/clips",
    ):
        super().__init__(daemon=True, name="watchdog")
        self._captures = captures
        self._clip_manager = clip_manager
        self._stop = stop_event
        self._clips_dir = Path(clips_dir)

        # per-stream baseline for dropped-chunk delta reporting
        self._last_dropped: dict[int, int] = {sr: 0 for sr in captures}
        self._last_status_time = time.time()

    # ------------------------------------------------------------------
    # Thread entry
    # ------------------------------------------------------------------

    def run(self) -> None:
        while not self._stop.wait(CHECK_INTERVAL):
            try:
                self._check_queues()
                self._check_streams()
                self._check_disk()
                self._maybe_print_status()
            except Exception as exc:
                _console.print(f"[red][watchdog] unexpected error: {exc}[/red]")

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _check_queues(self) -> None:
        for sr, capture in self._captures.items():
            depth = capture.queue_depth
            cap = capture.queue_capacity
            pct = depth / cap if cap else 0

            if pct >= 0.9:
                _console.print(
                    f"[bold red][watchdog] {sr}Hz queue critical "
                    f"({depth}/{cap}) — processing can't keep up[/bold red]"
                )
            elif pct >= 0.6:
                _console.print(
                    f"[yellow][watchdog] {sr}Hz queue filling "
                    f"({depth}/{cap} slots used)[/yellow]"
                )

            new_dropped = capture.dropped_chunks
            delta = new_dropped - self._last_dropped.get(sr, 0)
            if delta > 0:
                _console.print(
                    f"[yellow][watchdog] {sr}Hz stream dropped {delta} chunk(s) "
                    f"(total {new_dropped}) — classifier is slower than real-time[/yellow]"
                )
            self._last_dropped[sr] = new_dropped

    def _check_streams(self) -> None:
        now = time.time()
        for sr, capture in self._captures.items():
            last = capture.last_chunk_time
            if last == 0.0:
                continue  # stream hasn't started yet
            stale = now - last
            if stale > STREAM_STALE_SECS:
                _console.print(
                    f"[yellow][watchdog] {sr}Hz stream silent for {stale:.0f}s "
                    f"— attempting restart[/yellow]"
                )
                try:
                    capture.restart()
                    _console.print(f"[green][watchdog] {sr}Hz stream restarted[/green]")
                except Exception as exc:
                    _console.print(f"[red][watchdog] {sr}Hz restart failed: {exc}[/red]")

    def _check_disk(self) -> None:
        if not self._clips_dir.exists():
            return
        try:
            usage = shutil.disk_usage(self._clips_dir)
        except OSError:
            return
        free_mb = usage.free // (1024 ** 2)

        if free_mb < DISK_CRITICAL_MB:
            _console.print(
                f"[bold red][watchdog] CRITICAL: only {free_mb}MB free — "
                f"running emergency clip cleanup[/bold red]"
            )
            removed = self._clip_manager.emergency_cleanup(target_free_mb=DISK_WARNING_MB)
            _console.print(f"[yellow][watchdog] emergency cleanup removed {removed} clip(s)[/yellow]")
        elif free_mb < DISK_WARNING_MB:
            _console.print(f"[yellow][watchdog] low disk space: {free_mb}MB free[/yellow]")

    def _maybe_print_status(self) -> None:
        now = time.time()
        if now - self._last_status_time < STATUS_INTERVAL:
            return
        self._last_status_time = now

        parts = []
        for sr, capture in self._captures.items():
            parts.append(f"{sr}Hz q={capture.queue_depth}/{capture.queue_capacity}")
        if self._clips_dir.exists():
            try:
                free_mb = shutil.disk_usage(self._clips_dir).free // (1024 ** 2)
                parts.append(f"disk={free_mb}MB free")
            except OSError:
                pass
        species = self._clip_manager.known_species_count()
        parts.append(f"species_seen={species}")
        _console.print(f"[dim][watchdog] {' | '.join(parts)}[/dim]")
