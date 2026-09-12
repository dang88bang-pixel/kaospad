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
import select
import socket
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DB_PATH = ROOT / "dist" / "offline-rhymes.sqlite3"
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))
sys.path.insert(0, str(ROOT / "engines" / "neurallift_360"))

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
    SESSION_STORE,
    build_engine,
)

WASM_DIR = ROOT / "dist" / "wasm"
WASM_MODULE = WASM_DIR / "kaoss_dsp.wasm"


def wasm_status() -> dict[str, object]:
    """Status des C++-DSP-Kerns als WebAssembly (``make wasm``)."""
    built = WASM_MODULE.is_file()
    manifest_path = WASM_DIR / "build-manifest.json"
    manifest: dict[str, object] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    return {
        "ok": True,
        "built": built,
        "module": str(WASM_MODULE.relative_to(ROOT)) if built else "",
        "url": "/wasm/kaoss_dsp.wasm" if built else "",
        "bytes": WASM_MODULE.stat().st_size if built else 0,
        "core": "cpp kaoss_dsp (audio_flinger_hook + dsp_transient_splitter + kaoss_quad_engine)",
        "parity": "browser == native == python mirror",
        "build": manifest,
        "offline": True,
    }


AUTO_PORT_CANDIDATES = (8080, 8086, 8088, 8090, 8099)
DAEMONS = [
    {**ENGINES["orchestrator"], "latency": "AUTO", "task": "session/orchestrate"},
    {**ENGINES["audio"], "latency": "<1.2ms", "task": "audio.start/mic.arm"},
    {**ENGINES["neurallift"], "latency": "1.8s", "task": "neurallift.generate"},
    {**ENGINES["avatar"], "latency": "16.6ms", "task": "avatar.mode"},
    {**ENGINES["dsp"], "latency": "<1.2ms", "task": "dsp.process/kaoss/pad"},
    {**ENGINES["whisper"], "latency": "<9ms", "task": "transcribe/rhyme.lookup"},
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
    "/api/status", "/api/runtime", "/api/state", "/api/actions", "/api/events", "/api/events/stream",
    "/api/action", "/api/chain/run", "/api/chain/reset",
    "/native-bridge/ports", "/native-bridge/load", "/devices/status", "/devices/select", "/permissions/check",
    "/api/presets", "/api/preset/apply", "/api/kaoss/xy", "/api/kaoss/freeze",
    "/api/dsp/process", "/api/pad/trigger", "/api/transport/record", "/api/loop/capture",
    "/api/transcribe", "/api/rhymes", "/api/avatar/mode", "/api/neurallift/generate",
    "/api/session/export", "/api/session/latest", "/api/session/restore", "/api/session/replay", "/api/sessions",
    "/api/audio/capture", "/wasm/kaoss_dsp.wasm",
    "/mesh/default", "/dsp/transient", "/api/logs",
]

ENGINE = build_engine(DB_PATH)
# Native-Bridge: welcher Engine-Port zuletzt zur Aktion geladen wurde.
BRIDGE_LOADED: dict[int, dict[str, object]] = {}
BRIDGE_ACTIVE_PORT: int | None = None


def load_native_port_for_action(action: str) -> dict[str, object] | None:
    spec = ACTION_BY_NAME.get(action)
    if spec is None:
        return None
    global BRIDGE_ACTIVE_PORT
    port = int(ENGINES[spec.engine]["port"])
    payload = {
        "ok": True,
        "action": action,
        "engine": spec.engine,
        "port": port,
        "bind": "127.0.0.1",
        "status": "LOADED",
        "native_bridge": True,
        "task": spec.summary,
    }
    BRIDGE_LOADED[port] = payload
    BRIDGE_ACTIVE_PORT = port
    return payload


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
    # Server-Sent Events: echte Push-Kette zusätzlich zum Polling
    # ------------------------------------------------------------------ #
    def sse_write(self, event: str, payload: object, event_id: str | None = None) -> None:
        lines = []
        if event_id is not None:
            lines.append(f"id: {event_id}")
        if event:
            lines.append(f"event: {event}")
        lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
        self.wfile.write(("\n".join(lines) + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def stream_events(self, query: dict[str, list[str]]) -> None:
        """Hält die Verbindung offen und pusht jedes Ketten-Event sofort."""
        since = int(query.get("since", ["0"])[0] or 0)
        last_event_id = self.headers.get("Last-Event-ID") or ""
        if last_event_id.strip().isdigit():
            since = max(since, int(last_event_id.strip()))
        limit = max(1, min(500, int(query.get("limit", ["200"])[0] or 200)))
        heartbeat_s = max(1.0, min(120.0, float(query.get("heartbeat", ["15"])[0] or 15)))
        max_events = int(query.get("max", ["0"])[0] or 0)  # 0 = endlos (Browser-Default)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        subscription = ENGINE.hub.subscribe(since=since, limit=limit)
        sent = 0
        last_beat = time.monotonic()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.sse_write("hello", {
                "ok": True,
                "transport": "sse",
                "since": subscription.cursor,
                "last_seq": ENGINE.hub.last_seq(),
                "stream": ENGINE.hub.stats(),
                "polling_fallback": "/api/events",
            })
            while True:
                events = subscription.wait(timeout=min(heartbeat_s, 0.5))
                if events:
                    for event in events:
                        self.sse_write("chain", event, event_id=str(event.get("seq")))
                        sent += 1
                elif time.monotonic() - last_beat >= heartbeat_s:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_beat = time.monotonic()
                if self.client_gone():
                    break  # EventSource getrennt -> Thread und Abo freigeben
                if max_events and sent >= max_events:
                    self.sse_write("done", {"ok": True, "sent": sent, "seq": subscription.cursor})
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Client hat getrennt – EventSource reconnectet mit Last-Event-ID
        finally:
            ENGINE.hub.unsubscribe(subscription)

    def client_gone(self) -> bool:
        """Erkennt ein getrenntes SSE-Client-Socket, ohne auf den nächsten Push zu warten."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            return not self.connection.recv(1, socket.MSG_PEEK)
        except (OSError, ValueError):
            return True

    # ------------------------------------------------------------------ #
    # WASM-Asset des C++-DSP-Kerns
    # ------------------------------------------------------------------ #
    def send_wasm_asset(self, path: str) -> None:
        name = Path(path).name
        target = WASM_DIR / name
        if not target.is_file() or target.parent.resolve() != WASM_DIR.resolve():
            self.send_json({"ok": False, "error": f"wasm asset not built: {name}", "hint": "make wasm"}, code=404)
            return
        body = target.read_bytes()
        content_type = "application/wasm" if name.endswith(".wasm") else mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
                    # neu: echte Capture-Blöcke, Ketten-Persistenz, SSE, Replay, WASM-DSP
                    "live_audio_capture": True,
                    "capture_backends": ["alsa", "usb_uac2", "ble_lc3_ipc", "file"],
                    "session_persistence": True,
                    "session_store": str(SESSION_STORE.relative_to(ROOT)),
                    "cypher_replay": True,
                    "sse_events": True,
                    "wasm_dsp": wasm_status()["built"],
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

        if path in {"/api/events/stream", "/events/stream"}:
            self.stream_events(query)
            return

        if path in {"/api/session/latest", "/session/latest"}:
            try:
                payload = ENGINE.load_session()
            except FileNotFoundError:
                self.send_json({
                    "ok": False,
                    "error": "no persisted session",
                    "store": str(SESSION_STORE.relative_to(ROOT)),
                    "restored": ENGINE.restored,
                    "sessions": ENGINE.list_sessions(),
                }, code=404)
                return
            self.send_json({
                "ok": True,
                "session": payload,
                "restored": ENGINE.restored,
                "store": str(SESSION_STORE.relative_to(ROOT)),
                "sessions": ENGINE.list_sessions(),
            })
            return

        if path in {"/api/sessions", "/session/store", "/api/session/store"}:
            self.send_json({
                "ok": True,
                "store": str(SESSION_STORE.relative_to(ROOT)),
                "sessions": ENGINE.list_sessions(),
                "restored": ENGINE.restored,
                "chain_seq": ENGINE.events[-1]["seq"] if ENGINE.events else 0,
            })
            return

        if path in {"/api/audio/capture", "/audio/capture"}:
            frames = int(query.get("frames", ["0"])[0] or 0)
            block = None
            pcm_preview: list[float] = []
            if frames:
                captured = ENGINE.capture_router.pull(frames, timeout_s=float(query.get("timeout", ["0.3"])[0] or 0.3))
                if captured is not None:
                    block = captured.provenance()
                    pcm_preview = [round(value, 6) for value in captured.pcm[:8]]
            self.send_json({
                "ok": True,
                "status": ENGINE.capture_router.status(),
                "probe": ENGINE.capture_router.probe(),
                "block": block,
                "pcm_preview": pcm_preview,
                "stats": dict(ENGINE.capture_stats),
            })
            return

        if path in {"/api/wasm", "/wasm/status"}:
            self.send_json(wasm_status())
            return

        if path.startswith("/wasm/"):
            self.send_wasm_asset(path)
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
            self.send_json({
                "ok": True,
                "bridge": "kaoss-native-bridge",
                "auto_load": True,
                "active_port": BRIDGE_ACTIVE_PORT,
                "ports": self.port_statuses(),
            })
            return

        if path in {"/native-bridge/load", "/api/native-bridge/load"}:
            action = str(query.get("action", [""])[0] or "")
            loaded = load_native_port_for_action(action)
            if loaded is None:
                self.send_json({"ok": False, "error": f"no port mapping for action {action}"}, code=400)
                return
            self.send_json(loaded)
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

        if path in {"/devices/usb", "/api/usb/hotplug"}:
            from usb_uac2 import hotplug_snapshot

            self.send_json(hotplug_snapshot())
            return

        if path in {"/devices/ble", "/api/ble/codecs"}:
            from ble_codecs import negotiate

            preferred = query.get("codec", ["lc3plus"])[0]
            self.send_json(negotiate(preferred))
            return

        if path in {"/audio/oboe", "/api/audio/oboe"}:
            from oboe_exclusive import open_stream

            rate = float(query.get("sample_rate_hz", [ENGINE.audio["sample_rate_hz"]])[0])
            frames = int(query.get("frames", [ENGINE.audio["frames_per_buffer"]])[0])
            self.send_json(open_stream(rate, frames))
            return

        if path in {"/models/whisper", "/api/models/whisper"}:
            from tflite_runtime import model_status

            self.send_json(model_status())
            return

        if path in {"/models/midas", "/api/models/midas"}:
            from midas import depth_from_luma

            self.send_json(depth_from_luma(seed=query.get("source", ["orchestrator"])[0]))
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
                "skeleton": ENGINE.avatar.get("skeleton"),
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
            result = ENGINE.dispatch(action, params, strict=strict)
            load_native_port_for_action(action)
            self.send_json(self.action_response(result))
            return

        if path in {"/api/session/import", "/session/import", "/api/session/replay", "/session/replay"}:
            self.send_json(self.session_replay(params))
            return

        if path in {"/api/session/restore", "/session/restore"}:
            self.send_json(self.session_restore(params))
            return

        if path in {"/api/audio/capture", "/audio/capture"}:
            self.send_json(self.capture_control(params))
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
            last_action = next((item.get("action") for item in reversed(normalized) if item.get("action")), "boot")
            load_native_port_for_action(str(last_action))
            self.send_json({"ok": report["ok"], "chain_run": report, "native_bridge": BRIDGE_LOADED.get(BRIDGE_ACTIVE_PORT or 0)})
            return

        if path in {"/native-bridge/load", "/api/native-bridge/load"}:
            action = str(params.get("action", ""))
            loaded = load_native_port_for_action(action)
            if loaded is None:
                self.send_json({"ok": False, "error": f"no port mapping for action {action}"}, code=400)
                return
            self.send_json(loaded)
            return

        action = POST_ROUTES.get(path)
        if action is None:
            self.send_json({"ok": False, "error": f"no POST action for {path}", "routes": sorted(POST_ROUTES)}, code=404)
            return
        strict = bool(params.pop("strict", True))
        result = ENGINE.dispatch(action, params, strict=strict)
        load_native_port_for_action(action)
        self.send_json(self.action_response(result))

    def session_restore(self, params: dict[str, object]) -> dict[str, object]:
        """Persistierte Sitzung in den Live-State importieren (ohne Replay)."""
        payload = params.get("session") if isinstance(params.get("session"), dict) else None
        source = "inline"
        if payload is None:
            requested = str(params.get("path") or params.get("file") or "")
            if requested:
                target = Path(requested)
                if not target.is_absolute():
                    target = ROOT / target
                if not target.is_file() or target.suffix != ".json":
                    return {"ok": False, "error": f"session file not readable: {requested}"}
                payload = ENGINE.load_session(target)
                source = str(target.relative_to(ROOT))
            else:
                report = ENGINE.restore_from_store()
                if report is None:
                    return {"ok": False, "error": "no persisted session", "store": str(SESSION_STORE.relative_to(ROOT))}
                return {"ok": bool(report.get("ok")), "source": report.get("source", ""), "restored": report, "state": ENGINE.state()}
        report = ENGINE.restore_session(payload if isinstance(payload, dict) else {}, source=source)
        return {"ok": bool(report.get("ok")), "source": source, "restored": report, "state": ENGINE.state()}

    def session_replay(self, params: dict[str, object]) -> dict[str, object]:
        """Ketten-Replay aus ``.cypher``: aus Pfad, Inline-Payload oder dem letzten Store-Eintrag."""
        strict = bool(params.get("strict", True))
        reset = bool(params.get("reset", True))
        source = ""
        payload = params.get("session") if isinstance(params.get("session"), dict) else None
        if payload is not None:
            source = "inline"
        requested = str(params.get("path") or params.get("file") or "")
        if payload is None and requested:
            target = Path(requested)
            if not target.is_absolute():
                target = ROOT / target
            try:
                inside = target.resolve().is_relative_to(ROOT.resolve())
            except AttributeError:  # Python < 3.9
                inside = str(target.resolve()).startswith(str(ROOT.resolve()))
            if not inside or target.suffix != ".json" or not target.is_file():
                return {"ok": False, "error": f"session file not readable: {requested}", "store": str(SESSION_STORE.relative_to(ROOT))}
            payload = ENGINE.load_session(target)
            source = str(target.relative_to(ROOT))
        if payload is None and isinstance(params.get("action_chain"), list):
            payload = params
            source = "inline"
        if payload is None:
            try:
                payload = ENGINE.load_session()
                source = str((SESSION_STORE / "latest.cypher.json").relative_to(ROOT))
            except (FileNotFoundError, OSError):
                return {"ok": False, "error": "no session payload and no persisted session", "store": str(SESSION_STORE.relative_to(ROOT))}
        report = ENGINE.replay_cypher(payload if isinstance(payload, dict) else {}, strict=strict, reset=reset)
        report.pop("results", None)
        return {"ok": report["ok"], "source": source, "replay": report}

    def capture_control(self, params: dict[str, object]) -> dict[str, object]:
        """Echte Capture-Route öffnen/schließen und optional sofort einen Block ziehen."""
        frames = int(params.get("frames") or 0)
        if params.get("close") or params.get("open") is False:
            ENGINE.capture_router.close()
            ENGINE.capture.update({"armed": False, "backend": "none", "real_capture": False, "reason": "closed by request"})
            return {"ok": True, "opened": False, "capture": dict(ENGINE.capture), "status": ENGINE.capture_router.status()}
        info = ENGINE.open_capture(
            mode=str(params.get("mode") or params.get("capture") or "auto"),
            sample_rate_hz=params.get("sample_rate_hz"),
            frames_per_buffer=params.get("frames_per_buffer"),
            device=params.get("device"),
            file_path=params.get("file"),
        )
        block = None
        pcm_preview: list[float] = []
        if frames:
            captured = ENGINE.capture_router.pull(frames, timeout_s=float(params.get("timeout") or 0.4))
            if captured is not None:
                block = captured.provenance()
                pcm_preview = [round(value, 6) for value in captured.pcm[:8]]
        return {
            "ok": True,
            "opened": bool(info.get("opened")),
            "capture": dict(ENGINE.capture),
            "status": ENGINE.capture_router.status(),
            "block": block,
            "pcm_preview": pcm_preview,
        }

    def action_response(self, result: dict[str, object]) -> dict[str, object]:
        code_status = result.get("status")
        action = result.get("action")
        loaded = BRIDGE_LOADED.get(int(result.get("port") or 0))
        return {
            "ok": bool(result.get("ok")),
            "action": action,
            "seq": result.get("seq"),
            "status": code_status,
            "engine": result.get("engine"),
            "port": result.get("port"),
            "latency_ms": result.get("latency_ms"),
            "t_ms": result.get("t_ms"),
            "detail": result.get("detail"),
            "state": result.get("state"),
            "chain": (result.get("state") or {}).get("chain"),
            "native_bridge": loaded or load_native_port_for_action(str(action or "")),
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
        rows = []
        for spec in DAEMONS:
            port = int(spec["port"])
            loaded = BRIDGE_LOADED.get(port)
            hits = engine_hits.get(
                next((name for name, meta in ENGINES.items() if meta["port"] == port), ""), 0
            )
            if BRIDGE_ACTIVE_PORT == port:
                status = "ACTIVE"
            elif loaded or hits:
                status = "LOADED"
            elif port in {8080, 8081, 8084}:
                status = "LOCKED"
            else:
                status = "READY"
            rows.append({
                **spec,
                "bind": self.server.server_address[0],
                "status": status,
                "single_app": True,
                "auto_loaded": bool(loaded),
                "loaded_action": (loaded or {}).get("action"),
                "native_bridge": True,
                "chain_hits": hits,
            })
        return rows


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
    parser.add_argument("--restore", action="store_true", help="persistierte Sitzung beim Start in den Live-State importieren")
    parser.add_argument("--no-restore", action="store_true", help="Session-Store beim Start gar nicht lesen")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        raise SystemExit("Refusing non-local bind host for zero-cloud app")
    ensure_database(DB_PATH)
    if args.no_restore:
        ENGINE.inspect_on_boot = False
        ENGINE.restored = {"ok": False, "reason": "session store disabled by --no-restore", "source": "", "resumed": False}
    elif args.restore:
        ENGINE.restored = ENGINE.restore_from_store() or ENGINE.restored
        if ENGINE.restored and ENGINE.restored.get("ok"):
            print(
                f"Sitzung importiert: {ENGINE.restored.get('chain_length')} Schritte aus "
                f"{ENGINE.restored.get('source')} ({str(ENGINE.restored.get('checksum'))[:12]})",
                flush=True,
            )
    elif ENGINE.restored and ENGINE.restored.get("ok"):
        print(
            f"Letzte Sitzung verfügbar: {ENGINE.restored.get('chain_length')} Schritte, "
            f"preset={ENGINE.restored.get('preset')} ({str(ENGINE.restored.get('checksum'))[:12]}) "
            f"-> GET /api/session/latest, POST /api/session/restore|replay",
            flush=True,
        )
    if args.run_chain:
        report = ENGINE.run_script()
        print(f"Action chain pre-run: {report['steps']} steps ok={report['ok']} blocked={report['blocked']}", flush=True)
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    port = resolve_port(args.host, str(args.port))

    class KaossServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 128
        allow_reuse_address = True

    server = KaossServer((args.host, port), OneAppHandler)
    print(f"Kaoss One App ready: http://{args.host}:{port}/", flush=True)
    print(f"POST actions: {len(POST_ROUTES) + 2} routes // chain catalogue: {len(ACTION_CATALOGUE)} actions", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
