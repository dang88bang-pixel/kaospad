#!/usr/bin/env python3
"""Complete offline localhost IPC suite for ports 8080-8085.

This process provides executable local service contracts for the UI and CI. It is
strictly loopback-only and does not perform DNS or external network calls.
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
from device_matrix import save_selection, status as device_status  # noqa: E402

HOST = "127.0.0.1"
DAEMONS = [
    {"port": 8080, "name": "master-system-orchestrator", "protocol": "HTTP JSON", "latency": "AUTO"},
    {"port": 8081, "name": "audio-loopback-daemon", "protocol": "TCP Float32 PCM", "latency": "0.4ms shim"},
    {"port": 8082, "name": "neurallift-engine", "protocol": "HTTP GLB JSON", "latency": "1.8s fallback"},
    {"port": 8083, "name": "avatar-orchestrator", "protocol": "TCP skeleton JSONL", "latency": "16.6ms"},
    {"port": 8084, "name": "dsp-transient-bridge", "protocol": "UDP 64B JSON", "latency": "<1.2ms"},
    {"port": 8085, "name": "offline-whisper-daemon", "protocol": "HTTP UTF-8", "latency": "<9ms shim"},
]


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class JsonHandler(SimpleHTTPRequestHandler):
    server_version = "KaossLocalhostIPC/5.0.0"

    def __init__(self, *args, role: str, **kwargs):
        self.role = role
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt: str, *args: object) -> None:
        return

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
        if parsed.path == "/health":
            self.send_json({"ok": True, "service": self.role, "bind": HOST, "offline": True})
            return
        if self.role == "master-system-orchestrator":
            if parsed.path == "/native-bridge/ports":
                self.send_json({"ok": True, "bridge": "native-localhost-ipc", "ports": port_statuses()})
                return
            if parsed.path == "/session":
                self.send_json({"profile": "A", "bpm": 92.4, "limiter_dbfs": -3.2, "mode": "CYPHER"})
                return
            if parsed.path == "/devices/status":
                selected = parse_qs(parsed.query).get("selected", ["internal_mic"])[0]
                self.send_json(device_status(selected if selected in {"usb_c_audio", "internal_mic", "bluetooth_client"} else "internal_mic"))
                return
            if parsed.path == "/devices/select":
                selected = parse_qs(parsed.query).get("input", ["internal_mic"])[0]
                try:
                    self.send_json(save_selection(selected))
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, code=400)
                return
            if parsed.path == "/permissions/check":
                self.send_json({"ok": True, "permissions": device_status()["permissions"], "note": "native permissions declared; runtime mic prompt is UI/browser controlled"})
                return
        if self.role == "neurallift-engine" and parsed.path == "/mesh/default":
            self.send_json({"glb": "procedural_default_avatar.glb", "lod0_tris": 45000, "lod1_tris": 18000, "rig_bones": 24})
            return
        if self.role == "offline-whisper-daemon":
            query = parse_qs(parsed.query)
            if parsed.path == "/transcribe":
                text = query.get("text", ["drück und laber beton sektor dämon"])[0]
                self.send_json({"text": text, "language": "de", "offline": True, "buffer_ms": 500})
                return
            if parsed.path == "/rhymes":
                word = query.get("word", ["beton"])[0]
                self.send_json({"word": word, "rhymes": lookup(DB_PATH, word)})
                return
        super().do_GET()


class PCMHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data = self.request.recv(64)
        if data:
            self.request.sendall(b"PCM_FLOAT32_READY sample_rate=96000 frames=128 route=127.0.0.1:8081\n")


class AvatarHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        frame = {"fps": 60, "avatars": 8, "bones": 33, "mode": "CYPHER_CIRCLE", "offline": True}
        self.request.sendall(json_bytes(frame) + b"\n")


class UDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data, sock = self.request
        payload = {"bpm": 92.4, "kick808": True, "snare": False, "hat": True, "bytes": len(data), "offline": True}
        sock.sendto(json_bytes(payload), self.client_address)


class TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def port_statuses() -> list[dict[str, object]]:
    statuses = []
    for spec in DAEMONS:
        statuses.append({**spec, "bind": HOST, "status": "LOCKED" if spec["port"] in {8080, 8081, 8084} else "READY"})
    return statuses


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
    args = parser.parse_args()
    ensure_database(DB_PATH)
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
