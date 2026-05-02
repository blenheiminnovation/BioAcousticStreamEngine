"""API routes — location and system settings."""

from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
_SETTINGS = Path("config/settings.yaml")
_SECRETS = Path("config/secrets.yaml")


def _load_secrets() -> dict:
    if _SECRETS.exists():
        with open(_SECRETS) as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_secrets(data: dict) -> None:
    with open(_SECRETS, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

_CLASSIFIERS = ["bird", "bat", "bee", "insect", "soil"]


class LocationModel(BaseModel):
    name: str
    latitude: float
    longitude: float


class ClassifierDevicesModel(BaseModel):
    active: list[str]
    devices: dict[str, Any]   # classifier name → device index/name/None


class MqttSettingsModel(BaseModel):
    enabled: bool
    mode: str                        # direct | bridge
    host: str
    port: int
    tls: bool
    topic_prefix: str
    username: Optional[str] = None
    password: Optional[str] = None   # None = leave unchanged


@router.get("/settings/location")
def get_location():
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)
    loc = cfg.get("location", {})
    bird = cfg.get("bird", {})
    return {
        "name": loc.get("name", ""),
        "latitude": loc.get("latitude", bird.get("latitude", 0.0)),
        "longitude": loc.get("longitude", bird.get("longitude", 0.0)),
    }


@router.post("/settings/location")
def set_location(body: LocationModel):
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)

    cfg["location"] = {
        "name": body.name,
        "latitude": body.latitude,
        "longitude": body.longitude,
    }
    # Keep bird lat/lon in sync so BirdNET filtering stays accurate
    if "bird" in cfg:
        cfg["bird"]["latitude"] = body.latitude
        cfg["bird"]["longitude"] = body.longitude

    with open(_SETTINGS, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    return {"updated": True}


@router.get("/settings/mqtt")
def get_mqtt():
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)
    secrets = _load_secrets()
    mqtt = cfg.get("mqtt", {})
    mqtt_secrets = secrets.get("mqtt", {})
    return {
        "enabled": mqtt.get("enabled", False),
        "mode": mqtt.get("mode", "direct"),
        "host": mqtt.get("host", "localhost"),
        "port": mqtt.get("port", 1883),
        "tls": mqtt.get("tls", False),
        "topic_prefix": mqtt.get("topic_prefix", "bioacoustics"),
        "username": mqtt_secrets.get("username", ""),
        "has_password": bool(mqtt_secrets.get("password", "")),
    }


@router.post("/settings/mqtt")
def set_mqtt(body: MqttSettingsModel):
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)

    cfg["mqtt"] = {
        "enabled": body.enabled,
        "mode": body.mode,
        "host": body.host,
        "port": body.port,
        "tls": body.tls,
        "topic_prefix": body.topic_prefix,
    }
    with open(_SETTINGS, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    # Credentials go to secrets.yaml only
    secrets = _load_secrets()
    if "mqtt" not in secrets:
        secrets["mqtt"] = {}
    if body.username is not None:
        secrets["mqtt"]["username"] = body.username
    if body.password is not None:
        secrets["mqtt"]["password"] = body.password
    _save_secrets(secrets)

    return {"updated": True}


@router.post("/settings/mqtt/test")
async def test_mqtt():
    """Attempt a live connection to the configured broker and report result."""
    import asyncio
    import ssl as _ssl
    import threading as _threading
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)
    secrets = _load_secrets()
    mqtt_cfg = cfg.get("mqtt", {})
    mqtt_secrets = secrets.get("mqtt", {})

    host = mqtt_cfg.get("host", "localhost")
    port = mqtt_cfg.get("port", 1883)
    tls = mqtt_cfg.get("tls", False)
    username = mqtt_secrets.get("username")
    password = mqtt_secrets.get("password")

    try:
        import paho.mqtt.client as mqtt_client
        result = {"connected": False, "error": None}
        # threading.Event is safe to set from paho's background thread
        done = _threading.Event()

        def on_connect(client, userdata, flags, reason_code, properties):
            success = str(reason_code) == "Success" or getattr(reason_code, "value", reason_code) == 0
            result["connected"] = success
            result["error"] = None if success else f"Broker refused connection: {reason_code}"
            done.set()

        def on_connect_fail(client, userdata):
            result["error"] = f"Could not reach {host}:{port}"
            done.set()

        client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_connect_fail = on_connect_fail
        if tls:
            client.tls_set(cert_reqs=_ssl.CERT_REQUIRED)
        if username:
            client.username_pw_set(username, password)
        client.connect_async(host, port, keepalive=10)
        client.loop_start()
        try:
            await asyncio.wait_for(asyncio.to_thread(done.wait), timeout=8.0)
        except asyncio.TimeoutError:
            result["error"] = f"Timed out connecting to {host}:{port}"
        finally:
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:
                pass
        return result
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


@router.get("/settings/classifiers")
def get_classifiers():
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)
    clf_cfg = cfg.get("classifiers", {})
    devices = clf_cfg.get("devices", {})
    active = clf_cfg.get("active", ["bird"])
    return {
        "active": active,
        "devices": {c: devices.get(c) for c in _CLASSIFIERS},
    }


@router.post("/settings/classifiers")
def set_classifiers(body: ClassifierDevicesModel):
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)
    if "classifiers" not in cfg:
        cfg["classifiers"] = {}
    cfg["classifiers"]["active"] = body.active
    cfg["classifiers"]["devices"] = body.devices
    with open(_SETTINGS, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    return {"updated": True}
