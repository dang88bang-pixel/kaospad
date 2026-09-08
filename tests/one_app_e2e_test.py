#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def get_json(path: str) -> dict:
    with urlopen(path, timeout=1.5) as res:  # noqa: S310 local only
        return json.loads(res.read().decode("utf-8"))


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py"), "--host", "127.0.0.1", "--port", "8090"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                if get_json("http://127.0.0.1:8090/health")["ok"]:
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("Kaoss One App did not start")

        status = get_json("http://127.0.0.1:8090/api/status")
        assert status["mode"] == "single-application"
        assert status["features"]["web_audio_engine"] is True

        ports = get_json("http://127.0.0.1:8090/native-bridge/ports")
        assert len(ports["ports"]) == 6
        assert all(item["single_app"] is True for item in ports["ports"])

        devices = get_json("http://127.0.0.1:8090/devices/status?selected=bluetooth_client")
        assert devices["selected"] == "bluetooth_client"
        assert {item["id"] for item in devices["devices"]} == {"usb_c_audio", "internal_mic", "bluetooth_client"}

        rhymes = get_json("http://127.0.0.1:8090/rhymes?word=beton")
        assert "SEKTOR" in rhymes["rhymes"]

        mesh = get_json("http://127.0.0.1:8090/mesh/default")
        assert mesh["rig_bones"] == 24

        transient = get_json("http://127.0.0.1:8090/dsp/transient")
        assert transient["kick808"] is True and transient["latency_ms"] <= 1.2

        presets = get_json("http://127.0.0.1:8090/api/presets")
        assert {item["id"] for item in presets["presets"]} >= {"90s_tape", "acid_berlin", "cyber_drill", "lofi_cypher"}
        assert len(presets["sample_banks"]) == 4

        session = get_json("http://127.0.0.1:8090/api/session/export?preset=acid_berlin&input=usb_c_audio")
        assert session["session"]["format"] == ".cypher"
        assert session["session"]["preset"] == "acid_berlin"

        logs = get_json("http://127.0.0.1:8090/api/logs")
        assert any("DSP limiter" in line for line in logs["logs"])

        print("kaoss one-app e2e contract passed")
        return 0
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=2)
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
