#!/usr/bin/env python3
"""BLE / Classic Bluetooth codec matrix for client mics (LC3, SBC, AAC, aptX)."""
from __future__ import annotations

from pathlib import Path

CODECS = (
    {"id": "lc3plus", "name": "LC3plus", "latency_ms": 15.0, "bitrate_kbps": 96, "ble": True, "preferred": True},
    {"id": "lc3", "name": "LC3", "latency_ms": 20.0, "bitrate_kbps": 64, "ble": True, "preferred": False},
    {"id": "sbc", "name": "SBC", "latency_ms": 40.0, "bitrate_kbps": 328, "ble": False, "preferred": False},
    {"id": "aac", "name": "AAC", "latency_ms": 30.0, "bitrate_kbps": 256, "ble": False, "preferred": False},
    {"id": "aptx", "name": "aptX", "latency_ms": 32.0, "bitrate_kbps": 352, "ble": False, "preferred": False},
)


def negotiate(preferred: str = "lc3plus") -> dict[str, object]:
    chosen = next((c for c in CODECS if c["id"] == preferred), CODECS[0])
    hci = Path("/sys/class/bluetooth")
    adapters = [p.name for p in hci.iterdir()] if hci.is_dir() else []
    return {
        "ok": True,
        "selected": chosen,
        "available": list(CODECS),
        "compensation_ms": 42.0 if chosen["id"] in {"sbc", "aac"} else 12.0,
        "jitter_buffer_ms": 24.0,
        "adapters": adapters,
        "permissions": ["BLUETOOTH_CONNECT", "BLUETOOTH_SCAN", "RECORD_AUDIO"],
        "offline": True,
        "route": "ble://client/127.0.0.1:8081",
    }
