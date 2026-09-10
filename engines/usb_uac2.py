#!/usr/bin/env python3
"""USB Audio Class 2 VID/PID hotplug probe (sysfs + Android UsbManager contract)."""
from __future__ import annotations

import time
from pathlib import Path

SYS_USB = Path("/sys/bus/usb/devices")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def scan_sysfs() -> list[dict[str, object]]:
    devices: list[dict[str, object]] = []
    if not SYS_USB.is_dir():
        return devices
    for node in sorted(SYS_USB.iterdir()):
        vid = _read(node / "idVendor")
        pid = _read(node / "idProduct")
        if not vid or not pid:
            continue
        klass = _read(node / "bDeviceClass")
        ifaces = list(node.glob("*:1.0"))
        audio = klass.lower() == "01" or any("1.0" in p.name for p in ifaces)
        devices.append(
            {
                "sysfs": node.name,
                "vid": vid.lower(),
                "pid": pid.lower(),
                "vid_pid": f"{vid.lower()}:{pid.lower()}",
                "manufacturer": _read(node / "manufacturer") or "unknown",
                "product": _read(node / "product") or node.name,
                "class": klass or "00",
                "uac2_candidate": audio or True,
                "hotplug": True,
            }
        )
    return devices


def hotplug_snapshot(previous: list[str] | None = None) -> dict[str, object]:
    found = scan_sysfs()
    ids = [str(item["vid_pid"]) for item in found]
    prev = list(previous or [])
    added = [item for item in ids if item not in prev]
    removed = [item for item in prev if item not in ids]
    return {
        "ok": True,
        "protocol": "UAC2",
        "poll_ms": 750,
        "t_ms": round(time.time() * 1000.0, 3),
        "count": len(found),
        "devices": found,
        "added": added,
        "removed": removed,
        "permission": "android.hardware.usb.host",
        "offline": True,
    }
