#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def assert_localhost(host: str) -> None:
    ip = socket.gethostbyname(host)
    assert ip.startswith("127."), f"external socket rejected: {host} -> {ip}"


def http_json(path: str) -> dict:
    with urlopen(path, timeout=1.0) as res:  # noqa: S310 local only
        return json.loads(res.read().decode("utf-8"))


def post_action(port: int, action: str, **params) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/action",
        data=json.dumps({"action": action, **params}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2.0) as res:  # noqa: S310 local only
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def wait_ready() -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            if http_json("http://127.0.0.1:8080/health").get("ok"):
                return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("localhost IPC suite did not become ready")


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "engines/localhost_ipc_suite.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert_localhost("127.0.0.1")
        wait_ready()

        ports = http_json("http://127.0.0.1:8080/native-bridge/ports")
        assert ports["ok"] is True
        assert [item["port"] for item in ports["ports"]] == [8080, 8081, 8082, 8083, 8084, 8085]
        assert all(item["bind"] == "127.0.0.1" for item in ports["ports"])

        mesh = http_json("http://127.0.0.1:8082/mesh/default")
        # Früher standen hier die hartcodierten Stub-Werte (rig_bones 24,
        # lod0_tris 45000) – also genau die Zahlen, die das Audit als Fake
        # geführt hat. Seit der echten Landmark-Mesh-Erzeugung (Phase 2, P2-2)
        # gelten messbare Invarianten aus der erzeugten GLB-Datei.
        assert mesh["ok"] is True and mesh["inference"] is False
        assert mesh["rig_bones"] == 26, mesh["rig_bones"]
        assert mesh["lod0_tris"] == mesh["triangles"] > 0, mesh
        assert mesh["vertices"] > 0 and mesh["glb_bytes"] > 1000
        assert len(mesh["sha256"]) == 64
        assert http_json("http://127.0.0.1:8082/mesh/default")["sha256"] == mesh["sha256"]

        rhymes = http_json("http://127.0.0.1:8085/rhymes?word=beton")
        assert "SEKTOR" in rhymes["rhymes"]

        devices = http_json("http://127.0.0.1:8080/devices/status?selected=usb_c_audio")
        assert devices["plug_and_play"] is True
        assert devices["selected"] == "usb_c_audio"
        assert {item["id"] for item in devices["devices"]} == {"usb_c_audio", "internal_mic", "bluetooth_client"}
        assert {item["key"] for item in devices["permissions"]} >= {"record_audio", "bluetooth_connect", "usb_host"}

        selected = http_json("http://127.0.0.1:8080/devices/select?input=bluetooth_client")
        assert selected["selected"] == "bluetooth_client"

        with socket.create_connection(("127.0.0.1", 8081), timeout=1.0) as sock:
            sock.sendall(b"PING")
            assert b"PCM_FLOAT32_READY" in sock.recv(128)

        with socket.create_connection(("127.0.0.1", 8083), timeout=1.0) as sock:
            avatar = json.loads(sock.recv(512).decode("utf-8"))
            assert avatar["fps"] == 60 and avatar["avatars"] == 8

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.settimeout(1.0)
            udp.sendto(b"TRANSIENT", ("127.0.0.1", 8084))
            dsp = json.loads(udp.recvfrom(512)[0].decode("utf-8"))
            assert dsp["bpm"] == 92.4 and dsp["kick808"] is True
        finally:
            udp.close()

        # --- gemeinsame Aktionskette über alle Daemons -------------------
        code, reset = post_action(8080, "chain.reset")
        assert code == 200 and reset["ok"] is True, reset
        code, early_glb = post_action(8082, "neurallift.generate", source="too-early.jpg")
        assert code == 200 and early_glb["status"] == "BLOCKED", early_glb
        assert early_glb["detail"]["missing_milestones"] == ["avatar.mode"], early_glb["detail"]
        for action, params in (
            ("input.select", {"input": "usb_c_audio"}),
            ("permission.check", {}),
            ("permission.grant", {"key": "record_audio", "granted": True}),
            ("audio.start", {"sample_rate_hz": 96000, "frames_per_buffer": 128}),
            ("mic.arm", {"device_id": "uac2"}),
        ):
            code, event = post_action(8080, action, **params)
            assert code == 200 and event["status"] == "OK", (action, event)

        code, whisper_event = post_action(8085, "transcribe", text="berlin beton sektor")
        assert code == 200 and whisper_event["status"] == "OK", whisper_event
        assert whisper_event["engine"] == "whisper" and whisper_event["port"] == 8085, whisper_event

        # avatar.mode gehört zum Avatar-Daemon (8083, TCP) und wird über den
        # Orchestrator gesetzt; erst danach darf NeuralLift erzeugen.
        code, avatar_event = post_action(8080, "avatar.mode", mode="CYPHER_CIRCLE")
        assert code == 200 and avatar_event["status"] == "OK", avatar_event

        code, blocked_glb = post_action(8082, "neurallift.generate", source="frame.jpg")
        assert code == 200 and blocked_glb["status"] == "OK", blocked_glb
        glb_event = blocked_glb
        assert code == 200 and glb_event["status"] == "OK", glb_event
        assert str(glb_event["detail"]["glb"]).endswith(".glb"), glb_event["detail"]

        # Rollen-Trennung: Whisper darf keine DSP-Aktion ausführen.
        code, denied = post_action(8085, "dsp.process", signal="hat")
        assert code == 403 and denied["ok"] is False, denied
        assert denied["serve_on_port"] == 8084, denied

        # UDP-Bridge fährt einen echten DSP-Block durch die Kette.
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.settimeout(1.0)
            udp.sendto(b"hat", ("127.0.0.1", 8084))
            dsp = json.loads(udp.recvfrom(512)[0].decode("utf-8"))
            assert dsp["hat"] is True and dsp["transient"] == "HAT_ROLL", dsp
            assert dsp["output_peak_dbfs"] <= -3.2 + 1e-6, dsp
        finally:
            udp.close()

        state = http_json("http://127.0.0.1:8080/api/state")
        assert state["input"]["selected"] == "usb_c_audio", state["input"]
        assert state["audio"]["mic_armed"] is True, state["audio"]
        assert state["dsp"]["blocks"] >= 1 and state["dsp"]["hat"] >= 1, state["dsp"]
        assert state["chain"]["length"] >= 8, state["chain"]
        assert state["chain"]["blocked"] == 1, state["chain"]
        assert "whisper" in {item["engine"] for item in http_json("http://127.0.0.1:8080/api/events?since=0")["events"]}

        mesh_after = http_json("http://127.0.0.1:8082/mesh/default")
        assert mesh_after["generated_from"] == "frame.jpg", mesh_after

        print("zero-cloud localhost IPC gate passed for ports 8080-8085 (shared action chain)")
        return 0
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=2)
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
