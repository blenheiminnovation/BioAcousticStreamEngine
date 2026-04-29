"""
Listening schedule — calculates dawn, dusk, and custom windows from
sunrise/sunset times at the monitoring location.

Windows are defined relative to a solar anchor (sunrise, sunset, noon)
plus an offset in minutes, making the schedule automatically shift with
the seasons without manual adjustment.  An adaptive layer adds extra
windows when trigger species are detected (e.g. a night window if an owl
is identified during a standard session).

Author: David Green, Blenheim Palace
"""

import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from astral import LocationInfo
from astral.sun import sun


@dataclass
class ListeningWindow:
    """Defines a single scheduled listening period.

    Attributes:
        name: Human-readable label (e.g. 'dawn_chorus', 'dusk').
        anchor: Solar reference point — 'sunrise', 'sunset', 'noon', or 'fixed'.
        offset_mins: Minutes before (negative) or after (positive) the anchor.
        duration_mins: How long to listen once the window opens.
        fixed_time: 'HH:MM' clock time used when anchor == 'fixed'.
    """

    name: str
    anchor: str
    offset_mins: int
    duration_mins: int
    fixed_time: Optional[str] = None


class Scheduler:
    """Calculates listening window start/end times for any given date.

    Uses the astral library to compute accurate sunrise and sunset times for
    the configured latitude/longitude.  The schedule shifts automatically
    with the seasons.

    Adaptive windows are appended at runtime when trigger species are first
    detected — for example, detecting a Tawny Owl causes a 23:00 night window
    to be added for subsequent nights of the same run.
    """

    def __init__(self, lat: float, lon: float, timezone: str, windows: list[ListeningWindow]):
        """
        Args:
            lat: Decimal latitude of the monitoring site (positive = north).
            lon: Decimal longitude of the monitoring site (positive = east).
            timezone: IANA timezone string, e.g. 'Europe/London'.
            windows: List of ListeningWindow definitions from configuration.
        """
        self._location = LocationInfo(
            name="Monitor", region="", timezone=timezone,
            latitude=lat, longitude=lon,
        )
        self._tz = zoneinfo.ZoneInfo(timezone)
        self._base_windows: list[ListeningWindow] = windows
        self._extra_windows: list[ListeningWindow] = []

    # ------------------------------------------------------------------
    # Core schedule
    # ------------------------------------------------------------------

    def window_times(self, for_date: Optional[date] = None) -> list[tuple[datetime, datetime, str]]:
        """Return all (start, end, name) tuples for a given date, sorted by start.

        Args:
            for_date: The calendar date to compute windows for; defaults to today.

        Returns:
            Sorted list of (start_datetime, end_datetime, window_name) tuples.
        """
        d = for_date or date.today()
        s = sun(self._location.observer, date=d, tzinfo=self._tz)
        anchors = {
            "sunrise": s["sunrise"],
            "sunset": s["sunset"],
            "noon": s["noon"],
        }

        results = []
        for w in self._base_windows + self._extra_windows:
            if w.anchor == "fixed":
                h, m = map(int, (w.fixed_time or "00:00").split(":"))
                anchor_dt = datetime(d.year, d.month, d.day, h, m, tzinfo=self._tz)
            else:
                anchor_dt = anchors.get(w.anchor)
                if anchor_dt is None:
                    continue

            start = anchor_dt + timedelta(minutes=w.offset_mins)
            end = start + timedelta(minutes=w.duration_mins)
            results.append((start, end, w.name))

        return sorted(results, key=lambda x: x[0])

    def current_window(self) -> Optional[tuple[datetime, datetime, str]]:
        """Return the active window if the current time falls inside one, else None."""
        now = datetime.now(self._tz)
        for start, end, name in self.window_times():
            if start <= now < end:
                return (start, end, name)
        return None

    def next_window(self) -> Optional[tuple[datetime, datetime, str]]:
        """Return the next upcoming window, wrapping to tomorrow if needed."""
        now = datetime.now(self._tz)
        for start, end, name in self.window_times():
            if start > now:
                return (start, end, name)
        # No more windows today — return the first window tomorrow
        for start, end, name in self.window_times(date.today() + timedelta(days=1)):
            return (start, end, name)
        return None

    def seconds_until_next(self) -> float:
        """Seconds until the next window opens; 3600 if no windows are scheduled."""
        nw = self.next_window()
        if nw is None:
            return 3600.0
        return max(0.0, (nw[0] - datetime.now(self._tz)).total_seconds())

    def today_summary(self) -> str:
        """Return a formatted multi-line string of today's windows and their times."""
        lines = []
        for start, end, name in self.window_times():
            lines.append(f"  {name:<20} {start.strftime('%H:%M')} → {end.strftime('%H:%M')}")
        return "\n".join(lines) if lines else "  (no windows configured)"

    # ------------------------------------------------------------------
    # Adaptive scheduling
    # ------------------------------------------------------------------

    def adapt(self, species_detected: set[str], adaptive_cfg: dict) -> list[str]:
        """Add extra listening windows triggered by newly detected species.

        Checks the detected species set against the adaptive configuration from
        settings.yaml.  Nocturnal trigger species (owls, nightjars) add a night
        window; early-morning trigger species (Nightingale, Song Thrush) add a
        pre-dawn window.  Each extra window is only added once.

        Args:
            species_detected: All species common names seen so far this run.
            adaptive_cfg: The 'adaptive' dict from the schedule config section.

        Returns:
            List of newly added window names (empty if nothing changed).
        """
        added = []
        existing_names = {w.name for w in self._extra_windows}

        nocturnal = set(adaptive_cfg.get("nocturnal", []))
        if species_detected & nocturnal and "night" not in existing_names:
            self._extra_windows.append(ListeningWindow(
                name="night",
                anchor="fixed",
                offset_mins=0,
                duration_mins=60,
                fixed_time="23:00",
            ))
            added.append("night")

        early = set(adaptive_cfg.get("early_morning", []))
        if species_detected & early and "pre_dawn" not in existing_names:
            self._extra_windows.append(ListeningWindow(
                name="pre_dawn",
                anchor="sunrise",
                offset_mins=-60,
                duration_mins=30,
            ))
            added.append("pre_dawn")

        return added

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict) -> "Scheduler":
        """Construct a Scheduler from the loaded settings.yaml dictionary."""
        sched_cfg = cfg.get("schedule", {})
        lat = cfg["bird"]["latitude"]
        lon = cfg["bird"]["longitude"]
        tz = sched_cfg.get("timezone", "UTC")

        windows = [
            ListeningWindow(
                name=w["name"],
                anchor=w["anchor"],
                offset_mins=w.get("offset_mins", 0),
                duration_mins=w["duration_mins"],
                fixed_time=w.get("fixed_time"),
            )
            for w in sched_cfg.get("windows", [])
        ]
        return cls(lat=lat, lon=lon, timezone=tz, windows=windows)
