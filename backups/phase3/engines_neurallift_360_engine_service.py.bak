#!/usr/bin/env python3
"""Offline NeuralLift-360 daemon stub.

The production mobile build can swap this module for accelerated MiDaS/ZoeDepth,
MediaPipe and GLB generation. This reference daemon intentionally binds only to
127.0.0.1 and never performs external network calls, so CI can validate the
zero-cloud IPC contract.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "NeuralLift360Offline/5.0.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json({"ok": True, "engine": "neurallift-360", "offline": True})
        elif self.path == "/mesh/default":
            self._json({"glb": "procedural_default_avatar.glb", "lod0_tris": 45000, "rig_bones": 24})
        else:
            self.send_error(404)

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Zero-cloud policy violation: daemon must bind localhost only")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
