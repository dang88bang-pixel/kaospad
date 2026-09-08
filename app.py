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
DAEMONS = [
    {"port": 8080, "name": "master-system-orchestrator", "protocol": "HTTP JSON", "latency": "AUTO"},
    {"port": 8081, "name": "audio-loopback-daemon", "protocol": "in-app WebAudio/PCM contract", "latency": "0.4ms shim"},
    {"port": 8082, "name": "neurallift-engine", "protocol": "in-app HTTP GLB JSON", "latency": "1.8s fallback"},
    {"port": 8083, "name": "avatar-orchestrator", "protocol": "in-app skeleton JSON", "latency": "16.6ms"},
    {"port": 8084, "name": "dsp-transient-bridge", "protocol": "in-app transient JSON", "latency": "<1.2ms"},
    {"port": 8085, "name": "offline-whisper-daemon", "protocol": "in-app HTTP UTF-8", "latency": "<9ms shim"},
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        raise SystemExit("Refusing non-local bind host for zero-cloud app")
    ensure_database(DB_PATH)
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    server = ThreadingHTTPServer((args.host, args.port), OneAppHandler)
    print(f"Kaoss One App ready: http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
