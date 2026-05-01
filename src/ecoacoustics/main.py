"""
Command-line entry point for the Smart Ecoacoustics monitoring system.

Provides four sub-commands:

  wake        Start listening immediately, either indefinitely or for a
              specified number of minutes.

  schedule    Run the automated dawn/dusk schedule defined in settings.yaml,
              sleeping between windows and adapting future windows based on
              which species have been detected.

  status      Display today's calculated listening windows and a summary of
              all species detected so far today.

  list-devices  Print available audio input devices and their indices so the
                correct device can be set in config/settings.yaml.

Usage examples::

    .venv/bin/python -m ecoacoustics.main wake
    .venv/bin/python -m ecoacoustics.main wake --duration 30
    .venv/bin/python -m ecoacoustics.main schedule
    .venv/bin/python -m ecoacoustics.main status

Author: David Green, Blenheim Palace
"""

import argparse
import os
import sys
import time
import warnings
from datetime import datetime

import yaml
from rich.console import Console
from rich.table import Table

# Suppress noisy TF/pydub startup warnings before any imports trigger them
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
warnings.filterwarnings("ignore", category=UserWarning, module="tensorflow")
warnings.filterwarnings("ignore", category=RuntimeWarning, module="pydub")

_console = Console()


def cmd_wake(args) -> None:
    """Start the pipeline immediately and listen until stopped or time elapses."""
    from ecoacoustics.pipeline import Pipeline

    pipeline = Pipeline(config_path=args.config)
    duration = args.duration * 60.0 if args.duration else None
    try:
        pipeline.run(window_name="manual", duration_seconds=duration)
    finally:
        pipeline.close()


def cmd_schedule(args) -> None:
    """Run the automated schedule: sleep → wake → listen → sleep → repeat.

    Calculates dawn/dusk windows for the current day, waits until the next
    window opens, listens for the window duration, writes the session summary,
    then checks whether the detected species warrant adding any adaptive windows
    before sleeping until the next scheduled window.
    """
    from ecoacoustics.pipeline import Pipeline
    from ecoacoustics.scheduler import Scheduler

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    scheduler = Scheduler.from_config(cfg)
    adaptive_cfg = cfg.get("schedule", {}).get("adaptive", {})
    all_species: set[str] = set()

    _console.print("\n[bold]Ecoacoustics scheduled monitoring[/bold]")
    _console.print(f"Today's windows:\n{scheduler.today_summary()}\n")

    pipeline = Pipeline(config_path=args.config)

    try:
        while True:
            # If already inside a window, listen for the remainder of it
            current = scheduler.current_window()
            if current:
                start, end, name = current
                remaining = (end - datetime.now(start.tzinfo)).total_seconds()
                if remaining > 5:
                    _console.print(
                        f"[green]In window:[/green] [cyan]{name}[/cyan] "
                        f"— {remaining/60:.0f} min remaining"
                    )
                    session = pipeline.run(window_name=name, duration_seconds=remaining)
                    all_species |= session.species_detected()
                    added = scheduler.adapt(all_species, adaptive_cfg)
                    if added:
                        _console.print(f"[yellow]Schedule adapted — new windows: {added}[/yellow]")
                    continue

            # Sleep until the next window opens
            nw = scheduler.next_window()
            if nw is None:
                _console.print("[dim]No upcoming windows found. Exiting.[/dim]")
                break

            nw_start, nw_end, nw_name = nw
            wait_secs = scheduler.seconds_until_next()
            wake_at = nw_start.strftime("%H:%M")
            _console.print(
                f"[dim]Sleeping {wait_secs/60:.0f} min — next window: "
                f"[cyan]{nw_name}[/cyan] at {wake_at}[/dim]"
            )
            _sleep_interruptible(wait_secs)

    except KeyboardInterrupt:
        _console.print("\n[yellow]Schedule stopped.[/yellow]")
    finally:
        pipeline.close()


def cmd_status(args) -> None:
    """Print today's schedule and a summary of today's detections from CSV."""
    import csv
    from pathlib import Path
    from ecoacoustics.scheduler import Scheduler

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    scheduler = Scheduler.from_config(cfg)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _console.print(f"\n[bold]Ecoacoustics status[/bold]  [dim]{now_str}[/dim]")

    _console.print("\n[bold]Today's listening windows:[/bold]")
    current = scheduler.current_window()
    for start, end, name in scheduler.window_times():
        active = " ← [green]ACTIVE NOW[/green]" if (current and current[2] == name) else ""
        _console.print(
            f"  [cyan]{name:<20}[/cyan] {start.strftime('%H:%M')} → {end.strftime('%H:%M')}{active}"
        )

    nw = scheduler.next_window()
    if nw:
        wait = scheduler.seconds_until_next()
        _console.print(
            f"\nNext: [cyan]{nw[2]}[/cyan] at {nw[0].strftime('%H:%M')} "
            f"(in {wait/60:.0f} min)"
        )

    # Read today's entries from sessions.csv and display as a table
    sessions_path = Path(cfg["output"].get("sessions_csv", "output/sessions.csv"))
    if sessions_path.exists():
        today = datetime.now().strftime("%Y-%m-%d")
        rows = []
        with open(sessions_path) as f:
            for row in csv.DictReader(f):
                if row.get("date") == today:
                    rows.append(row)

        if rows:
            _console.print(f"\n[bold]Today's detections ({today}):[/bold]")
            table = Table()
            table.add_column("Species", style="green")
            table.add_column("Window")
            table.add_column("Calls", justify="right")
            table.add_column("Max conf", justify="right")
            for r in rows:
                table.add_row(r["species"], r["window_name"], r["total_calls"], r["max_confidence"])
            _console.print(table)
        else:
            _console.print(f"\n[dim]No detections logged today ({today}).[/dim]")
    else:
        _console.print("\n[dim]No session log found yet — run 'wake' or 'schedule' first.[/dim]")


def _sleep_interruptible(seconds: float, poll: float = 5.0) -> None:
    """Sleep in short bursts so KeyboardInterrupt is handled responsively."""
    remaining = seconds
    while remaining > 0:
        time.sleep(min(poll, remaining))
        remaining -= poll


def cmd_web(args) -> None:
    """Start the FastAPI web UI and open a browser tab."""
    import threading
    import webbrowser
    import uvicorn

    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        def _open():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    _console.print(f"\n[bold green]BioAcoustic Stream Engine (BASE)[/bold green] — web UI at [cyan]{url}[/cyan]\n")
    uvicorn.run("ecoacoustics.api.app:app", host=args.host, port=args.port, reload=False)


def main() -> None:
    """Parse command-line arguments and dispatch to the appropriate command."""
    parser = argparse.ArgumentParser(
        prog="ecoacoustics",
        description="Smart Ecoacoustics — real-time biodiversity monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  ecoacoustics wake                   # listen until Ctrl+C\n"
            "  ecoacoustics wake --duration 30     # listen for 30 minutes\n"
            "  ecoacoustics schedule               # run dawn/dusk schedule\n"
            "  ecoacoustics status                 # show schedule and today's detections\n"
            "  ecoacoustics list-devices           # list microphone devices"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- wake ---
    p_wake = sub.add_parser("wake", help="Start listening now")
    p_wake.add_argument(
        "--duration", type=int, metavar="MINUTES",
        help="Stop after N minutes (default: run until Ctrl+C)",
    )
    p_wake.add_argument("--config", default="config/settings.yaml", metavar="PATH")

    # --- schedule ---
    p_sched = sub.add_parser("schedule", help="Auto wake/sleep on the configured dawn/dusk schedule")
    p_sched.add_argument("--config", default="config/settings.yaml", metavar="PATH")

    # --- status ---
    p_status = sub.add_parser("status", help="Show today's schedule and detection summary")
    p_status.add_argument("--config", default="config/settings.yaml", metavar="PATH")

    # --- list-devices ---
    sub.add_parser("list-devices", help="List available audio input devices")

    # --- web ---
    p_web = sub.add_parser("web", help="Launch the web UI (opens browser automatically)")
    p_web.add_argument("--host", default="0.0.0.0", metavar="HOST")
    p_web.add_argument("--port", type=int, default=8000, metavar="PORT")
    p_web.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")

    args = parser.parse_args()

    if args.command == "wake":
        cmd_wake(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "list-devices":
        from ecoacoustics.audio.capture import AudioCapture
        AudioCapture.list_devices()
    elif args.command == "web":
        cmd_web(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
