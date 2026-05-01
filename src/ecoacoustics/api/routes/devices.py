"""API routes — audio input device listing via pactl (PipeWire/PulseAudio sources)."""

import subprocess
import re

from fastapi import APIRouter

router = APIRouter()


def _pactl_sources() -> list[dict]:
    """Return real audio input sources from PipeWire/PulseAudio via pactl."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "short", "sources"], text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []

    sources = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        index, name, driver, spec, state = parts[0], parts[1], parts[2], parts[3], parts[4].strip()

        # Skip monitor sources (loopback of speaker output)
        if name.endswith(".monitor"):
            continue

        # Parse sample spec e.g. "s32le 2ch 48000Hz"
        channels = 1
        sample_rate = 48000
        ch_match = re.search(r"(\d+)ch", spec)
        hz_match = re.search(r"(\d+)Hz", spec)
        if ch_match:
            channels = int(ch_match.group(1))
        if hz_match:
            sample_rate = int(hz_match.group(1))

        label = _friendly_name(name)
        sources.append({
            "index": int(index),
            "name": name,
            "label": label,
            "channels": channels,
            "sample_rate": sample_rate,
            "state": state,
            "is_default": False,
        })

    # Mark the system default
    try:
        info = subprocess.check_output(["pactl", "info"], text=True, timeout=5)
        for line in info.splitlines():
            if "Default Source:" in line:
                default_name = line.split(":", 1)[1].strip()
                for s in sources:
                    if s["name"] == default_name:
                        s["is_default"] = True
    except Exception:
        pass

    return sources


def _friendly_name(name: str) -> str:
    """Turn a PipeWire source name into a human-readable label."""
    if "usb" in name.lower():
        # e.g. alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone-...
        parts = name.split(".")
        if len(parts) > 1:
            usb_part = parts[1].split("-")
            label = " ".join(w.capitalize() for w in usb_part[:4] if not w.isdigit())
            return f"USB Mic — {label}".strip(" —")
    if "pci" in name.lower():
        if "analog" in name.lower():
            return "Built-in Microphone (analogue)"
        if "hdmi" in name.lower():
            return "HDMI Audio Input"
        return "Built-in Audio Input"
    if "bluez" in name.lower():
        return "Bluetooth Audio Input"
    return name


@router.get("/devices")
def list_devices():
    sources = _pactl_sources()

    if not sources:
        # Fallback: sounddevice list if pactl unavailable
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            sources = [
                {
                    "index": i,
                    "name": d["name"],
                    "label": d["name"],
                    "channels": int(d["max_input_channels"]),
                    "sample_rate": int(d["default_samplerate"]),
                    "state": "UNKNOWN",
                    "is_default": sd.default.device[0] == i,
                }
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            ]
        except Exception as exc:
            return {"devices": [], "error": str(exc)}

    return {"devices": sources}
