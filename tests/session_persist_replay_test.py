#!/usr/bin/env python3
"""Ketten-Persistenz über App-Neustarts + Ketten-Replay aus ``.cypher``.

Ablauf:

1. Kette laufen lassen, ``.cypher`` in ``dist/sessions/`` persistieren.
2. **Neuer Prozess** (echter Neustart des One-App-Servers): State muss aus dem
   Store wiederhergestellt sein (Preset/BPM, Input, Mic, DSP-Counter, Kaoss-XY),
   ``/api/session/latest`` liefert die persistierte Kette inklusive Parametern.
3. Replay über ``POST /api/session/replay``: Re-Import *mit* Parametern und
   erneute Ausführung -> identischer Export-Checksum (``checksum_match``).
4. Alt-Exporte ohne ``params`` laufen weiterhin (nur Aktionsnamen).
5. Leerer Store -> ``/api/session/latest`` antwortet 404 statt zu raten.
"""
from __future__ import annotations

import json
import shutil
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
sys.path.insert(0, str(ROOT / "engines" / "neurallift_360"))
sys.path.insert(0, str(ROOT / "engines" / "mopac_dance_learner"))

from session_engine import FULL_CHAIN_SCRIPT, SESSION_STORE, build_engine  # noqa: E402

CHECKS: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    assert condition, f"FAIL {label}: {detail}"
    CHECKS.append(label)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(port: int, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:  # noqa: S310 local only
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


class Server:
    def __init__(self, *extra: str) -> None:
        self.port = free_port()
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "app.py"), "--host", "127.0.0.1", "--port", str(self.port), *extra],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"server died: {self.proc.stderr.read()[:600]}")
            try:
                code, body = request(self.port, "GET", "/health")
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.1)
                continue
            if code == 200 and body.get("ok"):
                return
            time.sleep(0.1)
        raise AssertionError("server not ready")

    def get(self, path: str) -> tuple[int, dict]:
        return request(self.port, "GET", path)

    def post(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        return request(self.port, "POST", path, payload or {})

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main() -> int:  # noqa: C901 - linearer Persistenz-Test
    # ------------------------------------------------------------------ #
    # 1. Kette + Persistenz im Prozess
    # ------------------------------------------------------------------ #
    engine = build_engine(restore=False)
    engine.dispatch("chain.reset")
    report = engine.run_script(FULL_CHAIN_SCRIPT, strict=True)
    check("chain ok", report["ok"] and report["blocked"] == [], report["blocked"])
    payload = engine.export_payload()
    path = engine.persist_session(payload)
    check("persist file written", path.is_file() and path.suffix == ".json", path)
    check("persist in store", path.parent == SESSION_STORE, path)
    loaded = engine.load_session(path)
    check("persist checksum stable", loaded["checksum"] == payload["checksum"], (loaded["checksum"], payload["checksum"]))
    check("params recorded", loaded["params_recorded"] >= 15, loaded["params_recorded"])
    check("latest written", (SESSION_STORE / "latest.cypher.json").is_file())
    params_by_action: dict[str, list[dict]] = {}
    for event in loaded["action_chain"]:
        params_by_action.setdefault(event["action"], []).append(event.get("params") or {})
    check("preset param recorded", params_by_action.get("preset.apply", [{}])[0].get("preset") == "acid_berlin", params_by_action.get("preset.apply"))
    check("kaoss params recorded", [item.get("x") for item in params_by_action.get("kaoss.xy", [])] == [0.82, 0.35], params_by_action.get("kaoss.xy"))
    check("input param recorded", params_by_action.get("input.select", [{}])[0].get("input") == "usb_c_audio", params_by_action.get("input.select"))
    check("dsp signal recorded", [item.get("signal") for item in params_by_action.get("dsp.process", [])] == ["mouth_bass", "snare", "hat"], params_by_action.get("dsp.process"))

    inventory = engine.list_sessions()
    check("store inventory", any(row["latest"] for row in inventory) and len(inventory) >= 2, [row["file"] for row in inventory])

    # ------------------------------------------------------------------ #
    # 2. Neustart: neuer Server-Prozess stellt die Kette wieder her
    # ------------------------------------------------------------------ #
    server = Server()
    try:
        code, latest = server.get("/api/session/latest")
        check("latest 200", code == 200 and latest["ok"] is True, latest.get("error"))
        check("latest checksum", latest["session"]["checksum"] == payload["checksum"], latest["session"]["checksum"])
        check("latest restored flag", latest["restored"]["ok"] is True, latest["restored"])
        check("latest restored source", latest["restored"]["source"].endswith("latest.cypher.json"), latest["restored"]["source"])
        check("latest chain length", latest["session"]["chain_length"] == payload["chain_length"], latest["session"]["chain_length"])
        check("latest params in chain", latest["session"]["params_recorded"] >= 15, latest["session"]["params_recorded"])
        check("store listed", any(row["latest"] for row in latest["sessions"]), latest["sessions"])

        _, state = server.get("/api/state")
        check("restart starts deterministic", state["bpm"] == 92.4, state["bpm"])
        check("restart fresh pads", state["pads"] == [], state["pads"])
        check("restart fresh dsp", state["dsp"]["blocks"] == 0, state["dsp"]["blocks"])
        check("restart event log fresh", state["chain"]["length"] == 1, state["chain"])
        check("restart restored summary", state["restored"]["ok"] is True, state["restored"])
        check("restart summary preset", state["restored"]["preset"] == "acid_berlin", state["restored"])
        check("restart summary bpm", state["restored"]["bpm"] == 128.0, state["restored"])
        check("restart summary chain", state["restored"]["chain_length"] == payload["chain_length"], state["restored"])
        check("restart summary params", state["restored"]["params_recorded"] >= 15, state["restored"])
        check("restart summary dsp", state["restored"]["dsp_blocks"] == payload["dsp"]["blocks"], state["restored"])
        check("restart summary not imported", state["restored"].get("imported") is not True, state["restored"])
        check("restart summary actions", state["restored"]["actions"][:3] == ["boot", "input.select", "permission.check"], state["restored"]["actions"][:3])

        # Reihenfolge-Guards bleiben nach dem Neustart scharf (keine geliehene Arming).
        code, blocked = server.post("/api/action", {"action": "dsp.process", "signal": "mouth_bass"})
        check("guard still strict after restart", blocked["status"] == "BLOCKED", blocked)

        # Expliziter Import der persistierten Sitzung in den Live-State.
        code, restored = server.post("/api/session/restore", {})
        check("restore 200", code == 200 and restored["ok"] is True, restored)
        check("restore imported flag", restored["restored"]["imported"] is True, restored["restored"])
        check("restore fields", set(restored["restored"]["fields"]) >= {"preset", "kaoss", "audio", "pads"}, restored["restored"]["fields"])
        after = restored["state"]
        check("restore preset bpm", after["bpm"] == 128.0, after["bpm"])
        check("restore input", after["input"]["selected"] == "usb_c_audio", after["input"])
        check("restore kaoss xy", after["kaoss"]["modules"][2]["x"] == 0.82, after["kaoss"]["modules"][2])
        check("restore freeze", after["kaoss"]["modules"][0]["frozen"] is True, after["kaoss"]["modules"][0])
        check("restore pads", len(after["pads"]) == len(payload["pads"]) == 2, (len(after["pads"]), len(payload["pads"])))
        check("restore dsp counters", after["dsp"]["blocks"] == payload["dsp"]["blocks"], after["dsp"]["blocks"])
        check("restore lyrics", bool(after["lyrics"]["transcripts"]), after["lyrics"])
        check("restore avatar glb", after["avatar"]["glb"], after["avatar"])
        check("restore audio flags", after["audio"]["mic_armed"] is True and after["audio"]["running"] is True, after["audio"])
        check("restore keeps guards", "mic.armed" not in after["milestones"], after["milestones"])

        # ------------------------------------------------------------------ #
        # 3. Replay über HTTP (Re-Import + erneute Ausführung mit Parametern)
        # ------------------------------------------------------------------ #
        code, replay = server.post("/api/session/replay", {"path": "dist/sessions/latest.cypher.json"})
        check("replay 200", code == 200 and replay["ok"] is True, replay)
        body = replay["replay"]
        check("replay params restored", body["params_restored"] is True, body["params_events"])
        check("replay steps", body["steps"] == payload["chain_length"], (body["steps"], payload["chain_length"]))
        check("replay checksum match", body["checksum_match"] is True, (body["replay_checksum"], body["source"]["checksum"]))
        check("replay no blocked", body["blocked"] == [], body["blocked"])
        check("replay drift lengths", body["drift"]["chain_length"]["expected"] == body["drift"]["chain_length"]["replayed"], body["drift"])
        check("replay actions", body["actions"] == [event["action"] for event in payload["action_chain"]], body["actions"][:5])

        _, replayed_state = server.get("/api/state")
        check("replay re-armed chain", "mic.armed" in replayed_state["milestones"], replayed_state["milestones"])
        check("replay restored bpm", replayed_state["bpm"] == 128.0, replayed_state["bpm"])
        check("replay restored xy", replayed_state["kaoss"]["modules"][2]["x"] == 0.82, replayed_state["kaoss"]["modules"][2])
        check("replay restored pads", len(replayed_state["pads"]) == len(payload["pads"]), (len(replayed_state["pads"]), len(payload["pads"])))

        # Replay per Inline-Payload (ohne Datei) und per Default (letzte Sitzung)
        code, inline = server.post("/api/session/replay", {"session": payload})
        check("replay inline", code == 200 and inline["ok"] is True and inline["source"] == "inline", inline.get("error"))
        check("replay inline checksum", inline["replay"]["checksum_match"] is True, inline["replay"]["replay_checksum"])
        code, default = server.post("/api/session/replay", {})
        check("replay default latest", code == 200 and default["ok"] is True and default["source"].endswith("latest.cypher.json"), default)

        # Alt-Format ohne params: läuft, weist sich aber ehrlich aus.
        legacy = json.loads(json.dumps(payload))
        for event in legacy["action_chain"]:
            event.pop("params", None)
        code, legacy_replay = server.post("/api/session/replay", {"session": legacy})
        check("legacy replay ok", code == 200 and legacy_replay["ok"] is True, legacy_replay)
        check("legacy replay flagged", legacy_replay["replay"]["params_restored"] is False, legacy_replay["replay"])

        # Fehlerpfad: unbekannte Datei
        code, missing = server.post("/api/session/replay", {"path": "dist/sessions/does-not-exist.json"})
        check("replay missing file 200 with error", code == 200 and missing["ok"] is False, missing)
        check("replay path guard", request(server.port, "POST", "/api/session/replay", {"path": "../../etc/passwd"})[1]["ok"] is False)
    finally:
        server.close()

    # ------------------------------------------------------------------ #
    # 4. Neustart ohne Restore-Flag bleibt sauber
    # ------------------------------------------------------------------ #
    plain = Server("--no-restore")
    try:
        _, state = plain.get("/api/state")
        check("no-restore default preset", state["bpm"] == 92.4, state["bpm"])
        check("no-restore flag", state["restored"]["ok"] is False, state["restored"])
        check("no-restore reason", "disabled" in state["restored"]["reason"], state["restored"])
    finally:
        plain.close()

    # ------------------------------------------------------------------ #
    # 4b. --restore importiert die Sitzung direkt beim Boot
    # ------------------------------------------------------------------ #
    auto = Server("--restore")
    try:
        # Erwartet wird, was zu diesem Zeitpunkt wirklich im Store liegt
        # (der letzte Replay hat möglicherweise ein anderes Preset persistiert).
        _, stored = auto.get("/api/session/latest")
        _, state = auto.get("/api/state")
        check("--restore imports bpm", state["bpm"] == stored["session"]["bpm"], (state["bpm"], stored["session"]["bpm"]))
        check("--restore imports input", state["input"]["selected"] == stored["session"]["input"], state["input"])
        check("--restore imported flag", state["restored"].get("imported") is True, state["restored"])
        check("--restore same checksum", state["restored"]["checksum"] == stored["session"]["checksum"], state["restored"]["checksum"])
    finally:
        auto.close()

    # ------------------------------------------------------------------ #
    # 5. Leerer Store -> 404 statt geratenem Zustand
    # ------------------------------------------------------------------ #
    backup = SESSION_STORE.parent / f"sessions.backup-{Path(path).stat().st_mtime_ns}"
    moved = False
    if SESSION_STORE.is_dir():
        shutil.move(str(SESSION_STORE), str(backup))
        moved = True
    empty = Server()
    try:
        code, body = empty.get("/api/session/latest")
        check("empty store 404", code == 404 and body["ok"] is False, (code, body))
        check("empty store sessions", body["sessions"] == [], body["sessions"])
    finally:
        empty.close()
        if moved:
            if SESSION_STORE.is_dir():
                shutil.rmtree(SESSION_STORE)
            shutil.move(str(backup), str(SESSION_STORE))

    print(
        f"session persist + replay ok: {len(CHECKS)} checks // store={SESSION_STORE.relative_to(ROOT)} "
        f"checksum={payload['checksum'][:12]} chain={payload['chain_length']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
