#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web/index.html"
APP = ROOT / "web/src/app.js"
ENGINE = ROOT / "web/src/audio-engine.js"

REQUIRED_IDS = {
    "start-audio",
    "arm-mic",
    "trigger-808",
    "trigger-snare",
    "browser-device-select",
    "audio-state",
    "meter-fill",
    "meter-readout",
    "rhyme-word",
    "lookup-rhyme",
    "rhyme-output",
    "input-select",
    "permission-check",
    "portview-auto",
}
REQUIRED_ENGINE_TOKENS = {
    "class WebAudioCypherEngine",
    "getUserMedia",
    "enumerateDevices",
    "trigger808",
    "triggerSnare",
    "brickwallCurve",
    "createBiquadFilter",
    "createDelay",
    "createWaveShaper",
}
REQUIRED_APP_TOKENS = {
    "WebAudioCypherEngine",
    "refreshDeviceMatrix",
    "lookupRhymes",
    "applyXY",
    "BRIDGE: LOCALHOST IPC LIVE",
}


def main() -> int:
    index = INDEX.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    engine = ENGINE.read_text(encoding="utf-8")
    missing_ids = [item for item in REQUIRED_IDS if f'id="{item}"' not in index]
    missing_engine = [item for item in REQUIRED_ENGINE_TOKENS if item not in engine]
    missing_app = [item for item in REQUIRED_APP_TOKENS if item not in app]
    if missing_ids or missing_engine or missing_app:
        raise SystemExit(f"missing ids={missing_ids} engine={missing_engine} app={missing_app}")
    print("web functional audio/device/rhyme contract declared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
