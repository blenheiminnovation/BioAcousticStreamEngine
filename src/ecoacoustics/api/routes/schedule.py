"""API routes — schedule management."""

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_SETTINGS = Path("config/settings.yaml")
_UI_WINDOWS = Path("config/ui_windows.yaml")


class WindowModel(BaseModel):
    name: str
    anchor: str          # sunrise | sunset | noon | fixed
    offset_mins: int = 0
    duration_mins: int
    fixed_time: Optional[str] = None   # "HH:MM" when anchor == fixed


def _load_ui_windows() -> list[dict]:
    if _UI_WINDOWS.exists():
        with open(_UI_WINDOWS) as f:
            data = yaml.safe_load(f) or {}
        return data.get("windows", [])
    return []


def _save_ui_windows(windows: list[dict]) -> None:
    with open(_UI_WINDOWS, "w") as f:
        yaml.dump({"windows": windows}, f, default_flow_style=False)


@router.get("/schedule")
def get_schedule():
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)

    from ecoacoustics.scheduler import Scheduler
    scheduler = Scheduler.from_config(cfg)
    current = scheduler.current_window()

    windows = []
    for start, end, name in scheduler.window_times():
        windows.append({
            "name": name,
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
            "duration_mins": int((end - start).total_seconds() / 60),
            "active": current is not None and current[2] == name,
            "editable": False,
        })

    for w in _load_ui_windows():
        windows.append({**w, "editable": True})

    return {
        "windows": windows,
        "timezone": cfg.get("schedule", {}).get("timezone", "UTC"),
    }


@router.post("/schedule/windows")
def add_window(window: WindowModel):
    if not window.name or not window.duration_mins:
        raise HTTPException(400, "name and duration_mins are required")
    if window.anchor not in ("sunrise", "sunset", "noon", "fixed"):
        raise HTTPException(400, "anchor must be sunrise | sunset | noon | fixed")
    if window.anchor == "fixed" and not window.fixed_time:
        raise HTTPException(400, "fixed_time required when anchor is fixed")

    existing = _load_ui_windows()
    if any(w["name"] == window.name for w in existing):
        raise HTTPException(409, f"Window '{window.name}' already exists")

    existing.append(window.model_dump())
    _save_ui_windows(existing)
    return {"added": window.name}


@router.delete("/schedule/windows/{name}")
def delete_window(name: str):
    existing = _load_ui_windows()
    updated = [w for w in existing if w["name"] != name]
    if len(updated) == len(existing):
        raise HTTPException(404, f"Window '{name}' not found or not user-created")
    _save_ui_windows(updated)
    return {"deleted": name}
