"""API routes — system status and pipeline control."""

import shutil
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException

from ecoacoustics.api import state

router = APIRouter()

try:
    _VERSION = version("ecoacoustics")
except PackageNotFoundError:
    _VERSION = "0.1.0"


def _ensure_pipeline(device_key: str, device_index=None, device_name: str = "Default"):
    """Return an existing pipeline manager, creating and wiring one if needed."""
    from ecoacoustics.api.app import get_or_create_pipeline

    mgr = get_or_create_pipeline(device_key, device_index, device_name)
    if mgr._broadcast_queue is None and state.event_loop is not None:
        mgr.set_async_context(state.event_loop, state.broadcast_queue)
    return mgr


@router.get("/status")
def get_status():
    cfg_path = Path("config/settings.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    disk = shutil.disk_usage(".")

    from ecoacoustics.scheduler import Scheduler
    scheduler = Scheduler.from_config(cfg)
    windows = [
        {"name": n, "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")}
        for s, e, n in scheduler.window_times()
    ]
    current = scheduler.current_window()

    pipelines = {k: v.status_dict() for k, v in state.pipeline_instances.items()}
    any_running = any(p["state"] != "idle" for p in pipelines.values())

    return {
        "version": _VERSION,
        "timestamp": datetime.now().isoformat(),
        "pipeline": pipelines.get("default", {"state": "idle"}),
        "pipelines": pipelines,
        "any_running": any_running,
        "schedule": {
            "windows": windows,
            "active_window": current[2] if current else None,
            "next_window": scheduler.next_window()[2] if scheduler.next_window() else None,
            "seconds_until_next": round(scheduler.seconds_until_next()),
        },
        "disk_free_gb": round(shutil.disk_usage(".").free / (1024 ** 3), 1),
        "mqtt_enabled": cfg.get("mqtt", {}).get("enabled", False),
    }


@router.post("/pipeline/wake")
def start_wake(duration_minutes: int = None, device_key: str = "default",
               device_index: int = None, device_name: str = "Default"):
    mgr = _ensure_pipeline(device_key, device_index, device_name)
    ok = mgr.start_wake(duration_minutes=duration_minutes)
    if not ok:
        raise HTTPException(400, f"Device '{device_key}' is already running")
    return {"started": True, "mode": "wake", "device_key": device_key}


@router.post("/pipeline/schedule")
def start_schedule(device_key: str = "default", device_index: int = None, device_name: str = "Default"):
    mgr = _ensure_pipeline(device_key, device_index, device_name)
    ok = mgr.start_schedule()
    if not ok:
        raise HTTPException(400, f"Device '{device_key}' is already running")
    return {"started": True, "mode": "schedule", "device_key": device_key}


@router.post("/pipeline/stop")
def stop_pipeline(device_key: str = "default"):
    if device_key not in state.pipeline_instances:
        raise HTTPException(404, f"No pipeline found for '{device_key}'")
    ok = state.pipeline_instances[device_key].stop()
    if not ok:
        raise HTTPException(400, f"Device '{device_key}' is not running")
    return {"stopped": True, "device_key": device_key}


@router.post("/debug/test_broadcast")
async def test_broadcast():
    """Fire a fake detection into the WebSocket broadcast to test the delivery chain."""
    from ecoacoustics.api.app import _broadcast_queue, _ws_clients
    payload = {
        "type": "detection",
        "session_id": "test",
        "window_name": "test",
        "date": "2026-05-01",
        "time": "12:00:00",
        "classifier": "bird",
        "species_common": "TEST — Robin",
        "species_scientific": "Erithacus rubecula",
        "confidence": 0.99,
        "call_number_in_session": 1,
        "device_name": "Test",
        "device_index": None,
    }
    await _broadcast_queue.put(payload)
    return {"queued": True, "ws_clients": len(_ws_clients)}


@router.post("/pipeline/stop_all")
def stop_all():
    stopped = []
    for key, mgr in state.pipeline_instances.items():
        if mgr.state != "idle":
            mgr.stop()
            stopped.append(key)
    return {"stopped": stopped}
