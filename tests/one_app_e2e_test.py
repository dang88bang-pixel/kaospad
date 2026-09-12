#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def get_json(path: str) -> dict:
    with urlopen(path, timeout=1.5) as res:  # noqa: S310 local only
        return json.loads(res.read().decode("utf-8"))


def post_json(path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = Request(path, data=body, headers={"content-type": "application/json"})  # noqa: S310 local only
    with urlopen(req, timeout=5) as res:
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

        runtime = get_json("http://127.0.0.1:8090/api/runtime")
        assert runtime["port"] == 8090
        assert runtime["auto_port"] is True
        assert "/native-bridge/ports" in runtime["endpoints"]

        status = get_json("http://127.0.0.1:8090/api/status")
        assert status["mode"] == "single-application"
        assert status["features"]["web_audio_engine"] is True
        assert status["features"]["auto_port_runtime"] is True

        ports = get_json("http://127.0.0.1:8090/native-bridge/ports")
        assert len(ports["ports"]) == 6
        assert all(item["single_app"] is True for item in ports["ports"])

        devices = get_json("http://127.0.0.1:8090/devices/status?selected=bluetooth_client")
        assert devices["selected"] == "bluetooth_client"
        assert {item["id"] for item in devices["devices"]} == {"usb_c_audio", "internal_mic", "bluetooth_client"}

        rhymes = get_json("http://127.0.0.1:8090/rhymes?word=beton")
        assert "SEKTOR" in rhymes["rhymes"]

        mesh = get_json("http://127.0.0.1:8090/mesh/default")
        # Früher stand hier `assert mesh["rig_bones"] == 24` – eine der erfundenen
        # Stub-Zahlen aus dem Audit (45000 Triangles / 24 Bones / 1800 ms). Vor
        # `neurallift.generate` ist der Avatar die ehrliche Fallback-Kapsel:
        # ohne Rig, aber mit echten, aus den GLB-Bytes gelesenen Kennzahlen.
        assert mesh["ok"] is True and mesh["inference"] is False
        assert mesh["rigged"] is False and mesh["rig_bones"] == 0, mesh
        assert mesh["lod0_tris"] > 0 and mesh["vertices"] > 0, mesh
        assert mesh["lod1_tris"] == 0 and mesh["fallback"] is True, mesh

        # `neurallift.generate` braucht den Kettenkontext (Milestone `avatar.mode`).
        chain = post_json("http://127.0.0.1:8090/api/chain/run", {
            "strict": False,
            "script": [
                {"action": "avatar.mode", "mode": "CYPHER_CIRCLE"},
                {"action": "neurallift.generate", "source": "camera_frame_0001.jpg", "t_ms": 1200.0, "energy": 0.6},
            ],
        })
        run = chain["chain_run"]
        assert run["blocked"] == [], run["blocked"]
        detail = next(
            item["detail"] for item in run["results"] if item["action"] == "neurallift.generate"
        )
        assert detail["magic"] == "glTF" and detail["rigged"] is True, detail
        assert detail["rig_bones"] == 26 and detail["lod0_tris"] == 1248, detail
        assert detail["vertices"] == 780 and detail["glb_bytes"] > 1000, detail
        assert len(detail["glb_sha256"]) == 64 and detail["generate_ms"] > 0, detail
        glb = ROOT / detail["glb_path"]
        assert glb.is_file() and glb.read_bytes()[:4] == b"glTF", detail["glb_path"]

        mesh_after = get_json("http://127.0.0.1:8090/mesh/default")
        assert mesh_after["rigged"] is True and mesh_after["rig_bones"] == 26, mesh_after
        assert mesh_after["lod0_tris"] == detail["lod0_tris"], mesh_after

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
