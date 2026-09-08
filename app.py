#!/usr/bin/env python3
"""Kaoss One App – unified offline application server.

Runs the complete currently executable Kaoss suite as one local application:
web UI, Native Bridge PortView API, Plug & Play USB/Mic/Bluetooth device matrix,
permission reporting, NeuralLift fallback, offline rhyme/transcribe API and DSP
status contracts. Defaults to 127.0.0.1 for zero-cloud local use; pass
--host=0.0.0.0 only for sandbox/browser preview.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DB_PATH = ROOT / "dist" / "offline-rhymes.sqlite3"
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))

from device_matrix import save_selection, status as device_status  # noqa: E402
from rhyme_matrix import ensure_database, lookup  # noqa: E402

APP_VERSION = "5.0.0-offline-one-app"
AUTO_PORT_CANDIDATES = (8080, 8086, 8088, 8090, 8099)
DAEMONS = [
    {"port": 8080, "name": "master-system-orchestrator", "protocol": "HTTP JSON", "latency": "AUTO"},
    {"port": 8081, "name": "audio-loopback-daemon", "protocol": "in-app WebAudio/PCM contract", "latency": "0.4ms shim"},
    {"port": 8082, "name": "neurallift-engine", "protocol": "in-app HTTP GLB JSON", "latency": "1.8s fallback"},
    {"port": 8083, "name": "avatar-orchestrator", "protocol": "in-app skeleton JSON", "latency": "16.6ms"},
    {"port": 8084, "name": "dsp-transient-bridge", "protocol": "in-app transient JSON", "latency": "<1.2ms"},
    {"port": 8085, "name": "offline-whisper-daemon", "protocol": "in-app HTTP UTF-8", "latency": "<9ms shim"},
]

PRESETS = [
    {"id": "90s_tape", "name": "90s Tape Reel", "bpm": 92.4, "drive": 0.38, "filter": 0.62, "delay": 0.28},
    {"id": "acid_berlin", "name": "Acid Berlin", "bpm": 128.0, "drive": 0.44, "filter": 0.82, "delay": 0.18},
    {"id": "cyber_drill", "name": "Cyber Drill", "bpm": 142.0, "drive": 0.52, "filter": 0.46, "delay": 0.12},
    {"id": "lofi_cypher", "name": "Lo-Fi Cypher", "bpm": 84.0, "drive": 0.24, "filter": 0.36, "delay": 0.42},
]

SAMPLE_BANKS = [
    {"bank": "A", "label": "Kick / 808", "slots": ["SUB DROP", "BOOM", "TAPE KICK", "MOUTH 808"]},
    {"bank": "B", "label": "Snare / Clap", "slots": ["MPC SNARE", "CLAP", "RIM", "NOISE SNAP"]},
    {"bank": "C", "label": "Hat / Perc", "slots": ["TS HAT", "SHAKER", "ROLL 16", "ROLL 32"]},
    {"bank": "D", "label": "Vocal FX", "slots": ["DUB", "FORMANT", "FREEZE", "REVERSE"]},
]


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def selected_from_query(query: dict[str, list[str]]) -> str:
    selected = query.get("selected", ["internal_mic"])[0]
    return selected if selected in {"usb_c_audio", "internal_mic", "bluetooth_client"} else "internal_mic"


class OneAppHandler(SimpleHTTPRequestHandler):
    server_version = f"KaossOneApp/{APP_VERSION}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[kaoss-one-app] {self.address_string()} {fmt % args}", flush=True)

    def end_headers(self) -> None:
        self.send_header("X-Kaoss-Zero-Cloud", "true")
        self.send_header("X-Kaoss-App", APP_VERSION)
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
        path = parsed.path.rstrip("/") or "/"

        if path in {"/health", "/api/health"}:
            self.send_json({"ok": True, "app": "kaoss-one-app", "version": APP_VERSION, "offline": True})
            return

        if path in {"/api/runtime", "/runtime"}:
            host, port = self.server.server_address[:2]
            public_host = self.headers.get("Host", f"{host}:{port}")
            self.send_json({
                "ok": True,
                "app": "kaoss-one-app",
                "version": APP_VERSION,
                "bind_host": host,
                "port": int(port),
                "host_header": public_host,
                "base_url": f"http://{public_host}",
                "auto_port": True,
                "zero_cloud": True,
                "endpoints": [
                    "/api/status", "/native-bridge/ports", "/devices/status",
                    "/permissions/check", "/api/presets", "/api/session/export",
                    "/rhymes", "/mesh/default", "/dsp/transient"
                ],
            })
            return

        if path in {"/api/status", "/status"}:
            self.send_json(
                {
                    "ok": True,
                    "mode": "single-application",
                    "offline": True,
                    "zero_cloud": True,
                    "features": {
                        "web_audio_engine": True,
                        "mic_permission_prompt": True,
                        "usb_mic_bluetooth_matrix": True,
                        "native_bridge_portview": True,
                        "rhyme_matrix": True,
                        "neurallift_fallback": True,
                        "kaoss_xy_fx": True,
                        "kaoss_quad_control": True,
                        "sample_banks": True,
                        "session_export": True,
                        "live_logs": True,
                        "auto_port_runtime": True,
                    },
                }
            )
            return

        if path == "/native-bridge/ports":
            self.send_json({"ok": True, "bridge": "kaoss-one-app", "ports": self.port_statuses()})
            return

        if path == "/session":
            self.send_json({"profile": "A", "bpm": 92.4, "limiter_dbfs": -3.2, "mode": "CYPHER", "app": "one"})
            return

        if path == "/devices/status":
            self.send_json(device_status(selected_from_query(query)))
            return

        if path == "/devices/select":
            selected = query.get("input", ["internal_mic"])[0]
            try:
                self.send_json(save_selection(selected))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, code=400)
            return

        if path == "/permissions/check":
            self.send_json(
                {
                    "ok": True,
                    "permissions": device_status()["permissions"],
                    "runtime_note": "Browser prompts microphone permission; native Android declares USB/Bluetooth/audio permissions.",
                }
            )
            return

        if path in {"/mesh/default", "/api/neurallift/default"}:
            self.send_json(
                {
                    "ok": True,
                    "glb": "procedural_default_avatar.glb",
                    "lod0_tris": 45000,
                    "lod1_tris": 18000,
                    "rig_bones": 24,
                    "fallback": True,
                }
            )
            return

        if path in {"/avatar/frame", "/api/avatar/frame"}:
            self.send_json({"ok": True, "fps": 60, "avatars": 8, "bones": 33, "mode": "CYPHER_CIRCLE"})
            return

        if path in {"/dsp/transient", "/api/dsp/transient"}:
            self.send_json({"ok": True, "bpm": 92.4, "kick808": True, "snare": False, "hat": True, "latency_ms": 1.0})
            return

        if path in {"/api/presets", "/presets"}:
            self.send_json({"ok": True, "presets": PRESETS, "sample_banks": SAMPLE_BANKS})
            return

        if path in {"/api/session/export", "/session/export"}:
            preset = query.get("preset", ["90s_tape"])[0]
            selected = query.get("input", ["internal_mic"])[0]
            session = {
                "format": ".cypher",
                "version": APP_VERSION,
                "created_offline": True,
                "profile": "A",
                "preset": preset,
                "input": selected,
                "bpm": next((item["bpm"] for item in PRESETS if item["id"] == preset), 92.4),
                "limiter_dbfs": -3.2,
                "stems": ["vocal", "mouth_808", "kaoss_fx", "avatar_motion"],
                "sample_banks": SAMPLE_BANKS,
            }
            self.send_json({"ok": True, "session": session})
            return

        if path in {"/api/logs", "/logs"}:
            self.send_json({"ok": True, "logs": [
                "BOOT zero-cloud one-app",
                "PORTVIEW native bridge ready",
                "I/O matrix usb/mic/bluetooth ready",
                "DSP limiter -3.2 dBFS armed",
                "PWA WebAudio engine standby",
            ]})
            return

        if path == "/transcribe":
            text = query.get("text", ["drück und laber beton sektor dämon"])[0]
            self.send_json({"ok": True, "text": text, "language": "de", "offline": True, "buffer_ms": 500})
            return

        if path == "/rhymes":
            ensure_database(DB_PATH)
            word = query.get("word", ["beton"])[0]
            self.send_json({"ok": True, "word": word, "rhymes": lookup(DB_PATH, word)})
            return

        super().do_GET()

    def port_statuses(self) -> list[dict[str, object]]:
        return [
            {
                **spec,
                "bind": self.server.server_address[0],
                "status": "LOCKED" if spec["port"] in {8080, 8081, 8084} else "READY",
                "single_app": True,
            }
            for spec in DAEMONS
        ]



def is_port_free(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "localhost"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((probe_host, port)) != 0


def resolve_port(host: str, requested: str) -> int:
    if requested not in {"auto", "0"}:
        return int(requested)
    for port in AUTO_PORT_CANDIDATES:
        if is_port_free(host, port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="auto", help="numeric port, 0, or auto")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        raise SystemExit("Refusing non-local bind host for zero-cloud app")
    ensure_database(DB_PATH)
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    port = resolve_port(args.host, str(args.port))
    server = ThreadingHTTPServer((args.host, port), OneAppHandler)
    print(f"Kaoss One App ready: http://{args.host}:{port}/", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
