"""
MQTT publisher — broadcasts every detection as a JSON message.

Topics published:
  {prefix}/detections            — every detection regardless of classifier
  {prefix}/detections/{classifier} — e.g. bioacoustics/detections/bird

Payload (JSON):
  {
    "session_id": "a3f1b2c4",
    "window_name": "dawn_chorus",
    "date": "2026-05-01",
    "time": "05:23:11",
    "classifier": "bird",
    "species_common": "European Robin",
    "species_scientific": "Erithacus rubecula",
    "species_image": "european_robin.jpg",
    "confidence": 0.873,
    "call_number_in_session": 3,
    "latitude": 51.8403,
    "longitude": -1.3625
  }

Author: David Green, Blenheim Palace
"""

import datetime
import json
import logging
import re
import ssl

import paho.mqtt.client as mqtt

from ecoacoustics.classifiers.base import Detection
from ecoacoustics.session import Session

_log = logging.getLogger(__name__)


class MqttPublisher:
    """Thin wrapper around paho-mqtt for publishing detection events.

    Supports two connection modes:
      - Bridge mode: connect to a local Mosquitto broker (no credentials needed;
        Mosquitto handles bridging and auth to the remote broker).
      - Direct mode: connect straight to a remote broker, with optional TLS and
        credentials supplied via config/secrets.yaml.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1883,
        topic_prefix: str = "bioacoustics",
        tls: bool = False,
        username: str | None = None,
        password: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        location_name: str | None = None,
    ):
        self._prefix = topic_prefix.rstrip("/")
        self._lat = latitude
        self._lon = longitude
        self._location_name = location_name or ""

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        if tls:
            self._client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        if username:
            self._client.username_pw_set(username, password)

        try:
            self._client.connect(host, port, keepalive=60)
            self._client.loop_start()
        except Exception as exc:
            _log.warning("MQTT: could not connect to %s:%d — %s", host, port, exc)

    def publish(self, det: Detection, session: Session, call_n: int) -> None:
        """Publish a single detection to the broker."""
        ts = datetime.datetime.fromtimestamp(det.timestamp)
        payload = {
            "session_id": session.session_id,
            "window_name": session.window_name,
            "date": ts.strftime("%Y-%m-%d"),
            "time": ts.strftime("%H:%M:%S"),
            "classifier": det.classifier,
            "species_common": det.label,
            "species_scientific": det.metadata.get("scientific_name", ""),
            "species_image": re.sub(r"[^a-z0-9]+", "_", det.label.lower().replace("'", "")).strip("_") + ".jpg",
            "confidence": round(det.confidence, 4),
            "call_number_in_session": call_n,
            "location_name": self._location_name,
            "latitude": self._lat,
            "longitude": self._lon,
        }
        message = json.dumps(payload)
        self._client.publish(f"{self._prefix}/detections", message)
        self._client.publish(f"{self._prefix}/detections/{det.classifier}", message)

    def close(self) -> None:
        """Stop the network loop and disconnect cleanly."""
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if str(reason_code) == "Success" or getattr(reason_code, "value", reason_code) == 0:
            _log.info("MQTT: connected")
        else:
            _log.warning("MQTT: connection refused (reason %s)", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            _log.warning("MQTT: unexpected disconnect (reason %s)", reason_code)
