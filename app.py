#!/usr/bin/env python3
"""Kaoss One App – unified offline application server.

Runs the complete currently executable Kaoss suite as one local application:
web UI, Native Bridge PortView API, Plug & Play USB/Mic/Bluetooth device matrix,
permission reporting, NeuralLift fallback, offline rhyme/transcribe API, the
deterministic DSP chain and – new – the full stateful action & interaction chain
(``engines/session_engine.py``) over GET *and* POST.

Defaults to 127.0.0.1 for zero-cloud local use; pass --host=0.0.0.0 only for
sandbox/browser preview.
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

from device_matrix import status as device_status  # noqa: E402
from dsp_chain import LIMITER_THRESHOLD_DBFS, KaossQuadChain, process_block, test_signal  # noqa: E402
from rhyme_matrix import ensure_database, lookup  # noqa: E402
from session_engine import (  # noqa: E402
    ACTION_BY_NAME,
    ACTION_CATALOGUE,
    APP_VERSION,
    ENGINES,
    FULL_CHAIN_SCRIPT,
    PRESETS,
    SAMPLE_BANKS,
    build_engine,
)

AUTO_PORT_CANDIDATES = (8080, 8086, 8088, 8090, 8099)
DAEMONS = [
    {**ENGINES["orchestrator"], "latency": "AUTO"},
    {**ENGINES["audio"], "latency": "0.4ms shim"},
    {**ENGINES["neurallift"], "latency": "1.8s fallback"},
    {**ENGINES["avatar"], "latency": "16.6ms"},
    {**ENGINES["dsp"], "latency": "<1.2ms"},
    {**ENGINES["whisper"], "latency": "<9ms shim"},
]

# POST path -> action name in the interaction chain.
POST_ROUTES = {
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
}

ENDPOINT_LIST = [
    "/api/status", "/api/runtime", "/api/state", "/api/actions", "/api/events",
    "/api/action", "/api/chain/run", "/api/chain/reset",
    "/native-bridge/ports", "/devices/status", "/devices/select", "/permissions/check",
    "/api/presets", "/api/preset/apply", "/api/kaoss/xy", "/api/kaoss/freeze",
    "/api/dsp/process", "/api/pad/trigger", "/api/transport/record", "/api/loop/capture",
    "/api/transcribe", "/api/rhymes", "/api/avatar/mode", "/api/neurallift/generate",
    "/api/session/export", "/mesh/default", "/dsp/transient", "/api/logs",
]

ENGINE = build_engine(DB_PATH)


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def selected_from_query(query: dict[str, list[str]]) -> str:
    selected = query.get("selected", [ENGINE.input])[0]
    return selected if selected in {"usb_c_audio", "internal_mic", "bluetooth_client"} else ENGINE.input


def transient_snapshot() -> dict[str, object]:
    """Live DSP report; runs one deterministic block when nothing was processed yet."""
    last = ENGINE.dsp.get("last")
    if last is None:
        chain = KaossQuadChain()
        chain.bpm = ENGINE.chain.bpm
        chain.sample_rate_hz = ENGINE.audio["sample_rate_hz"]
        last = process_block(test_signal("mouth_bass", frames=128, sample_rate_hz=chain.sample_rate_hz), chain, chain.sample_rate_hz)
    return {
        "ok": True,
        "bpm": ENGINE.chain.bpm,
        "kick808": bool(last["kick808"]),
        "snare": bool(last["snare"]),
        "hat": bool(last["hat"]),
        "latency_ms": float(last["latency_ms"]),
        "transient": last["transient"],
        "input_peak_dbfs": last["input_peak_dbfs"],
        "output_peak_dbfs": last["output_peak_dbfs"],
        "limiter_dbfs": LIMITER_THRESHOLD_DBFS,
        "frames": last["frames"],
        "sample_rate_hz": last["sample_rate_hz"],
        "checksum": last["checksum"],
        "processed_blocks": ENGINE.dsp["blocks"],
    }


class OneAppHandler(SimpleHTTPRequestHandler):
    server_version = f"KaossOneApp/{APP_VERSION}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[kaoss-one-app] {self.address_string()} {fmt % args}", flush=True)

    def end_headers(self) -> None:
        self.send_header("X-Kaoss-Zero-Cloud", "true")
        self.send_header("X-Kaoss-App", APP_VERSION)
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

    # ------------------------------------------------------------------ #
    # localhost CSRF/origin guard for state changing requests
    # ------------------------------------------------------------------ #
    def origin_allowed(self) -> bool:
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if not origin:
            return True  # native host, curl or same-document form post
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        origin_host = urlparse(origin).hostname or ""
        if origin_host == host:
            return True
        return origin_host in {"127.0.0.1", "localhost", "[::1]", "::1"}

    def read_body_params(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 4_000_000))
        if not raw:
            return {}
        content_type = (self.headers.get("Content-Type") or "").lower()
        if "application/json" in content_type or raw[:1] in {b"{", b"["}:
            try:
                parsed = json.loads(raw.decode("utf-8"))
                return parsed if isinstance(parsed, dict) else {"pcm": parsed}
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
        return {key: values[0] for key, values in parse_qs(raw.decode("utf-8", "replace")).items()}

    # ------------------------------------------------------------------ #
    # GET contract (read-only projections of the session state)
    # ------------------------------------------------------------------ #
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if path in {"/health", "/api/health"}:
            self.send_json({
                "ok": True,
                "app": "kaoss-one-app",
                "version": APP_VERSION,
                "offline": True,
                "chain_seq": ENGINE.events[-1]["seq"] if ENGINE.events else 0,
                "chain_length": len(ENGINE.events),
            })
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
                "action_chain": True,
                "post_actions": sorted(POST_ROUTES),
                "endpoints": ENDPOINT_LIST,
            })
            return

        if path in {"/api/status", "/status"}:
            self.send_json({
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
                    "action_chain": True,
                    "post_actions": True,
                    "dsp_chain_python": True,
                    "session_state": True,
                    "looper_freeze": True,
                    "transport_record": True,
                },
            })
            return

        if path in {"/api/state", "/state"}:
            self.send_json(ENGINE.state())
            return

        if path in {"/api/actions", "/actions"}:
            self.send_json({
                "ok": True,
                "actions": [spec.as_dict() for spec in ACTION_CATALOGUE],
                "engines": ENGINES,
                "full_chain_script": [dict(step) for step in FULL_CHAIN_SCRIPT],
            })
            return

        if path in {"/api/events", "/api/chain", "/events"}:
            since = int(query.get("since", ["0"])[0] or 0)
            events = ENGINE.events_since(since)
            self.send_json({
                "ok": True,
                "since": since,
                "count": len(events),
                "events": events,
                "chain": ENGINE.state()["chain"],
            })
            return

        if path == "/native-bridge/ports":
            self.send_json({"ok": True, "bridge": "kaoss-one-app", "ports": self.port_statuses()})
            return

        if path == "/session":
            state = ENGINE.state()
            self.send_json({
                "profile": state["profile"],
                "bpm": state["bpm"],
                "limiter_dbfs": state["limiter_dbfs"],
                "mode": state["mode"],
                "app": "one",
                "input": state["input"]["selected"],
                "transport": state["transport"],
                "chain_length": state["chain"]["length"],
            })
            return

        if path == "/devices/status":
            self.send_json(ENGINE.device_snapshot(selected_from_query(query)))
            return

        if path == "/devices/select":
            selected = query.get("input", [ENGINE.input])[0]
            result = ENGINE.dispatch("input.select", {"input": selected}, strict=False)
            if result["status"] == "ERROR":
                self.send_json({"ok": False, "error": result["detail"].get("error", "invalid input")}, code=400)
            else:
                self.send_json(ENGINE.device_snapshot(selected))
            return

        if path == "/permissions/check":
            result = ENGINE.dispatch("permission.check", {}, strict=False)
            self.send_json({
                "ok": True,
                "permissions": ENGINE.device_snapshot()["permissions"],
                **{key: value for key, value in result["detail"].items() if key != "error"},
                "runtime_note": "Browser prompts microphone permission; native Android declares USB/Bluetooth/audio permissions.",
            })
            return

        if path in {"/mesh/default", "/api/neurallift/default"}:
            self.send_json({
                "ok": True,
                "glb": ENGINE.avatar["glb"],
                "lod0_tris": ENGINE.avatar["lod0_tris"],
                "lod1_tris": ENGINE.avatar["lod1_tris"],
                "rig_bones": ENGINE.avatar["rig_bones"],
                "generated_from": ENGINE.avatar["generated_from"],
                "fallback": True,
            })
            return

        if path in {"/avatar/frame", "/api/avatar/frame"}:
            self.send_json({
                "ok": True,
                "fps": ENGINE.avatar["fps"],
                "avatars": ENGINE.avatar["avatars"],
                "bones": ENGINE.avatar["bones"],
                "mode": ENGINE.avatar["mode"],
            })
            return

        if path in {"/dsp/transient", "/api/dsp/transient"}:
            self.send_json(transient_snapshot())
            return

        if path in {"/dsp/report", "/api/dsp/report"}:
            last = ENGINE.dsp.get("last")
            self.send_json({
                "ok": True,
                "blocks": ENGINE.dsp["blocks"],
                "kick808": ENGINE.dsp["kick808"],
                "snare": ENGINE.dsp["snare"],
                "hat": ENGINE.dsp["hat"],
                "max_peak_dbfs": round(ENGINE.dsp["max_peak_dbfs"], 3),
                "limiter_dbfs": LIMITER_THRESHOLD_DBFS,
                "checksums": ENGINE.dsp["checksums"][-8:],
                "last": last,
            })
            return

        if path in {"/api/presets", "/presets"}:
            self.send_json({"ok": True, "presets": PRESETS, "sample_banks": SAMPLE_BANKS, "active": ENGINE.preset})
            return

        if path in {"/api/session/export", "/session/export"}:
            preset = query.get("preset", [None])[0]
            selected = query.get("input", [None])[0]
            session = ENGINE.export_payload(preset=preset, selected_input=selected)
            self.send_json({"ok": True, "session": session})
            return

        if path in {"/api/logs", "/logs"}:
            self.send_json({"ok": True, "logs": self.chain_logs()})
            return

        if path == "/transcribe":
            text = query.get("text", ["drück und laber beton sektor dämon"])[0]
            transcripts = ENGINE.lyrics["transcripts"]
            self.send_json({
                "ok": True,
                "text": text,
                "language": "de",
                "offline": True,
                "buffer_ms": 500,
                "partials": len(transcripts),
                "last": transcripts[-1] if transcripts else None,
            })
            return

        if path == "/rhymes":
            ensure_database(DB_PATH)
            word = query.get("word", ["beton"])[0]
            self.send_json({"ok": True, "word": word, "rhymes": lookup(DB_PATH, word)})
            return

        super().do_GET()

    # ------------------------------------------------------------------ #
    # POST contract: the real action & interaction chain
    # ------------------------------------------------------------------ #
    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        params = self.read_body_params()
        for key, values in query.items():
            params.setdefault(key, values[0])

        if not self.origin_allowed():
            self.send_json({"ok": False, "error": "cross-origin localhost action rejected", "zero_cloud": True}, code=403)
            return

        if path in {"/api/action", "/action"}:
            action = str(params.pop("action", ""))
            strict = bool(params.pop("strict", True))
            if action not in ACTION_BY_NAME:
                self.send_json({"ok": False, "error": f"unknown action: {action}", "known": sorted(ACTION_BY_NAME)}, code=400)
                return
            self.send_json(self.action_response(ENGINE.dispatch(action, params, strict=strict)))
            return

        if path in {"/api/chain/run", "/chain/run"}:
            script = params.get("script")
            steps = script if isinstance(script, list) else [dict(step) for step in FULL_CHAIN_SCRIPT]
            strict = bool(params.get("strict", True))
            normalized = []
            for step in steps:
                payload = dict(step)
                action = payload.pop("action", None)
                if action:
                    normalized.append({"action": action, **payload})
            report = ENGINE.run_script(normalized, strict=strict)
            self.send_json({"ok": report["ok"], "chain_run": report})
            return

        action = POST_ROUTES.get(path)
        if action is None:
            self.send_json({"ok": False, "error": f"no POST action for {path}", "routes": sorted(POST_ROUTES)}, code=404)
            return
        strict = bool(params.pop("strict", True))
        self.send_json(self.action_response(ENGINE.dispatch(action, params, strict=strict)))

    def action_response(self, result: dict[str, object]) -> dict[str, object]:
        code_status = result.get("status")
        return {
            "ok": bool(result.get("ok")),
            "action": result.get("action"),
            "seq": result.get("seq"),
            "status": code_status,
            "engine": result.get("engine"),
            "port": result.get("port"),
            "latency_ms": result.get("latency_ms"),
            "t_ms": result.get("t_ms"),
            "detail": result.get("detail"),
            "state": result.get("state"),
            "chain": (result.get("state") or {}).get("chain"),
        }

    def chain_logs(self, limit: int = 14) -> list[str]:
        logs = [
            "BOOT zero-cloud one-app",
            "PORTVIEW native bridge ready",
            "I/O matrix usb/mic/bluetooth ready",
            "DSP limiter -3.2 dBFS armed",
            "PWA WebAudio engine standby",
        ]
        for event in ENGINE.events[-limit:]:
            logs.append(
                f"#{event['seq']:>3} {event['action']:<19} {event['status']:<7} "
                f"{event['latency_ms']:>7.3f}ms :{event['port']} {event['engine']}"
            )
        state = ENGINE.state()
        logs.append(
            f"CHAIN {state['chain']['length']} steps // blocked={state['chain']['blocked']} // "
            f"max={state['chain']['max_latency_ms']}ms // peak={round(state['dsp']['max_peak_dbfs'], 2)} dBFS"
        )
        return logs

    def port_statuses(self) -> list[dict[str, object]]:
        engine_hits = {}
        for event in ENGINE.events:
            engine_hits[event["engine"]] = engine_hits.get(event["engine"], 0) + 1
        return [
            {
                **spec,
                "bind": self.server.server_address[0],
                "status": "LOCKED" if spec["port"] in {8080, 8081, 8084} else "READY",
                "single_app": True,
                "chain_hits": engine_hits.get(
                    next((name for name, meta in ENGINES.items() if meta["port"] == spec["port"]), ""), 0
                ),
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
    parser.add_argument("--run-chain", action="store_true", help="execute the full action chain once at boot (demo/preview)")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        raise SystemExit("Refusing non-local bind host for zero-cloud app")
    ensure_database(DB_PATH)
    if args.run_chain:
        report = ENGINE.run_script()
        print(f"Action chain pre-run: {report['steps']} steps ok={report['ok']} blocked={report['blocked']}", flush=True)
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    port = resolve_port(args.host, str(args.port))
    server = ThreadingHTTPServer((args.host, port), OneAppHandler)
    print(f"Kaoss One App ready: http://{args.host}:{port}/", flush=True)
    print(f"POST actions: {len(POST_ROUTES) + 2} routes // chain catalogue: {len(ACTION_CATALOGUE)} actions", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
