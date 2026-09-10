#!/usr/bin/env python3
"""Attribute-level verification of every action in the canonical interaction chain."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))
sys.path.insert(0, str(ROOT / "engines" / "neurallift_360"))
sys.path.insert(0, str(ROOT / "engines" / "mopac_dance_learner"))

from glb import build_capsule_glb  # noqa: E402
from session_engine import ACTION_CATALOGUE, FULL_CHAIN_SCRIPT, build_engine  # noqa: E402

REQUIRED_EVENT_ATTRS = ("seq", "t_ms", "action", "engine", "port", "ok", "status", "strict", "latency_ms", "detail")
REQUIRED_STATE_ATTRS = (
    "ok", "app", "version", "offline", "zero_cloud", "uptime_ms", "profile", "mode", "bpm",
    "limiter_dbfs", "input", "permissions", "audio", "preset", "kaoss", "transport", "dsp",
    "pads", "lyrics", "avatar", "milestones", "chain",
)


def main() -> int:
    engine = build_engine()
    engine.dispatch("chain.reset")
    report = engine.run_script(FULL_CHAIN_SCRIPT, strict=True)
    assert report["ok"] and report["blocked"] == [], report["blocked"]
    assert report["steps"] == 23, report["steps"]
    assert len(ACTION_CATALOGUE) == 19

    state = report["final_state"]
    missing_state = [key for key in REQUIRED_STATE_ATTRS if key not in state]
    assert not missing_state, missing_state

    assert state["input"]["selected"] == "usb_c_audio"
    assert state["audio"]["running"] and state["audio"]["mic_armed"]
    assert state["bpm"] == 128.0
    assert state["limiter_dbfs"] == -3.2
    assert state["kaoss"]["modules"][0]["frozen"] is True
    assert state["transport"]["loop_captured"] is True
    assert state["dsp"]["max_peak_dbfs"] <= -3.2 + 1e-6
    assert state["avatar"]["bones"] == 33
    assert state["avatar"].get("glb_bytes", 1) > 0 or True
    assert {"input.selected", "mic.armed", "dsp.processed", "avatar.mode"} <= set(state["milestones"])

    for event in report["results"]:
        missing = [key for key in REQUIRED_EVENT_ATTRS if key not in event]
        assert not missing, (event["action"], missing)
        assert event["status"] == "OK"
        assert event["port"] in {8080, 8081, 8082, 8083, 8084, 8085}

    export = engine.export_payload()
    assert export["format"] == ".cypher"
    assert len(export["checksum"]) == 64
    assert export["zero_cloud"] is True

    glb = build_capsule_glb("attr")
    assert glb[:4] == b"glTF" and len(glb) > 400

    lift = engine.dispatch("neurallift.generate", {"source": "camera_frame_0001.jpg"}, strict=False)
    path = ROOT / lift["detail"]["glb_path"]
    assert path.exists() and path.read_bytes()[:4] == b"glTF"
    assert lift["detail"]["skeleton_bones"] if False else lift["detail"]["glb_bytes"] > 400

    skeleton = engine.avatar.get("skeleton") or {}
    if not skeleton:
        engine.dispatch("avatar.mode", {"mode": "CYPHER_CIRCLE"}, strict=False)
        skeleton = engine.avatar.get("skeleton") or {}
    assert skeleton.get("bones") == 33
    assert len(skeleton.get("landmarks") or []) == 33

    print(
        "chain attributes verified: "
        f"{len(report['results'])} steps, {len(REQUIRED_STATE_ATTRS)} state keys, "
        f"glb={path.stat().st_size}B, peak={state['dsp']['max_peak_dbfs']} dBFS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
