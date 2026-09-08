#!/usr/bin/env python3
"""Offline plug-and-play input matrix for USB, internal mic and Bluetooth clients.

The module exposes deterministic device/permission state for CI and the web UI.
Production Android/Tauri hosts can replace the probe functions with OS-specific
USB Audio Class, AudioManager and Bluetooth profile queries while keeping the
same JSON contract.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

InputKind = Literal["usb_c_audio", "internal_mic", "bluetooth_client"]
CONFIG_PATH = Path("dist/device-matrix.json")


@dataclass(frozen=True)
class PermissionSpec:
    key: str
    android: str
    required_for: tuple[InputKind, ...]
    granted: bool
    note: str


@dataclass(frozen=True)
class DeviceSpec:
    id: InputKind
    label: str
    status: str
    sample_rate_hz: int
    bit_depth: str
    latency_ms: float
    route: str
    configurable: bool
    permissions: tuple[str, ...]


def permissions() -> list[PermissionSpec]:
    return [
        PermissionSpec("record_audio", "android.permission.RECORD_AUDIO", ("internal_mic", "usb_c_audio", "bluetooth_client"), True, "Mic capture gate"),
        PermissionSpec("modify_audio", "android.permission.MODIFY_AUDIO_SETTINGS", ("usb_c_audio", "bluetooth_client"), True, "Route switching and low-latency mode"),
        PermissionSpec("bluetooth_connect", "android.permission.BLUETOOTH_CONNECT", ("bluetooth_client",), True, "Android 12+ BT client access"),
        PermissionSpec("bluetooth_scan", "android.permission.BLUETOOTH_SCAN", ("bluetooth_client",), True, "BLE discovery without cloud"),
        PermissionSpec("usb_host", "android.hardware.usb.host", ("usb_c_audio",), True, "USB Audio Class plug-and-play"),
    ]


def devices(selected: InputKind = "internal_mic") -> list[DeviceSpec]:
    return [
        DeviceSpec(
            "usb_c_audio",
            "USB-C Audio Interface",
            "LOCKED" if selected == "usb_c_audio" else "AVAILABLE",
            96_000,
            "32-bit float",
            1.2,
            "UAC2 direct monitor / 127.0.0.1:8081",
            True,
            ("record_audio", "modify_audio", "usb_host"),
        ),
        DeviceSpec(
            "internal_mic",
            "Internes Mikrofon",
            "LOCKED" if selected == "internal_mic" else "AVAILABLE",
            48_000,
            "24-bit capture shim",
            2.6,
            "Android AudioRecord / CoreAudio default input",
            True,
            ("record_audio",),
        ),
        DeviceSpec(
            "bluetooth_client",
            "Bluetooth Client / BLE Mic",
            "LOCKED" if selected == "bluetooth_client" else "PAIRABLE",
            48_000,
            "LC3plus shim",
            4.8,
            "BLE jitter buffer / route compensation +42ms",
            True,
            ("record_audio", "modify_audio", "bluetooth_connect", "bluetooth_scan"),
        ),
    ]


def status(selected: InputKind = "internal_mic") -> dict[str, object]:
    return {
        "ok": True,
        "offline": True,
        "selected": selected,
        "plug_and_play": True,
        "hotplug_poll_ms": 750,
        "permissions": [asdict(item) for item in permissions()],
        "devices": [asdict(item) for item in devices(selected)],
    }


def save_selection(selected: InputKind) -> dict[str, object]:
    if selected not in {"usb_c_audio", "internal_mic", "bluetooth_client"}:
        raise ValueError(f"unsupported input: {selected}")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = status(selected)
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(save_selection("internal_mic"), ensure_ascii=False, indent=2))
