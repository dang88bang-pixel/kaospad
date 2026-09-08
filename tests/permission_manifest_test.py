#!/usr/bin/env python3
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
ANDROID = "{http://schemas.android.com/apk/res/android}"

REQUIRED_PERMISSIONS = {
    "android.permission.RECORD_AUDIO",
    "android.permission.MODIFY_AUDIO_SETTINGS",
    "android.permission.BLUETOOTH_CONNECT",
    "android.permission.BLUETOOTH_SCAN",
}
REQUIRED_FEATURES = {
    "android.hardware.audio.low_latency",
    "android.hardware.usb.host",
    "android.hardware.bluetooth_le",
}


def names(root: ET.Element, tag: str) -> set[str]:
    return {item.attrib.get(f"{ANDROID}name", "") for item in root.findall(tag)}


def main() -> int:
    root = ET.parse(MANIFEST).getroot()
    permissions = names(root, "uses-permission")
    features = names(root, "uses-feature")
    missing_permissions = REQUIRED_PERMISSIONS - permissions
    missing_features = REQUIRED_FEATURES - features
    if missing_permissions or missing_features:
        print(f"missing permissions={sorted(missing_permissions)} features={sorted(missing_features)}", file=sys.stderr)
        return 1
    print("android USB/mic/bluetooth permissions and features declared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
