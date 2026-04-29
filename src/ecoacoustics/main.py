import argparse
import os
import sys
import time
import warnings
from datetime import datetime

# Suppress noisy TF/pydub startup warnings before any imports trigger them
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
warnings.filterwarnings("ignore", category=UserWarning, module="tensorflow")
warnings.filterwarnings("ignore", category=RuntimeWarning, module="pydub")

import yaml
from rich.console import Console
from rich.table import Table

_console = Console()


def cmd_wake(args) -> None:
    from ecoacoustics.pipeline import Pipeline

    pipeline = Pipeline(config_path=args.config)
    duration = args.duration * 60.0 if args.duration else None
    try:
        pipeline.run(window_name="manual", duration_seconds=duration)
    finally:
        pipeline.close()


def cmd_schedule(args) -> None:
    """Run automated schedule: sleep → wake → listen → sleep → ..."""
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
            # If we're currently inside a window, listen for the remainder
            current = scheduler.current_window()
            if current:
                start, end, name = current
                remaining = (end - datetime.now(start.tzinfo)).total_seconds()
                if remaining > 5:
                    _console.print(f"[green]In window:[/green] [cyan]{name}[/cyan] — {remaining/60:.0f} min remaining")
                    session = pipeline.run(window_name=name, duration_seconds=remaining)
                    all_species |= session.species_detected()
                    added = scheduler.adapt(all_species, adaptive_cfg)
                    if added:
                        _console.print(f"[yellow]Schedule adapted — new windows: {added}[/yellow]")
                    continue

            # Sleep until next window
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
    import csv
    from pathlib import Path
    from ecoacoustics.scheduler import Scheduler

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    scheduler = Scheduler.from_config(cfg)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _console.print(f"\n[bold]Ecoacoustics status[/bold]  [dim]{now_str}[/dim]")

    # Schedule
    _console.print("\n[bold]Today's listening windows:[/bold]")
    current = scheduler.current_window()
    for start, end, name in scheduler.window_times():
        active = " ← [green]ACTIVE NOW[/green]" if (current and current[2] == name) else ""
        _console.print(f"  [cyan]{name:<20}[/cyan] {start.strftime('%H:%M')} → {end.strftime('%H:%M')}{active}")

    nw = scheduler.next_window()
    if nw:
        wait = scheduler.seconds_until_next()
        _console.print(f"\nNext: [cyan]{nw[2]}[/cyan] at {nw[0].strftime('%H:%M')} "
                       f"(in {wait/60:.0f} min)")

    # Today's detections from CSV
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
        _console.print("\n[dim]No session log found yet.[/dim]")


def _sleep_interruptible(seconds: float, poll: float = 5.0) -> None:
    """Sleep in short bursts so KeyboardInterrupt is responsive."""
    remaining = seconds
    while remaining > 0:
        time.sleep(min(poll, remaining))
        remaining -= poll


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ecoacoustics",
        description="Real-time ecoacoustic monitoring",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- wake ---
    p_wake = sub.add_parser("wake", help="Start listening now")
    p_wake.add_argument(
        "--duration", type=int, metavar="MINUTES",
        help="Listen for N minutes then stop (default: until Ctrl+C)",
    )
    p_wake.add_argument("--config", default="config/settings.yaml")

    # --- schedule ---
    p_sched = sub.add_parser("schedule", help="Auto wake/sleep based on dawn & dusk windows")
    p_sched.add_argument("--config", default="config/settings.yaml")

    # --- status ---
    p_status = sub.add_parser("status", help="Show today's schedule and detection summary")
    p_status.add_argument("--config", default="config/settings.yaml")

    # --- list-devices ---
    sub.add_parser("list-devices", help="List available audio input devices")

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
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
