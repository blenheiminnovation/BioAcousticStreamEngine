import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from astral import LocationInfo
from astral.sun import sun


@dataclass
class ListeningWindow:
    name: str
    anchor: str          # "sunrise" | "sunset" | "noon" | "fixed"
    offset_mins: int     # minutes before(-) or after(+) anchor
    duration_mins: int
    fixed_time: Optional[str] = None  # "HH:MM" when anchor == "fixed"


class Scheduler:
    def __init__(self, lat: float, lon: float, timezone: str, windows: list[ListeningWindow]):
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
        """Returns sorted list of (start, end, name) for all windows on a given date."""
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
        now = datetime.now(self._tz)
        for start, end, name in self.window_times():
            if start <= now < end:
                return (start, end, name)
        return None

    def next_window(self) -> Optional[tuple[datetime, datetime, str]]:
        now = datetime.now(self._tz)
        for start, end, name in self.window_times():
            if start > now:
                return (start, end, name)
        # wrap to tomorrow
        for start, end, name in self.window_times(date.today() + timedelta(days=1)):
            return (start, end, name)
        return None

    def seconds_until_next(self) -> float:
        nw = self.next_window()
        if nw is None:
            return 3600.0
        return max(0.0, (nw[0] - datetime.now(self._tz)).total_seconds())

    def today_summary(self) -> str:
        lines = []
        for start, end, name in self.window_times():
            lines.append(f"  {name:<20} {start.strftime('%H:%M')} → {end.strftime('%H:%M')}")
        return "\n".join(lines) if lines else "  (no windows configured)"

    # ------------------------------------------------------------------
    # Adaptive scheduling
    # ------------------------------------------------------------------

    def adapt(self, species_detected: set[str], adaptive_cfg: dict) -> list[str]:
        """
        Inspect detected species and add extra windows when trigger species appear.
        Returns list of newly added window names.
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
