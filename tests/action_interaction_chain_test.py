#!/usr/bin/env python3
"""End-to-End-Test der vollständigen Aktions- und Interaktionskette.

Der Test startet die Kaoss One App (``app.py``) als echten HTTP-Server und fährt
die komplette Benutzerkette durch:

    Input wählen -> Permissions prüfen/erteilen -> Audio starten -> Mic armen
    -> Preset laden -> XY-Pad -> Freeze -> DSP-Blöcke -> Pads A-D -> Record
    -> Loop Capture -> Transkript -> Reime -> Avatar-Modus -> NeuralLift GLB
    -> Record Stop -> .cypher Export

Verifiziert werden: Reihenfolge-Guards (BLOCKED), State-Übergänge, DSP-Zahlen
(-3.2 dBFS Limiter, Transient-Klassifikation, <=1.2 ms Latenz), Ketten-Äquivalenz
zum Referenzmodell, Determinismus des Export-Checksums, Projektions-Endpoints,
Zero-Cloud-Header und der Localhost-Origin-Guard.
"""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))

from session_engine import FULL_CHAIN_SCRIPT, build_engine  # noqa: E402

STEP_BUDGET_MS = 400.0
DSP_LATENCY_BUDGET_MS = 1.2
LIMITER_DBFS = -3.2
CHECKS: list[str] = []


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Client:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.headers_seen: set[str] = set()

    def request(self, method: str, path: str, payload: dict | None = None, headers: dict | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:  # noqa: S310 local only
                body = json.loads(response.read().decode("utf-8"))
                self.headers_seen.update(response.headers.keys())
                return response.status, body, response.headers
        except urllib.error.HTTPError as exc:  # 4xx/5xx sind Teil des Vertrags
            raw = exc.read().decode("utf-8")
            with contextlib.suppress(json.JSONDecodeError):
                return exc.code, json.loads(raw), exc.headers
            return exc.code, {"raw": raw}, exc.headers

    def get(self, path: str, headers: dict | None = None):
        return self.request("GET", path, None, headers)

    def post(self, path: str, payload: dict | None = None, headers: dict | None = None):
        return self.request("POST", path, payload if payload is not None else {}, headers)

    def action(self, action: str, **params):
        code, body, _ = self.post("/api/action", {"action": action, **params})
        assert code == 200, f"{action} -> HTTP {code}: {body}"
        return body


def short(detail: object, limit: int = 240) -> str:
    text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + " …"


def check(label: str, condition: bool, detail: object = "") -> None:
    assert condition, f"CHECK FAILED: {label} // {short(detail)}"
    CHECKS.append(label)


def reference_export_checksum() -> str:
    """Identische Kette offline im Referenzmodell -> erwarteter .cypher Hash."""
    engine = build_engine()
    engine.dispatch("chain.reset")  # gleicher Startpunkt wie der Server-Run
    report = engine.run_script(FULL_CHAIN_SCRIPT, strict=True)
    assert report["ok"], report["blocked"]
    return engine.export_payload()["checksum"]


def wait_ready(client: Client, proc: subprocess.Popen) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            stdout = proc.stdout.read() if proc.stdout else ""
            stderr = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"Kaoss One App exited early:\n{stdout}\n{stderr}")
        try:
            code, body, _ = client.get("/health")
            if code == 200 and body.get("ok"):
                return
        except Exception:  # noqa: BLE001 - Server startet noch
            pass
        time.sleep(0.1)
    raise AssertionError("Kaoss One App did not start")


def main() -> int:  # noqa: C901 - linearer Ketten-Test
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py"), "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    client = Client(port)
    try:
        wait_ready(client, proc)

        # ---------------------------------------------------------------- #
        # 1. Runtime/Status/ Katalog kündigen die Kette an
        # ---------------------------------------------------------------- #
        _, runtime, headers = client.get("/api/runtime")
        check("runtime zero-cloud header", headers.get("X-Kaoss-Zero-Cloud") == "true", headers)
        check("runtime action endpoint", "/api/action" in runtime["endpoints"], runtime["endpoints"])
        check("runtime post routes", "/api/kaoss/xy" in runtime["post_actions"], runtime["post_actions"])
        check("runtime action chain flag", runtime["action_chain"] is True)

        _, status, _ = client.get("/api/status")
        for feature in ("action_chain", "post_actions", "dsp_chain_python", "session_state", "looper_freeze", "transport_record"):
            check(f"feature {feature}", status["features"][feature] is True, status["features"])

        _, catalogue, _ = client.get("/api/actions")
        actions = {item["action"]: item for item in catalogue["actions"]}
        check("catalogue size", len(actions) == 19, sorted(actions))
        check("catalogue ports", actions["dsp.process"]["port"] == 8084 and actions["transcribe"]["port"] == 8085, actions)
        check("catalogue script", len(catalogue["full_chain_script"]) == len(FULL_CHAIN_SCRIPT))
        check("catalogue engines", set(catalogue["engines"]) == {"orchestrator", "audio", "neurallift", "avatar", "dsp", "whisper"})

        # ---------------------------------------------------------------- #
        # 2. Reihenfolge-Guards: falsche Interaktion muss BLOCKED sein
        # ---------------------------------------------------------------- #
        reset = client.action("chain.reset")
        check("reset ok", reset["ok"] and reset["status"] == "OK", reset["status"])

        blocked = client.action("mic.arm", device_id="too-early")
        check("mic.arm blocked", blocked["status"] == "BLOCKED" and blocked["ok"] is False, blocked["detail"])
        check("mic.arm missing milestone", blocked["detail"]["missing_milestones"] == ["audio.started"], blocked["detail"])
        check("mic.arm expected before", blocked["detail"]["expected_before"] == ["audio.start"], blocked["detail"])

        for action, milestone in (
            ("dsp.process", "mic.armed"),
            ("pad.trigger", "mic.armed"),
            ("loop.capture", "transport.recording"),
            ("neurallift.generate", "avatar.mode"),
            ("session.export", "mic.armed"),
        ):
            event = client.action(action)
            check(f"{action} blocked", event["status"] == "BLOCKED", event)
            check(f"{action} missing {milestone}", milestone in event["detail"]["missing_milestones"], event["detail"])

        code, unknown, _ = client.post("/api/action", {"action": "not.a.real.action"})
        check("unknown action 400", code == 400 and unknown["ok"] is False, unknown)

        code, _, headers = client.post("/api/action", {"action": "boot"}, headers={"Origin": "http://evil.example"})
        check("cross-origin guard", code == 403, headers)
        check("zero-cloud header on guard", headers.get("X-Kaoss-Zero-Cloud") == "true")

        # ---------------------------------------------------------------- #
        # 3. Die vollständige Kette Schritt für Schritt
        # ---------------------------------------------------------------- #
        client.action("chain.reset")
        seq = 0

        def step(action: str, **params) -> dict:
            nonlocal seq
            event = client.action(action, **params)
            seq += 1
            check(f"{action} ok", event["ok"] is True and event["status"] == "OK", event.get("detail"))
            check(f"{action} seq {seq}", event["seq"] == seq, event["seq"])
            check(f"{action} latency budget", event["latency_ms"] <= STEP_BUDGET_MS, event["latency_ms"])
            return event

        event = step("input.select", input="usb_c_audio")
        check("input locked", event["detail"]["selected"] == "usb_c_audio" and event["detail"]["status"] == "LOCKED", event["detail"])
        check("input sample rate", event["detail"]["sample_rate_hz"] == 96_000, event["detail"])
        check("input engine port", event["port"] == 8080 and event["engine"] == "orchestrator", event)
        check("input persisted", event["detail"]["persisted"] == "dist/device-matrix.json")
        check("input state", event["state"]["input"]["selected"] == "usb_c_audio", event["state"]["input"])

        code, bad_input, _ = client.post("/api/action", {"action": "input.select", "input": "telepathy"})
        check("invalid input error", bad_input["status"] == "ERROR" and bad_input["ok"] is False, bad_input)
        seq += 1  # Fehler-Events gehören ebenfalls in die Kette

        event = step("permission.check")
        check("permissions pending mic", "record_audio" in event["detail"]["pending"], event["detail"])
        check("permissions usb host required", "usb_host" in event["detail"]["required"], event["detail"])
        check("permission engine", event["engine"] == "orchestrator")

        _, devices, _ = client.get("/devices/status?selected=usb_c_audio")
        mic_permission = next(item for item in devices["permissions"] if item["key"] == "record_audio")
        check("mic permission prompt state", mic_permission["granted"] is False, mic_permission)

        event = step("permission.grant", key="record_audio", granted=True)
        check("grant applied", event["detail"]["runtime_grants"]["record_audio"] is True, event["detail"])
        _, devices, _ = client.get("/devices/status?selected=usb_c_audio")
        mic_permission = next(item for item in devices["permissions"] if item["key"] == "record_audio")
        check("mic permission granted state", mic_permission["granted"] is True, mic_permission)

        event = step("audio.start", sample_rate_hz=96_000, frames_per_buffer=128)
        check("audio running", event["detail"]["running"] is True, event["detail"])
        check("audio route locked", event["detail"]["route_locked"] is True, event["detail"])
        check("audio roundtrip", abs(event["detail"]["roundtrip_ms"] - 2.4) < 1e-6, event["detail"])
        check("audio block ms", abs(event["detail"]["block_ms"] - 1.333) < 1e-3, event["detail"])
        check("audio engine port", event["port"] == 8081, event)

        event = step("mic.arm", device_id="usb-c-uac2")
        check("mic armed", event["detail"]["armed"] is True and event["detail"]["device_id"] == "usb-c-uac2", event["detail"])
        check("mic monitor safe", "safe" in event["detail"]["monitor"], event["detail"])

        event = step("preset.apply", preset="acid_berlin")
        check("preset bpm", event["detail"]["bpm"] == 128.0, event["detail"])
        check("preset step", event["detail"]["step_16_ms"] == 117.188, event["detail"])
        check("preset maps filter module", event["detail"]["kaoss"]["modules"][2]["x"] == 0.82, event["detail"]["kaoss"])
        check("preset engine dsp", event["engine"] == "dsp" and event["port"] == 8084, event)

        code, bad_preset, _ = client.post("/api/action", {"action": "preset.apply", "preset": "trance_1999"})
        check("invalid preset error", bad_preset["status"] == "ERROR", bad_preset)
        seq += 1

        event = step("kaoss.xy", module=2, x=0.82, y=0.46)
        check("xy stored", event["detail"]["x"] == 0.82 and event["detail"]["y"] == 0.46, event["detail"])
        check("xy clamped", client.action("kaoss.xy", module=3, x=4.2, y=-1.0)["detail"]["x"] == 1.0)
        seq += 1
        event = step("kaoss.freeze", module=3, frozen=True)
        check("freeze on", event["detail"]["frozen"] is True and event["detail"]["name"] == "TAPE_ECHO", event["detail"])
        held = client.action("kaoss.xy", module=3, x=0.1, y=0.1)
        seq += 1
        check("frozen module holds xy", held["detail"]["held"] is True and held["detail"]["x"] == 1.0, held["detail"])
        client.action("kaoss.freeze", module=3, frozen=False)
        seq += 1

        # DSP-Blöcke: Transient-Klassifikation, Limiter, Latenz, Determinismus
        expected = {
            "mouth_bass": "KICK808",
            "snare": "SNARE_CLAP",
            "hat": "HAT_ROLL",
            "vocal": "NONE",
        }
        checksums: dict[str, str] = {}
        for signal, kind in expected.items():
            event = step("dsp.process", signal=signal, frames=128, sample_rate_hz=96_000)
            report = event["detail"]["report"]
            check(f"dsp {signal} kind", report["transient"]["kind"] == kind, report["transient"])
            check(f"dsp {signal} latency", report["latency_ms"] <= DSP_LATENCY_BUDGET_MS, report["latency_ms"])
            check(f"dsp {signal} limiter", report["output_peak_dbfs"] <= LIMITER_DBFS + 1e-6, report["output_peak_dbfs"])
            check(f"dsp {signal} headroom", report["headroom_db"] >= -1e-6, report["headroom_db"])
            check(f"dsp {signal} engine", event["engine"] == "dsp" and event["port"] == 8084, event)
            checksums[signal] = report["checksum"]

        repeat = client.action("dsp.process", signal="mouth_bass", frames=128, sample_rate_hz=96_000)
        seq += 1
        check("dsp deterministic checksum", repeat["detail"]["report"]["checksum"] == checksums["mouth_bass"], repeat["detail"]["report"])
        check("dsp limiter safe flag", repeat["detail"]["limiter_safe"] is True, repeat["detail"])

        event = step("pad.trigger", bank="A", slot="MOUTH 808")
        check("pad A kick", event["detail"]["pad"]["transient"] == "KICK808", event["detail"]["pad"])
        check("pad A 808 voice", event["detail"]["pad"]["voice_frames"] > 0, event["detail"]["pad"])
        check("pad quantize", event["detail"]["quantize_ms"] == 117.188, event["detail"])

        event = step("pad.trigger", bank="B", slot="CLAP")
        check("pad B snare", event["detail"]["pad"]["transient"] == "SNARE_CLAP", event["detail"]["pad"])
        event = step("pad.trigger", bank="C", slot="ROLL 16")
        check("pad C hat", event["detail"]["pad"]["transient"] == "HAT_ROLL", event["detail"]["pad"])
        event = step("pad.trigger", bank="D", slot="FORMANT")
        check("pad D no drum transient", event["detail"]["pad"]["transient"] == "NONE", event["detail"]["pad"])
        check("pad D no 808 voice", event["detail"]["pad"]["voice_frames"] == 0, event["detail"]["pad"])

        bad_pad = client.action("pad.trigger", bank="Z", slot="NOPE")
        seq += 1
        check("invalid pad bank error", bad_pad["status"] == "ERROR" and bad_pad["ok"] is False, bad_pad)
        bad_slot = client.action("pad.trigger", bank="A", slot="NOT_A_SLOT")
        seq += 1
        check("invalid pad slot error", bad_slot["status"] == "ERROR", bad_slot)

        early_record = client.action("transport.record", running=True)
        seq += 1
        check("record after dsp ok", early_record["ok"] is True, early_record)
        check("record captures blocks", early_record["detail"]["blocks_captured"] >= 5, early_record["detail"])
        check("record state", early_record["state"]["transport"]["recording"] is True)

        event = step("loop.capture", subdivision=16)
        check("loop frames", event["detail"]["loop_frames"] == 45_000, event["detail"])
        check("loop ms", event["detail"]["loop_ms"] == 468.75, event["detail"])
        check("looper frozen", event["detail"]["looper"]["frozen"] is True, event["detail"])
        check("loop state", event["state"]["transport"]["loop_captured"] is True)

        frozen_a = client.action("dsp.process", signal="snare", frames=128)
        seq += 1
        frozen_b = client.action("dsp.process", signal="snare", frames=128)
        seq += 1
        check("frozen looper holds audio", frozen_a["detail"]["report"]["checksum"] == frozen_b["detail"]["report"]["checksum"],
              (frozen_a["detail"]["report"]["checksum"], frozen_b["detail"]["report"]["checksum"]))

        event = step("transcribe", text="drück und laber beton sektor dämon")
        check("transcript offline", event["detail"]["transcript"]["offline"] is True, event["detail"])
        check("transcript rhymes", "SEKTOR" in event["detail"]["rhymes"].get("beton", []), event["detail"]["rhymes"])
        check("transcript engine whisper", event["engine"] == "whisper" and event["port"] == 8085, event)

        event = step("rhyme.lookup", word="sektor")
        check("rhyme lookup", "VEKTOR" in event["detail"]["rhymes"], event["detail"])
        check("rhyme db offline", event["detail"]["db"] == "dist/offline-rhymes.sqlite3", event["detail"])

        event = step("avatar.mode", mode="SOLO_HUD")
        check("avatar solo", event["detail"]["avatars"] == 1 and event["detail"]["fps"] == 60, event["detail"])
        event = step("avatar.mode", mode="CYPHER_CIRCLE")
        check("avatar cypher", event["detail"]["avatars"] == 8 and event["detail"]["bones"] == 33, event["detail"])
        bad_mode = client.action("avatar.mode", mode="DISCO_INFERNO")
        seq += 1
        check("invalid avatar mode error", bad_mode["status"] == "ERROR", bad_mode)

        event = step("neurallift.generate", source="camera_frame_0001.jpg")
        # -- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 2, P2-2)
        # Der Dateiname leitet sich jetzt aus der SHA-256 des Meshes ab
        # (`neurallift-<16 hex>.glb`), die Kennzahlen kommen aus der Datei.
        nl = event["detail"]
        check("neurallift glb", str(nl["glb"]).startswith("neurallift-") and nl["glb"].endswith(".glb"), nl)
        check("neurallift mesh real", nl["vertices"] == 780 and nl["lod0_tris"] == 1248 and nl["rig_bones"] == 26, nl)
        check("neurallift file on disk", (ROOT / nl["glb_path"]).read_bytes()[:4] == b"glTF", nl["glb_path"])
        check("neurallift timing measured", 0 < nl["generate_ms"] < 1800.0, nl["generate_ms"])
        check("neurallift offline fallback", event["detail"]["fallback"] is True and event["detail"]["offline"] is True, event["detail"])
        check("neurallift engine", event["engine"] == "neurallift" and event["port"] == 8082, event)

        event = step("transport.record", running=False)
        check("record stopped", event["detail"]["recording"] is False, event["detail"])

        event = step("session.export")
        session = event["detail"]["session"]
        check("export format", session["format"] == ".cypher", session["format"])
        check("export chain length", session["chain_length"] >= 25, session["chain_length"])
        chain_actions = [item["action"] for item in session["action_chain"]]
        # Der Export-Event selbst wird erst nach dem Payload-Build geloggt.
        check("export chain tail", chain_actions[-1] == "transport.record", chain_actions[-3:])
        check("export chain covers journey", {
            "input.select", "permission.grant", "audio.start", "mic.arm", "preset.apply",
            "kaoss.xy", "kaoss.freeze", "dsp.process", "pad.trigger", "transport.record",
            "loop.capture", "transcribe", "rhyme.lookup", "avatar.mode", "neurallift.generate",
        } <= set(chain_actions), sorted(set(chain_actions)))
        check("export chain all ok", all(item["status"] in {"OK", "ERROR"} for item in session["action_chain"]), session["action_chain"])
        check("export stems", session["stems"] == ["vocal", "mouth_808", "kaoss_fx", "avatar_motion"], session["stems"])
        check("export pads", len(session["pads"]) == 4, session["pads"])
        check("export lyrics", session["lyrics"]["rhymes"].get("beton"), session["lyrics"])
        check("export limiter", session["limiter_dbfs"] == LIMITER_DBFS, session["limiter_dbfs"])
        check("export zero cloud", session["zero_cloud"] is True and session["created_offline"] is True)
        check("export checksum", len(session["checksum"]) == 64, session["checksum"])

        # ---------------------------------------------------------------- #
        # 4. Ketten-Äquivalenz zum Referenzmodell + Determinismus
        # ---------------------------------------------------------------- #
        expected_checksum = reference_export_checksum()
        client.action("chain.reset")
        code, run, _ = client.post("/api/chain/run", {"strict": True})
        check("chain run ok", code == 200 and run["ok"] is True, run.get("chain_run", {}).get("blocked"))
        report = run["chain_run"]
        check("chain run steps", report["steps"] == len(FULL_CHAIN_SCRIPT), report["steps"])
        check("chain run no blocked", report["blocked"] == [], report["blocked"])
        check("chain run actions", report["actions"] == [step_["action"] for step_ in FULL_CHAIN_SCRIPT], report["actions"])
        check("chain run max latency", report["chain"]["max_latency_ms"] <= STEP_BUDGET_MS, report["chain"])

        export = client.action("session.export")
        check("chain equals reference model", export["detail"]["checksum"] == expected_checksum,
              (export["detail"]["checksum"], expected_checksum))

        client.action("chain.reset")
        client.post("/api/chain/run", {"strict": True})
        export_again = client.action("session.export")
        check("chain deterministic rerun", export_again["detail"]["checksum"] == expected_checksum, export_again["detail"]["checksum"])

        # non-strict: dieselben Aktionen ohne Reihenfolge-Guard
        loose_script = [
            {"action": "dsp.process", "signal": "hat"},
            {"action": "transcribe", "text": "offline check ohne kette"},
            {"action": "session.export"},
        ]
        client.action("chain.reset")
        code, guarded, _ = client.post("/api/chain/run", {"strict": True, "script": loose_script})
        check("strict guard blocks unordered chain", code == 200 and guarded["ok"] is False, guarded["chain_run"]["blocked"])
        check("strict guard lists blocked actions", guarded["chain_run"]["blocked"] == ["dsp.process", "transcribe", "session.export"], guarded["chain_run"]["blocked"])

        client.action("chain.reset")
        code, loose, _ = client.post("/api/chain/run", {"strict": False, "script": loose_script})
        check("non strict chain allowed", code == 200 and loose["ok"] is True, loose["chain_run"]["blocked"])
        check("non strict events flagged", all(item["strict"] is False for item in loose["chain_run"]["results"]), loose["chain_run"]["results"])
        check("non strict final state", loose["chain_run"]["final_state"]["dsp"]["blocks"] == 1, loose["chain_run"]["final_state"]["dsp"])

        # ---------------------------------------------------------------- #
        # 5. Projektionen: State, Events, Logs, Ports, DSP-Report
        # ---------------------------------------------------------------- #
        client.action("chain.reset")
        client.post("/api/chain/run", {"strict": True})

        _, state, _ = client.get("/api/state")
        check("state input", state["input"]["selected"] == "usb_c_audio", state["input"])
        check("state audio", state["audio"]["running"] is True and state["audio"]["mic_armed"] is True, state["audio"])
        check("state bpm", state["bpm"] == 128.0, state["bpm"])
        check("state freeze", state["kaoss"]["modules"][0]["frozen"] is True, state["kaoss"])
        check("state dsp blocks", state["dsp"]["blocks"] >= 3, state["dsp"])
        check("state limiter safe", state["dsp"]["max_peak_dbfs"] <= LIMITER_DBFS + 1e-6, state["dsp"]["max_peak_dbfs"])
        check("state chain summary", state["chain"]["length"] >= 23 and state["chain"]["blocked"] == 0, state["chain"])
        check("state milestones", {"input.selected", "mic.armed", "dsp.processed", "transport.recording", "avatar.mode"} <= set(state["milestones"]), state["milestones"])

        _, events, _ = client.get("/api/events?since=0")
        check("events complete", events["count"] == state["chain"]["length"], (events["count"], state["chain"]["length"]))
        seqs = [item["seq"] for item in events["events"]]
        check("events strictly ordered", seqs == sorted(seqs) and len(set(seqs)) == len(seqs), seqs[:5])
        _, tail, _ = client.get(f"/api/events?since={seqs[-3]}")
        check("events incremental", tail["count"] == 2, tail["count"])

        _, logs, _ = client.get("/api/logs")
        check("logs boot line", any("DSP limiter -3.2 dBFS armed" in line for line in logs["logs"]), logs["logs"])
        check("logs chain lines", any(line.startswith("#") and "session.export" in line for line in logs["logs"]), logs["logs"][-3:])
        check("logs chain summary", any(line.startswith("CHAIN ") for line in logs["logs"]), logs["logs"][-1])

        _, ports, _ = client.get("/native-bridge/ports")
        hits = {item["port"]: item["chain_hits"] for item in ports["ports"]}
        check("ports chain hits dsp", hits[8084] >= 5, hits)
        check("ports chain hits whisper", hits[8085] >= 2, hits)
        check("ports chain hits neurallift", hits[8082] >= 1, hits)
        check("ports single app", all(item["single_app"] for item in ports["ports"]))

        _, dsp_report, _ = client.get("/api/dsp/report")
        check("dsp report blocks", dsp_report["blocks"] >= 3, dsp_report["blocks"])
        check("dsp report transient counts", dsp_report["kick808"] >= 1 and dsp_report["snare"] >= 1 and dsp_report["hat"] >= 1, dsp_report)
        check("dsp report limiter", dsp_report["max_peak_dbfs"] <= LIMITER_DBFS + 1e-6, dsp_report["max_peak_dbfs"])
        check("dsp report checksums", len(dsp_report["checksums"]) >= 1, dsp_report["checksums"])

        _, transient, _ = client.get("/dsp/transient")
        check("transient projection", transient["ok"] is True and transient["latency_ms"] <= DSP_LATENCY_BUDGET_MS, transient)
        check("transient bpm", transient["bpm"] == 128.0, transient["bpm"])

        _, session_get, _ = client.get("/session")
        check("session projection", session_get["chain_length"] >= 23 and session_get["limiter_dbfs"] == LIMITER_DBFS, session_get)

        _, export_get, _ = client.get("/api/session/export?preset=cyber_drill&input=internal_mic")
        check("export get back-compat", export_get["session"]["preset"] == "cyber_drill" and export_get["session"]["input"] == "internal_mic", export_get["session"])
        check("export get bpm", export_get["session"]["bpm"] == 142.0, export_get["session"])

        # ---------------------------------------------------------------- #
        # 6. Zero-Cloud: nur Loopback, keine externen Sockets
        # ---------------------------------------------------------------- #
        _, health, headers = client.get("/health")
        check("health chain seq", health["chain_seq"] >= 1, health)
        check("zero cloud header", headers.get("X-Kaoss-Zero-Cloud") == "true", headers)
        check("chain header", int(headers.get("X-Kaoss-Chain-Seq", "0")) >= 1, headers)
        _, allowed, _ = client.post("/api/action", {"action": "permission.check"}, headers={"Origin": f"http://127.0.0.1:{port}"})
        check("loopback origin allowed", allowed["ok"] is True, allowed)

        print(f"vollständige Aktions- und Interaktionskette verifiziert: {len(CHECKS)} Checks, "
              f"{state['chain']['length']} Ketten-Schritte, max {state['chain']['max_latency_ms']} ms, "
              f"peak {round(state['dsp']['max_peak_dbfs'], 2)} dBFS")
        return 0
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=3)
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
