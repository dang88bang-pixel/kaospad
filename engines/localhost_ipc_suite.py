#!/usr/bin/env python3
"""Complete offline localhost IPC suite for ports 8080-8085.

This process provides executable local service contracts for the UI and CI. It is
strictly loopback-only and does not perform DNS or external network calls.

Seit der Aktionsketten-Erweiterung teilen sich alle Daemons *eine* Session-Engine
(``engines/session_engine.py``): Jede Aktion wird über den Daemon abgewickelt, der
sie im Produktionsaufbau besitzt – Orchestrator (8080) für State/Route/Transport,
NeuralLift (8082) für GLB, Avatar (8083) für die Skeleton-Matrix, DSP-Bridge (8084)
für Audio-Blöcke und Whisper (8085) für Transkript/Reime. Damit ist die komplette
Aktions- und Interaktionskette sowohl in der One App (``app.py``) als auch im
Multi-Daemon-Modus identisch adressierbar.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import signal
import socket
import socketserver
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
DB_PATH = ROOT / "dist" / "offline-rhymes.sqlite3"
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))
from rhyme_matrix import ensure_database, lookup  # noqa: E402
sys.path.insert(0, str(ROOT / "engines"))
from device_matrix import status as device_status  # noqa: E402
from session_engine import ACTION_BY_NAME, FULL_CHAIN_SCRIPT, build_engine  # noqa: E402

HOST = "127.0.0.1"
DAEMONS = [
    {"port": 8080, "name": "master-system-orchestrator", "protocol": "HTTP JSON", "latency": "AUTO"},
    {"port": 8081, "name": "audio-loopback-daemon", "protocol": "TCP Float32 PCM", "latency": "0.4ms shim"},
    {"port": 8082, "name": "neurallift-engine", "protocol": "HTTP GLB JSON", "latency": "1.8s fallback"},
    {"port": 8083, "name": "avatar-orchestrator", "protocol": "TCP skeleton JSONL", "latency": "16.6ms"},
    {"port": 8084, "name": "dsp-transient-bridge", "protocol": "UDP 64B JSON", "latency": "<1.2ms"},
    {"port": 8085, "name": "offline-whisper-daemon", "protocol": "HTTP UTF-8", "latency": "<9ms shim"},
]

# Welche Aktionen pro Daemon-Rolle ausführbar sind (Produktions-Mapping).
ROLE_ACTIONS = {
    "master-system-orchestrator": frozenset(ACTION_BY_NAME),
    "neurallift-engine": frozenset({"neurallift.generate"}),
    "offline-whisper-daemon": frozenset({"transcribe", "rhyme.lookup"}),
}

ENGINE = build_engine(DB_PATH)
# Phase 3/5: IPC binding
try:
    from ipc_binding import call_with_retry  # type: ignore
    HAS_BINDING = True
except ImportError:
    HAS_BINDING = False
    def call_with_retry(key, func, timeout_ms=5000, attempts=3, base_delay_ms=20):
        try:
            return func()
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}

def _dispatch_bound(action, params, strict=True):
    def _call():
        return ENGINE.dispatch(action, params, strict=strict)
    if HAS_BINDING:
        return call_with_retry(f"ipc:{action}", _call, timeout_ms=5000, attempts=3)
    return _call()



def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def action_response(result: dict[str, object]) -> dict[str, object]:
    return {
        "ok": bool(result.get("ok")),
        "action": result.get("action"),
        "seq": result.get("seq"),
        "status": result.get("status"),
        "engine": result.get("engine"),
        "port": result.get("port"),
        "latency_ms": result.get("latency_ms"),
        "t_ms": result.get("t_ms"),
        "detail": result.get("detail"),
        "state": result.get("state"),
        "chain": (result.get("state") or {}).get("chain"),
    }


class JsonHandler(SimpleHTTPRequestHandler):
    server_version = "KaossLocalhostIPC/5.0.0"

    def __init__(self, *args, role: str, **kwargs):
        self.role = role
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("X-Kaoss-Zero-Cloud", "true")
        self.send_header("X-Kaoss-Chain-Seq", str(ENGINE.events[-1]["seq"] if ENGINE.events else 0))
        super().end_headers()

    def send_json(self, payload: object, code: int = 200) -> None:
        body = json_bytes(payload)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/health":
            self.send_json({
                "ok": True,
                "service": self.role,
                "bind": HOST,
                "offline": True,
                "chain_length": len(ENGINE.events),
            })
            return
        if parsed.path in {"/api/state", "/state"}:
            self.send_json(ENGINE.state())
            return
        if parsed.path in {"/api/events", "/events"}:
            since = int(query.get("since", ["0"])[0] or 0)
            self.send_json({"ok": True, "since": since, "events": ENGINE.events_since(since), "chain": ENGINE.state()["chain"]})
            return
        if parsed.path in {"/api/actions", "/actions"}:
            allowed = sorted(ROLE_ACTIONS.get(self.role, frozenset()))
            self.send_json({
                "ok": True,
                "service": self.role,
                "allowed_actions": allowed,
                "actions": [spec.as_dict() for spec in ACTION_BY_NAME.values() if spec.action in allowed],
                "full_chain_script": [dict(step) for step in FULL_CHAIN_SCRIPT],
            })
            return
        if self.role == "master-system-orchestrator":
            if parsed.path == "/native-bridge/ports":
                self.send_json({"ok": True, "bridge": "native-localhost-ipc", "ports": port_statuses()})
                return
            if parsed.path == "/session":
                state = ENGINE.state()
                self.send_json({
                    "profile": state["profile"],
                    "bpm": state["bpm"],
                    "limiter_dbfs": state["limiter_dbfs"],
                    "mode": state["mode"],
                    "chain_length": state["chain"]["length"],
                })
                return
            if parsed.path == "/devices/status":
                selected = query.get("selected", [ENGINE.input])[0]
                self.send_json(ENGINE.device_snapshot(selected if selected in {"usb_c_audio", "internal_mic", "bluetooth_client"} else ENGINE.input))
                return
            if parsed.path == "/devices/select":
                selected = query.get("input", [ENGINE.input])[0]
                result = ENGINE.dispatch("input.select", {"input": selected}, strict=False)
                if result["status"] == "ERROR":
                    self.send_json({"ok": False, "error": result["detail"].get("error", "invalid input")}, code=400)
                else:
                    self.send_json(ENGINE.device_snapshot(selected))
                return
            if parsed.path == "/permissions/check":
                result = ENGINE.dispatch("permission.check", {}, strict=False)
                self.send_json({
                    "ok": True,
                    "permissions": ENGINE.device_snapshot()["permissions"],
                    **{key: value for key, value in result["detail"].items() if key != "error"},
                    "note": "native permissions declared; runtime mic prompt is UI/browser controlled",
                })
                return
            if parsed.path in {"/api/session/export", "/session/export"}:
                self.send_json({
                    "ok": True,
                    "session": ENGINE.export_payload(
                        preset=query.get("preset", [None])[0],
                        selected_input=query.get("input", [None])[0],
                    ),
                })
                return
        if self.role == "neurallift-engine" and parsed.path == "/mesh/default":
            self.send_json({
                "glb": ENGINE.avatar["glb"],
                "lod0_tris": ENGINE.avatar["lod0_tris"],
                "lod1_tris": ENGINE.avatar["lod1_tris"],
                "rig_bones": ENGINE.avatar["rig_bones"],
                "generated_from": ENGINE.avatar["generated_from"],
            })
            return
        if self.role == "offline-whisper-daemon":
            if parsed.path == "/transcribe":
                text = query.get("text", ["drück und laber beton sektor dämon"])[0]
                self.send_json({"text": text, "language": "de", "offline": True, "buffer_ms": 500})
                return
            if parsed.path == "/rhymes":
                word = query.get("word", ["beton"])[0]
                self.send_json({"word": word, "rhymes": lookup(DB_PATH, word)})
                return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 4_000_000)) if length > 0 else b""
        try:
            params = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            params = {}
        if not isinstance(params, dict):
            params = {"pcm": params}
        params.update({key: values[0] for key, values in parse_qs(parsed.query).items()})

        allowed = ROLE_ACTIONS.get(self.role, frozenset())
        if parsed.path in {"/api/chain/run", "/chain/run"} and self.role == "master-system-orchestrator":
            script = params.get("script") or [dict(step) for step in FULL_CHAIN_SCRIPT]
            report = ENGINE.run_script(script, strict=bool(params.get("strict", True)))
            self.send_json({"ok": report["ok"], "chain_run": report})
            return

        declared = str(params.pop("action", ""))
        if parsed.path in {"/api/action", "/action"}:
            action = declared
        else:
            action = declared or ACTION_BY_PATH.get(parsed.path.rstrip("/"), "")
        if not action or action not in ACTION_BY_NAME:
            self.send_json({"ok": False, "error": f"unknown action for {parsed.path}", "allowed_actions": sorted(allowed)}, code=400)
            return
        if action not in allowed:
            self.send_json({
                "ok": False,
                "error": f"action '{action}' is not served by {self.role}",
                "serve_on_port": ACTION_BY_NAME[action].as_dict()["port"],
                "allowed_actions": sorted(allowed),
            }, code=403)
            return
        strict = bool(params.pop("strict", True))
        self.send_json(action_response(_dispatch_bound(action, params, strict=strict)))


ACTION_BY_PATH = {path: action for path, action in {
    "/api/input/select": "input.select",
    "/api/permission/check": "permission.check",
    "/api/permission/grant": "permission.grant",
    "/api/audio/start": "audio.start",
    "/api/mic/arm": "mic.arm",
    "/api/preset/apply": "preset.apply",
    "/api/kaoss/xy": "kaoss.xy",
    "/api/kaoss/freeze": "kaoss.freeze",
    "/api/dsp/process": "dsp.process",
    "/api/pad/trigger": "pad.trigger",
    "/api/transport/record": "transport.record",
    "/api/loop/capture": "loop.capture",
    "/api/transcribe": "transcribe",
    "/api/rhymes": "rhyme.lookup",
    "/api/avatar/mode": "avatar.mode",
    "/api/neurallift/generate": "neurallift.generate",
    "/api/session/export": "session.export",
    "/api/chain/reset": "chain.reset",
}.items()}


class PCMHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data = self.request.recv(64)
        if data:
            state = ENGINE.audio
            self.request.sendall(
                f"PCM_FLOAT32_READY sample_rate={int(state['sample_rate_hz'])} "
                f"frames={state['frames_per_buffer']} roundtrip_ms={state['roundtrip_ms']} "
                f"route=127.0.0.1:8081\n".encode("utf-8")
            )


class AvatarHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        avatar = ENGINE.avatar
        frame = {
            "fps": avatar["fps"],
            "avatars": avatar["avatars"],
            "bones": avatar["bones"],
            "mode": avatar["mode"],
            "offline": True,
            "chain_seq": ENGINE.events[-1]["seq"] if ENGINE.events else 0,
        }
        self.request.sendall(json_bytes(frame) + b"\n")


class UDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data, sock = self.request
        # Jeder UDP-Ping fährt einen echten DSP-Block durch die Kette.
        signal = data.decode("utf-8", "replace").strip().lower() or "mouth_bass"
        if signal not in {"mouth_bass", "snare", "hat", "vocal", "silence", "transient"}:
            signal = "mouth_bass"
        if signal == "transient":
            signal = "mouth_bass"
        result = _dispatch_bound("dsp.process", {"signal": signal, "frames": 128}, strict=False) if HAS_BINDING else ENGINE.dispatch("dsp.process", {"signal": signal, "frames": 128}, strict=False)
        report = (result.get("detail") or {}).get("report") or {}
        payload = {
            "bpm": ENGINE.chain.bpm,
            "kick808": bool(report.get("kick808")),
            "snare": bool(report.get("snare")),
            "hat": bool(report.get("hat")),
            "transient": (report.get("transient") or {}).get("kind", "NONE"),
            "latency_ms": report.get("latency_ms", 1.2),
            "output_peak_dbfs": report.get("output_peak_dbfs", -3.2),
            "bytes": len(data),
            "offline": True,
        }
        sock.sendto(json_bytes(payload), self.client_address)


class TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def port_statuses() -> list[dict[str, object]]:
    hits: dict[str, int] = {}
    for event in ENGINE.events:
        hits[event["engine"]] = hits.get(event["engine"], 0) + 1
    statuses = []
    for spec in DAEMONS:
        engine_name = next((name for name, meta in _ENGINE_PORTS.items() if meta == spec["port"]), "")
        statuses.append({
            **spec,
            "bind": HOST,
            "status": "LOCKED" if spec["port"] in {8080, 8081, 8084} else "READY",
            "chain_hits": hits.get(engine_name, 0),
        })
    return statuses


_ENGINE_PORTS = {
    "orchestrator": 8080,
    "audio": 8081,
    "neurallift": 8082,
    "avatar": 8083,
    "dsp": 8084,
    "whisper": 8085,
}


def start_http(port: int, role: str):
    handler = partial(JsonHandler, role=role)
    server = ThreadingHTTPServer((HOST, port), handler)
    thread = threading.Thread(target=server.serve_forever, name=role, daemon=True)
    thread.start()
    return server


def start_tcp(port: int, handler_cls):
    server = TCPServer((HOST, port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, name=f"tcp-{port}", daemon=True)
    thread.start()
    return server


def start_udp(port: int):
    server = UDPServer((HOST, port), UDPHandler)
    thread = threading.Thread(target=server.serve_forever, name=f"udp-{port}", daemon=True)
    thread.start()
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=0.0, help="seconds to run; 0 means forever")
    parser.add_argument("--run-chain", action="store_true", help="execute the full action chain once at boot")
    args = parser.parse_args()
    ensure_database(DB_PATH)
    if args.run_chain:
        report = ENGINE.run_script()
        print(f"Action chain pre-run: {report['steps']} steps ok={report['ok']}", flush=True)
    servers = [
        start_http(8080, "master-system-orchestrator"),
        start_tcp(8081, PCMHandler),
        start_http(8082, "neurallift-engine"),
        start_tcp(8083, AvatarHandler),
        start_udp(8084),
        start_http(8085, "offline-whisper-daemon"),
    ]
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    print("Kaoss localhost IPC suite ready on 127.0.0.1:8080-8085", flush=True)
    print(f"Shared session engine: {len(ACTION_BY_NAME)} actions // chain script {len(FULL_CHAIN_SCRIPT)} steps", flush=True)
    deadline = time.time() + args.duration if args.duration > 0 else None
    try:
        while not stop.is_set() and (deadline is None or time.time() < deadline):
            time.sleep(0.1)
    finally:
        # Threads are daemonized; close listening sockets immediately so tests and
        # short validation runs can exit without waiting on serve_forever joins.
        for server in servers:
            with contextlib.suppress(Exception):
                server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
