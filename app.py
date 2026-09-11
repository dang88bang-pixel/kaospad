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
import os
import socket
import sys
import threading
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
from dsp_chain import (  # noqa: E402
    LIMITER_THRESHOLD_DBFS,
    KaossQuadChain,
    direct_pipe_roundtrip_ms,
    process_block,
    test_signal,
)
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
    "/api/status", "/api/runtime", "/api/state", "/api/actions", "/api/events",
    "/api/action", "/api/chain/run", "/api/chain/reset",
    "/native-bridge/ports", "/native-bridge/load", "/devices/status", "/devices/select", "/permissions/check",
    "/api/presets", "/api/preset/apply", "/api/kaoss/xy", "/api/kaoss/freeze",
    "/api/dsp/process", "/api/pad/trigger", "/api/transport/record", "/api/loop/capture",
    "/api/transcribe", "/api/rhymes", "/api/avatar/mode", "/api/neurallift/generate",
    "/api/session/export", "/mesh/default", "/dsp/transient", "/api/logs",
    "/api/daemons", "/api/audio/calibrate", "/api/audio/capture",
]

ENGINE = build_engine(DB_PATH)
# Phase 3/5: IPC binding with retry/circuit-breaker + watchdog (graceful fallback if not installed)
try:
    from ipc_binding import call_with_retry, serialize, deserialize  # type: ignore
    HAS_IPC_BINDING = True
except ImportError:
    HAS_IPC_BINDING = False
    def call_with_retry(key, func, timeout_ms=5000, attempts=3, base_delay_ms=20):
        try:
            return func()
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "attempt": attempts, "degraded": True}
    def serialize(payload):  # type: ignore
        import json as _json
        return _json.dumps(payload, ensure_ascii=False).encode("utf-8")
    def deserialize(blob):  # type: ignore
        import json as _json
        try:
            return _json.loads(blob.decode("utf-8"))
        except Exception:
            return {"raw": blob.hex()[:80]}

def _dispatch_with_binding(action: str, params: dict, strict: bool = True, timeout_ms: int = 5000):
    """Phase 3: 5s timeout, 3 attempts, user-friendly error + bug file."""
    def _call():
        return ENGINE.dispatch(action, params, strict=strict)
    if HAS_IPC_BINDING:
        return call_with_retry(f"app:{action}", _call, timeout_ms=timeout_ms, attempts=3)
    # fallback direct
    try:
        return _call()
    except Exception as exc:
        # Graceful Degradation + Bug-Report-File (Phase 5)
        try:
            import hashlib as _h, time as _t, json as _j
            from pathlib import Path as _P
            bid = _h.sha256(f"{action}:{_t.time()}:{exc}".encode()).hexdigest()[:12]
            (_P("dist/bug_reports") / f"{bid}.json").parent.mkdir(parents=True, exist_ok=True)
            (_P("dist/bug_reports") / f"{bid}.json").write_text(_j.dumps({"action": action, "error": str(exc)[:300], "type": type(exc).__name__, "at": _t.time()}, indent=2), encoding="utf-8")
        except Exception:
            pass
        return {"ok": False, "action": action, "status": "ERROR", "detail": {"error": f"User-friendly: {exc}.".strip()[:300], "hint": "Siehe dist/bug_reports/*.json"}, "seq": 0, "latency_ms": 0}

# Native-Bridge: welcher Engine-Port zuletzt zur Aktion geladen wurde.
BRIDGE_LOADED: dict[int, dict[str, object]] = {}
BRIDGE_ACTIVE_PORT: int | None = None

# Logische Daemon-Registry (one-app: alle Engine-Rollen laufen in diesem Prozess).
DAEMON_REGISTRY_LOCK = threading.Lock()
DAEMON_RESTARTS: dict[int, int] = {}
DAEMON_LAST_RESTART_MS: dict[int, float] = {}


def daemon_statuses() -> list[dict[str, object]]:
    with DAEMON_REGISTRY_LOCK:
        return [
            {
                "port": int(spec["port"]),
                "name": spec["name"],
                "pid": os.getpid(),
                "in_process": True,
                "health": "ok",
                "restarts": DAEMON_RESTARTS.get(int(spec["port"]), 0),
                "last_restart_ms": DAEMON_LAST_RESTART_MS.get(int(spec["port"])),
            }
            for spec in DAEMONS
        ]


def restart_daemon(port: int) -> dict[str, object]:
    known = {int(spec["port"]) for spec in DAEMONS}
    if port not in known:
        return {"ok": False, "error": f"unknown daemon port {port}", "known": sorted(known)}
    now_ms = round(time.time() * 1000.0, 3)
    with DAEMON_REGISTRY_LOCK:
        DAEMON_RESTARTS[port] = DAEMON_RESTARTS.get(port, 0) + 1
        DAEMON_LAST_RESTART_MS[port] = now_ms
    # Die One-App läuft als ein Prozess: "Restart" re-initialisiert die logische
    # Rolle (Bridge-Load-State + Health), statt einen echten Prozess neu zu starten.
    if port == BRIDGE_ACTIVE_PORT:
        BRIDGE_LOADED.pop(port, None)
    return {
        "ok": True,
        "logical_restart": True,
        "in_process": True,
        "port": port,
        "pid": os.getpid(),
        "restarts": DAEMON_RESTARTS[port],
        "health": "ok",
        "last_restart_ms": now_ms,
    }


def calibrate_roundtrip() -> dict[str, object]:
    """Deterministische Loopback-Kalibrierung des Audio-Pfads (Python-DSP-Spiegel)."""
    sample_rate = float(ENGINE.audio["sample_rate_hz"])
    frames = int(ENGINE.audio["frames_per_buffer"])
    chain = KaossQuadChain()
    chain.bpm = ENGINE.chain.bpm
    chain.sample_rate_hz = sample_rate
    started = time.perf_counter()
    signal = test_signal("mouth_bass", frames=frames, sample_rate_hz=sample_rate)
    report = process_block(signal, chain, sample_rate)
    compute_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "ok": True,
        "method": "deterministic-fixture",
        "sample_rate_hz": sample_rate,
        "frames_per_buffer": frames,
        "block_latency_ms": round(float(report["latency_ms"]), 3),
        "direct_pipe_roundtrip_ms": round(direct_pipe_roundtrip_ms(sample_rate, frames), 3),
        "dsp_compute_ms": compute_ms,
        "peak_dbfs": report["output_peak_dbfs"],
        "limiter_dbfs": LIMITER_THRESHOLD_DBFS,
        "transient": report["transient"],
        "zero_cloud": True,
    }


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

        if path in {"/api/events/stream", "/events/stream"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            since = int(query.get("since", ["0"])[0] or 0)
            events = ENGINE.events_since(since)
            chunk = f"data: {json.dumps({'ok': True, 'events': events}, ensure_ascii=False)}\n\n"
            self.wfile.write(chunk.encode("utf-8"))
            return

        if path in {"/api/session/latest", "/session/latest"}:
            try:
                payload = ENGINE.load_session()
                self.send_json({"ok": True, "session": payload})
            except FileNotFoundError:
                self.send_json({"ok": False, "error": "no persisted session"}, code=404)
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

        if path in {"/api/daemons", "/daemons"}:
            self.send_json({"ok": True, "mode": "one-app", "in_process": True, "daemons": daemon_statuses()})
            return

        if path in {"/api/audio/calibrate", "/audio/calibrate"}:
            self.send_json(calibrate_roundtrip())
            return

        if path in {"/api/audio/capture", "/audio/capture"}:
            # Im Python-Host läuft die echte Aufnahme über WebAudio bzw. die native
            # Android-Shell (AAudio/AudioRecord); hier wird der bekannte Zustand projiziert.
            self.send_json({
                "ok": True,
                "backend": "browser-webaudio",
                "native_aaudio": False,
                "fallback_audiorecord": False,
                "running": bool(ENGINE.audio["mic_armed"]),
                "sample_rate_hz": ENGINE.audio["sample_rate_hz"],
                "frames_per_buffer": ENGINE.audio["frames_per_buffer"],
                "underruns": ENGINE.audio["underruns"],
                "note": "Native AAudio/AudioRecord capture runs in the Android shell; WebAudio in the browser.",
            })
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
            result = _dispatch_with_binding(action, params, strict=strict)
            load_native_port_for_action(action)
            self.send_json(self.action_response(result))
            return

        if path in {"/api/session/import", "/session/import"}:
            payload = params.get("session") if isinstance(params.get("session"), dict) else params
            report = ENGINE.replay_cypher(payload if isinstance(payload, dict) else {})
            self.send_json({"ok": report["ok"], "replay": report})
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

        if path in {"/api/daemons/restart", "/daemons/restart"}:
            try:
                port = int(params.get("port", 0))
            except (TypeError, ValueError):
                self.send_json({"ok": False, "error": "port must be an integer"}, code=400)
                return
            result = restart_daemon(port)
            self.send_json(result, code=200 if result["ok"] else 400)
            return

        if path in {"/api/audio/calibrate", "/audio/calibrate"}:
            self.send_json(calibrate_roundtrip())
            return

        action = POST_ROUTES.get(path)
        if action is None:
            self.send_json({"ok": False, "error": f"no POST action for {path}", "routes": sorted(POST_ROUTES)}, code=404)
            return
        strict = bool(params.pop("strict", True))
        result = _dispatch_with_binding(action, params, strict=strict)
        load_native_port_for_action(action)
        self.send_json(self.action_response(result))

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
        health = {row["port"]: row for row in daemon_statuses()}
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
            daemon = health.get(port, {})
            rows.append({
                **spec,
                "bind": self.server.server_address[0],
                "status": status,
                "single_app": True,
                "auto_loaded": bool(loaded),
                "loaded_action": (loaded or {}).get("action"),
                "native_bridge": True,
                "chain_hits": hits,
                "pid": daemon.get("pid"),
                "health": daemon.get("health", "ok"),
                "restarts": daemon.get("restarts", 0),
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
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        raise SystemExit("Refusing non-local bind host for zero-cloud app")
    ensure_database(DB_PATH)
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
