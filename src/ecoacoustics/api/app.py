"""
FastAPI application — serves the REST API and web UI.

IMPORTANT: The WebSocket route and all API routes must be registered BEFORE
app.mount("/", StaticFiles(...)) — StaticFiles mounted at "/" intercepts every
request including WebSocket upgrades, so anything registered after the mount
is unreachable.

Author: David Green, Blenheim Palace
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ecoacoustics.api import state
from ecoacoustics.api.pipeline_manager import PipelineManager
from ecoacoustics.api.routes import clips, detections, devices, reports, schedule, settings, status

CONFIG_PATH = "config/settings.yaml"

_ws_clients: set[WebSocket] = set()
_broadcast_queue: asyncio.Queue = asyncio.Queue()


def get_or_create_pipeline(device_key: str, device_index=None, device_name: str = "Default") -> PipelineManager:
    if device_key not in state.pipeline_instances:
        state.pipeline_instances[device_key] = PipelineManager(
            config_path=CONFIG_PATH,
            device_index=device_index,
            device_name=device_name,
        )
    return state.pipeline_instances[device_key]


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    # Store in state so sync route handlers can wire new pipelines without needing
    # asyncio.get_running_loop() (which raises RuntimeError outside async context).
    state.event_loop = loop
    state.broadcast_queue = _broadcast_queue
    mgr = get_or_create_pipeline("default", device_index=None, device_name="Default")
    mgr.set_async_context(loop, _broadcast_queue)
    task = asyncio.create_task(_broadcast_loop())
    yield
    task.cancel()


app = FastAPI(title="BioAcoustic Stream Engine (BASE)", lifespan=lifespan)

# ── API routes — registered first so StaticFiles mount cannot shadow them ──
app.include_router(status.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(detections.router, prefix="/api")
app.include_router(clips.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(settings.router, prefix="/api")


# ── WebSocket — must be before the StaticFiles mount ──
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)
    except Exception:
        _ws_clients.discard(websocket)


# ── Static files — mounted last so it only catches unmatched requests ──
_web_dir = Path(__file__).parent.parent / "web"
app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")


async def _broadcast_loop() -> None:
    print("[BCAST] loop started", flush=True)
    try:
        while True:
            data = await _broadcast_queue.get()
            print(f"[BCAST] got type={data.get('type')} clients={len(_ws_clients)}", flush=True)
            dead: set[WebSocket] = set()
            for ws in list(_ws_clients):
                try:
                    await ws.send_json(data)
                    print(f"[BCAST] sent ok", flush=True)
                except Exception as e:
                    print(f"[BCAST] send failed: {e}", flush=True)
                    dead.add(ws)
            _ws_clients.difference_update(dead)
    except Exception as e:
        print(f"[BCAST] loop CRASHED: {e}", flush=True)


def run(host: str = "0.0.0.0", port: int = 8000) -> None:
    uvicorn.run("ecoacoustics.api.app:app", host=host, port=port, reload=False)
