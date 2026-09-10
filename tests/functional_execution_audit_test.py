#!/usr/bin/env python3
"""Funktionale Ausführung ALLER 19 Aktionen + HAL-Endpunkte gegen live app.py.

Prüft nicht nur HTTP-200, sondern Side-Effects im State (Input lock, Mic armed,
DSP-Peak, Freeze, Loop-Frames, GLB-Datei, Checksum, Replay).
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))
from session_engine import ACTION_CATALOGUE, FULL_CHAIN_SCRIPT  # noqa: E402

CHECKS: list[str] = []


def check(label: str, cond: bool, detail: object = "") -> None:
    assert cond, f"FAIL {label}: {detail}"
    CHECKS.append(label)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class App:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"

    def json(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    def get(self, path: str) -> dict:
        return self.json("GET", path)

    def post(self, path: str, payload: dict) -> dict:
        return self.json("POST", path, payload)

    def act(self, action: str, **params) -> dict:
        return self.post("/api/action", {"action": action, **params})


def wait(app: App, proc: subprocess.Popen) -> None:
    for _ in range(80):
        if proc.poll() is not None:
            raise AssertionError("app died")
        try:
            if app.get("/health").get("ok"):
                return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("app not ready")


def main() -> int:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py"), "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    app = App(port)
    try:
        wait(app, proc)
        names = [spec.action for spec in ACTION_CATALOGUE]
        check("catalogue 19", len(names) == 19, names)

        reset = app.act("chain.reset")
        check("chain.reset clears", reset["ok"] is True)

        boot = app.act("boot")
        check("boot version", boot["detail"]["booted"] is True and "5.0.0" in boot["detail"]["version"])

        sel = app.act("input.select", input="internal_mic")
        check("input.select functional", sel["detail"]["selected"] == "internal_mic" and sel["state"]["input"]["selected"] == "internal_mic")

        chk = app.act("permission.check")
        check("permission.check pending", "record_audio" in chk["detail"]["pending"])

        grant = app.act("permission.grant", key="record_audio", granted=True)
        check("permission.grant mic", grant["detail"]["runtime_grants"]["record_audio"] is True)

        audio = app.act("audio.start", sample_rate_hz=96000, frames_per_buffer=128)
        check("audio.start running", audio["detail"]["running"] is True)
        check("audio.start oboe json", audio["detail"]["oboe"]["exclusive"] is True, audio["detail"].get("oboe"))
        check("audio.start roundtrip", audio["detail"]["roundtrip_ms"] > 0)

        mic = app.act("mic.arm", device_id="functional-mic")
        check("mic.arm", mic["detail"]["armed"] is True and mic["state"]["audio"]["mic_armed"] is True)

        preset = app.act("preset.apply", preset="cyber_drill")
        check("preset.apply bpm", preset["detail"]["bpm"] == 142.0)

        xy = app.act("kaoss.xy", module=1, x=0.33, y=0.66)
        check("kaoss.xy", xy["detail"]["x"] == 0.33 and xy["detail"]["y"] == 0.66)

        fr = app.act("kaoss.freeze", module=1, frozen=True)
        check("kaoss.freeze", fr["detail"]["frozen"] is True)

        dsp = app.act("dsp.process", signal="mouth_bass", frames=128, sample_rate_hz=96000)
        report = dsp["detail"]["report"]
        check("dsp.process kick", report["transient"]["kind"] == "KICK808")
        check("dsp.process limiter", report["output_peak_dbfs"] <= -3.2 + 1e-6)
        check("dsp.process latency", report["latency_ms"] <= 1.2)
        check("dsp.process checksum", len(report["checksum"]) >= 16, report["checksum"])

        pad = app.act("pad.trigger", bank="A", slot="BOOM")
        check("pad.trigger voice", pad["detail"]["pad"]["voice_frames"] > 0)

        rec = app.act("transport.record", running=True)
        check("transport.record", rec["detail"]["recording"] is True)

        loop = app.act("loop.capture", subdivision=16)
        check("loop.capture frames", loop["detail"]["loop_frames"] > 0 and loop["detail"]["looper"]["frozen"] is True)

        tr = app.act("transcribe", text="beton sektor")
        check("transcribe offline", tr["detail"]["transcript"]["offline"] is True)
        check("transcribe rhymes", bool(tr["detail"]["rhymes"]))

        rh = app.act("rhyme.lookup", word="beton")
        check("rhyme.lookup", "SEKTOR" in rh["detail"]["rhymes"])

        av = app.act("avatar.mode", mode="PARTY_8")
        check("avatar.mode party", av["detail"]["avatars"] == 8 and av["detail"]["skeleton_bones"] == 33)

        nl = app.act("neurallift.generate", source="audit.jpg")
        glb = ROOT / nl["detail"]["glb_path"]
        check("neurallift glb file", glb.is_file() and glb.stat().st_size > 32, glb)
        check("neurallift fallback", nl["detail"]["fallback"] is True)

        stop = app.act("transport.record", running=False)
        check("record stop", stop["detail"]["recording"] is False)

        exp = app.act("session.export")
        session = exp["detail"]["session"]
        check("export cypher", session["format"] == ".cypher" and len(session["checksum"]) == 64)
        executed = {event["action"] for event in session["action_chain"]}
        missing = [action for action in names if action not in executed and action not in {"chain.reset", "session.export"}]
        check("all catalogue actions executed", missing == [], missing)

        # HAL live endpoints
        usb = app.get("/devices/usb")
        check("usb hotplug contract", usb["ok"] is True and usb["protocol"] == "UAC2")
        ble = app.get("/devices/ble")
        check("ble lc3plus", ble["selected"]["id"] == "lc3plus")
        oboe = app.get("/audio/oboe")
        check("oboe exclusive endpoint", oboe["exclusive"] is True and oboe["opened"] is True)
        whisper = app.get("/models/whisper")
        check("whisper model status", "loaded" in whisper or whisper.get("ok") is not False)
        midas = app.get("/models/midas")
        check("midas buffer", midas.get("ok") is True or "width" in midas or "depth" in str(midas))

        # Replay
        imp = app.post("/api/session/import", {"session": session})
        check("session.import ran", imp["ok"] is True or "replay" in imp, imp)

        # Canonical script still green
        app.act("chain.reset")
        run = app.post("/api/chain/run", {"strict": True})
        check("full script ok", run["ok"] is True and run["chain_run"]["steps"] == len(FULL_CHAIN_SCRIPT), run["chain_run"].get("blocked"))
        check("full script no blocked", run["chain_run"]["blocked"] == [])

        state = app.get("/api/state")
        check("final mic armed", state["audio"]["mic_armed"] is True)
        check("final dsp blocks", state["dsp"]["blocks"] >= 3)
        check("final limiter", state["dsp"]["max_peak_dbfs"] <= -3.2 + 1e-6)

        print(f"funktionale Ausführung aller Aktionen: {len(CHECKS)} Checks, catalogue={len(names)}")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
