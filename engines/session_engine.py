#!/usr/bin/env python3
"""Stateful Kaoss session engine: the complete action & interaction chain.

Until now every endpoint of the suite answered with static constants, so a user
interaction (choose input -> grant permission -> arm mic -> load preset -> move
XY pad -> freeze -> trigger pad -> record -> transcribe -> export) could not be
observed, replayed or tested as one chain.

This module owns that chain:

* one authoritative, thread-safe session state (route, permissions, transport,
  Kaoss Quad XY/freeze, DSP metering, lyrics, avatar stage),
* an ordered action catalogue where each action is bound to the localhost daemon
  that would serve it in production (ports 8080-8085),
* dependency rules (``requires``) so an out-of-order interaction is reported as
  ``BLOCKED`` instead of silently succeeding,
* an append-only event log (the "Aktionskette") with sequence ids, engine,
  latency and result, which is part of the ``.cypher`` session export.

It is offline-only: no DNS, no external sockets, no cloud model calls.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]

_FALLBACK_CAPSULE_STATS: dict[str, Any] | None = None


def _fallback_capsule_stats() -> dict[str, Any]:
    """Kennzahlen der Fallback-Kapsel – aus den GLB-Bytes gelesen, nicht geraten."""
    global _FALLBACK_CAPSULE_STATS
    if _FALLBACK_CAPSULE_STATS is None:
        from glb import build_capsule_glb, glb_stats

        _FALLBACK_CAPSULE_STATS = glb_stats(build_capsule_glb("default"))
    return _FALLBACK_CAPSULE_STATS
DB_PATH = ROOT / "dist" / "offline-rhymes.sqlite3"
SESSION_STORE = ROOT / "dist" / "sessions"

# Importable both as top-level module (engines/ on sys.path) and via package path.
for _path in (
    str(Path(__file__).resolve().parent),
    str(Path(__file__).resolve().parent / "whisper_offline"),
    str(Path(__file__).resolve().parent / "neurallift_360"),
    str(Path(__file__).resolve().parent / "mopac_dance_learner"),
):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from audio_capture import CaptureRouter, fixture_block
from dsp_chain import (
    LIMITER_THRESHOLD_DBFS,
    MODULE_NAMES,
    KaossQuadChain,
    process_block,
    quantize_step_ms,
    synthesize_808,
    test_signal,
)
from device_matrix import permissions as device_permissions, save_selection, status as device_status
from event_stream import EventHub

APP_VERSION = "5.0.0-offline-one-app"
INPUTS = ("usb_c_audio", "internal_mic", "bluetooth_client")
AVATAR_MODES = ("CYPHER_CIRCLE", "PARTY_8", "SOLO_HUD", "TANZ_ANLERNEN", "ENDLESS_REEL")
PRESET_IDS = ("90s_tape", "acid_berlin", "cyber_drill", "lofi_cypher")
RUNTIME_PROMPT_PERMISSIONS = ("record_audio", "bluetooth_connect", "bluetooth_scan")

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

PAD_SIGNAL = {
    "A": "mouth_bass",
    "B": "snare",
    "C": "hat",
    "D": "vocal",
}

ENGINES = {
    "orchestrator": {"port": 8080, "name": "master-system-orchestrator", "protocol": "HTTP JSON"},
    "audio": {"port": 8081, "name": "audio-loopback-daemon", "protocol": "Float32 PCM pipe"},
    "neurallift": {"port": 8082, "name": "neurallift-engine", "protocol": "HTTP GLB JSON"},
    "avatar": {"port": 8083, "name": "avatar-orchestrator", "protocol": "skeleton JSONL"},
    "dsp": {"port": 8084, "name": "dsp-transient-bridge", "protocol": "DSP block JSON"},
    "whisper": {"port": 8085, "name": "offline-whisper-daemon", "protocol": "HTTP UTF-8"},
}


@dataclass(frozen=True)
class ActionSpec:
    action: str
    engine: str
    summary: str
    params: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "engine": self.engine,
            "port": ENGINES[self.engine]["port"],
            "summary": self.summary,
            "params": list(self.params),
            "requires": list(self.requires),
        }


ACTION_CATALOGUE: tuple[ActionSpec, ...] = (
    ActionSpec("boot", "orchestrator", "Zero-cloud one-app Boot + State-Reset"),
    ActionSpec("input.select", "orchestrator", "USB-C / internes Mic / Bluetooth Route locken", ("input",)),
    ActionSpec("permission.check", "orchestrator", "Permission-Matrix rapportieren", (), ("input.selected",)),
    ActionSpec("permission.grant", "orchestrator", "Runtime-Permission erteilen/entziehen", ("key", "granted"), ("permission.checked",)),
    ActionSpec("audio.start", "audio", "WebAudio/AAudio Engine starten + Sample-Rate handeln", ("sample_rate_hz", "frames_per_buffer"), ("input.selected", "permission.granted")),
    ActionSpec("mic.arm", "audio", "Eingang armen (Monitor safe)", ("device_id",), ("audio.started",)),
    ActionSpec("preset.apply", "dsp", "Theme-Preset auf Kaoss Quad + BPM mappen", ("preset",), ("audio.started",)),
    ActionSpec("kaoss.xy", "dsp", "XY-Pad pro FX-Modul bewegen", ("module", "x", "y"), ("audio.started",)),
    ActionSpec("kaoss.freeze", "dsp", "FX-Modul einfrieren/lösen", ("module", "frozen"), ("audio.started",)),
    ActionSpec("dsp.process", "dsp", "Audio-Block durch Limiter/Transient/Quad jagen", ("signal", "frames", "sample_rate_hz"), ("mic.armed",)),
    ActionSpec("pad.trigger", "dsp", "Sample-Bank-Pad A-D triggern", ("bank", "slot"), ("mic.armed",)),
    ActionSpec("transport.record", "orchestrator", "Cypher-Aufnahme starten/stoppen", ("running",), ("dsp.processed",)),
    ActionSpec("loop.capture", "dsp", "Looper-Freeze auf 1/16 Quantisierung capturen", ("subdivision",), ("transport.recording",)),
    ActionSpec("transcribe", "whisper", "Offline Transkript (Whisper-Shim) erzeugen", ("text", "signal"), ("mic.armed",)),
    ActionSpec("rhyme.lookup", "whisper", "Reim-Matrix aus lokaler SQLite laden", ("word",), ("permission.checked",)),
    ActionSpec("avatar.mode", "avatar", "Avatar-Stage Modus + Skeleton Matrix setzen", ("mode",), ("audio.started",)),
    ActionSpec("neurallift.generate", "neurallift", "Foto/Mesh zu GLB Avatar (offline Fallback)", ("source",), ("avatar.mode",)),
    ActionSpec("session.export", "orchestrator", "Session als .cypher inkl. Aktionskette exportieren", (), ("mic.armed",)),
    ActionSpec("chain.reset", "orchestrator", "Aktionskette + State zurücksetzen"),
)

ACTION_BY_NAME: dict[str, ActionSpec] = {spec.action: spec for spec in ACTION_CATALOGUE}

# Canonical user journey: exactly this order forms the complete chain.
FULL_CHAIN_SCRIPT: tuple[dict[str, Any], ...] = (
    {"action": "boot"},
    {"action": "input.select", "input": "usb_c_audio"},
    {"action": "permission.check"},
    {"action": "permission.grant", "key": "record_audio", "granted": True},
    {"action": "audio.start", "sample_rate_hz": 96_000, "frames_per_buffer": 128},
    {"action": "mic.arm", "device_id": "usb-c-uac2"},
    {"action": "preset.apply", "preset": "acid_berlin"},
    {"action": "kaoss.xy", "module": 2, "x": 0.82, "y": 0.46},
    {"action": "kaoss.xy", "module": 3, "x": 0.35, "y": 0.55},
    {"action": "dsp.process", "signal": "mouth_bass", "frames": 128},
    {"action": "pad.trigger", "bank": "A", "slot": "MOUTH 808"},
    {"action": "dsp.process", "signal": "snare", "frames": 128},
    {"action": "pad.trigger", "bank": "B", "slot": "CLAP"},
    {"action": "dsp.process", "signal": "hat", "frames": 128},
    {"action": "transport.record", "running": True},
    {"action": "loop.capture", "subdivision": 16},
    {"action": "kaoss.freeze", "module": 0, "frozen": True},
    {"action": "transcribe", "text": "drück und laber beton sektor dämon"},
    {"action": "rhyme.lookup", "word": "beton"},
    {"action": "avatar.mode", "mode": "CYPHER_CIRCLE"},
    {"action": "neurallift.generate", "source": "camera_frame_0001.jpg"},
    {"action": "transport.record", "running": False},
    {"action": "session.export"},
)


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        return min(high, max(low, float(value)))
    except (TypeError, ValueError):
        return default


# PCM-Payloads gehören nicht in die .cypher-Datei (Größe + Replay-Deterministik);
# alles andere wird 1:1 mitgeschrieben, damit Replay dieselbe Reise fährt.
_PARAM_OMIT = {"pcm", "pcm_b64", "samples", "audio", "session"}


def sanitize_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """JSON-sichere, replay-fähige Kopie der Aktionsparameter."""
    clean: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key in _PARAM_OMIT:
            clean[key] = f"<omitted:{type(value).__name__}>"
            continue
        if isinstance(value, (list, tuple)) and len(value) > 16:
            clean[key] = f"<omitted:{len(value)} values>"
            continue
        if isinstance(value, dict):
            clean[key] = sanitize_params(value)
            continue
        if isinstance(value, str) and len(value) > 240:
            clean[key] = value[:240] + "…"
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            value = str(value)
        clean[key] = value
    return clean


def _shrink_detail(detail: dict[str, Any] | None, max_items: int = 16, max_text: int = 160) -> dict[str, Any]:
    """Kompakte Event-Zusammenfassung für SSE (volles Detail bleibt im Polling)."""
    small: dict[str, Any] = {}
    for key, value in list((detail or {}).items())[:max_items]:
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value)
            small[key] = text[:max_text] + "…" if len(text) > max_text else value
        elif isinstance(value, dict):
            small[key] = _shrink_detail(value, max_items=8, max_text=max_text)
        elif isinstance(value, (list, tuple)):
            small[key] = f"<{len(value)} items>"
        else:
            small[key] = f"<{type(value).__name__}>"
    return small


class SessionEngine:
    """Owns the offline session state and the ordered action chain."""

    def __init__(self, db_path: Path = DB_PATH, version: str = APP_VERSION) -> None:
        self.db_path = Path(db_path)
        self.version = version
        self._lock = threading.RLock()
        self._boot_monotonic = time.perf_counter()
        self._seq = 0
        self.events: list[dict[str, Any]] = []
        self.chain = KaossQuadChain()
        self.milestones: set[str] = set()
        # Eine Event-Quelle für Polling *und* SSE (/api/events/stream).
        self.hub = EventHub()
        # Echte Capture-Blöcke (Mic/USB-UAC2/BLE-IPC) statt reiner Fixtures.
        self.capture_router = CaptureRouter()
        self.restored: dict[str, Any] | None = None
        # Neustart-Persistenz: beim Boot die letzte Sitzung anzeigen/importieren.
        self.restore_on_boot = False
        self.inspect_on_boot = True
        self.reset_state()

    # ------------------------------------------------------------------ #
    # state
    # ------------------------------------------------------------------ #
    def reset_state(self) -> None:
        with self._lock:
            self.chain = KaossQuadChain()
            self.milestones = set()
            self.input = "internal_mic"
            # Deklarierte Feature-Permissions sind vorhanden, Runtime-Prompts
            # (Mic, Bluetooth) müssen in der Kette erst erteilt werden.
            self.permission_grants = {
                spec.key: (spec.granted and spec.key not in RUNTIME_PROMPT_PERMISSIONS)
                for spec in device_permissions()
            }
            self.permission_checked = False
            self.audio = {
                "running": False,
                "sample_rate_hz": 96_000.0,
                "frames_per_buffer": 128,
                "roundtrip_ms": 1.2,
                "route_locked": True,
                "mic_armed": False,
                "mic_device": "",
                "monitor_db": -6.0,
                "underruns": 0,
                "glitches": 0,
            }
            self.preset = dict(PRESETS[0])
            self.transport = {
                "recording": False,
                "started_seq": None,
                "stopped_seq": None,
                "loop_captured": False,
                "loop_frames": 0,
                "loop_subdivision": 16,
                "loop_step_ms": quantize_step_ms(self.preset["bpm"]),
            }
            self.dsp = {
                "blocks": 0,
                "kick808": 0,
                "snare": 0,
                "hat": 0,
                "max_peak_dbfs": -120.0,
                "last": None,
                "checksums": [],
            }
            self.pads: list[dict[str, Any]] = []
            self.lyrics = {"transcripts": [], "rhymes": {}, "language": "de", "offline": True, "buffer_ms": 500}
            # -- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 2, P2-2)
            # Vorher: lod0_tris 45000 / lod1_tris 18000 / rig_bones 24 – erfundene
            # Zahlen ohne Rig und ohne LOD1. Jetzt werden die Kennzahlen der
            # tatsächlich geschriebenen Fallback-Kapsel aus den Bytes gelesen.
            capsule = _fallback_capsule_stats()
            self.avatar = {
                "mode": "CYPHER_CIRCLE",
                "fps": 60,
                "avatars": 8,
                "bones": 33,
                "glb": "procedural_default_avatar.glb",
                "vertices": capsule["vertices"],
                "lod0_tris": capsule["triangles"],
                "lod1_tris": 0,
                "rig_bones": 0,
                "rigged": False,
                "fallback": True,
                "generated_from": None,
                "note": "Fallback-Kapsel ohne Rig; das echte Landmark-Mesh liefert neurallift.generate",
            }
            self.profile = "A"
            self.mode = "CYPHER"
            self.pcm_ring: list[float] = []
            # Capture-Router schließen: ein Reset beendet jede offene Hardware-Pipe.
            self.capture_router.close()
            self.capture = {
                "armed": False,
                "backend": "none",
                "route": self.input,
                "mode": "none",
                "device": "",
                "real_capture": False,
                "blocks": 0,
                "frames": 0,
                "reason": "capture not armed",
                "available": False,
            }
            self.capture_stats: dict[str, Any] = {"real_blocks": 0, "fixture_blocks": 0, "by_backend": {}}

    def uptime_ms(self) -> float:
        return round((time.perf_counter() - self._boot_monotonic) * 1000.0, 3)

    # ------------------------------------------------------------------ #
    # public snapshots
    # ------------------------------------------------------------------ #
    def device_snapshot(self, selected: str | None = None) -> dict[str, Any]:
        chosen = selected or self.input
        if chosen not in INPUTS:
            chosen = "internal_mic"
        payload = device_status(chosen)  # type: ignore[arg-type]
        grants = self.permission_grants
        payload["permissions"] = [
            {**item, "granted": bool(item["granted"] and grants.get(item["key"], False))}
            for item in payload["permissions"]
        ]
        payload["runtime_grants"] = dict(grants)
        payload["audio"] = dict(self.audio)
        try:
            from usb_uac2 import hotplug_snapshot
            from ble_codecs import negotiate

            payload["usb_uac2"] = hotplug_snapshot()
            payload["ble_codecs"] = negotiate("lc3plus")
        except Exception:  # noqa: BLE001
            payload["usb_uac2"] = {"ok": True, "count": 0, "devices": []}
            payload["ble_codecs"] = {"ok": True, "selected": {"id": "lc3plus"}}
        return payload

    def state(self) -> dict[str, Any]:
        with self._lock:
            latencies = [event["latency_ms"] for event in self.events]
            device = next((item for item in device_status(self.input)["devices"] if item["id"] == self.input), None)  # type: ignore[arg-type]
            return {
                "ok": True,
                "app": "kaoss-one-app",
                "version": self.version,
                "offline": True,
                "zero_cloud": True,
                "uptime_ms": self.uptime_ms(),
                "profile": self.profile,
                "mode": self.mode,
                "bpm": self.chain.bpm,
                "limiter_dbfs": LIMITER_THRESHOLD_DBFS,
                "input": {
                    "selected": self.input,
                    "label": device["label"] if device else self.input,
                    "sample_rate_hz": device["sample_rate_hz"] if device else 48_000,
                    "latency_ms": device["latency_ms"] if device else 2.6,
                    "route": device["route"] if device else "localhost",
                    "locked": bool(self.audio["route_locked"]),
                },
                "permissions": [
                    {**item, "granted": bool(item["granted"] and self.permission_grants.get(item["key"], False))}
                    for item in [spec.__dict__ for spec in device_permissions()]
                ],
                "permission_checked": self.permission_checked,
                "audio": dict(self.audio),
                "preset": dict(self.preset),
                "kaoss": self.chain.state(),
                "transport": dict(self.transport),
                "dsp": {key: value for key, value in self.dsp.items() if key != "checksums"},
                "pads": list(self.pads),
                "lyrics": json.loads(json.dumps(self.lyrics, ensure_ascii=False)),
                "avatar": dict(self.avatar),
                "capture": dict(self.capture),
                "capture_stats": dict(self.capture_stats),
                "restored": dict(self.restored) if self.restored else None,
                "stream": self.hub.stats(),
                "milestones": sorted(self.milestones),
                "chain": {
                    "length": len(self.events),
                    "first_seq": self.events[0]["seq"] if self.events else None,
                    "last_seq": self.events[-1]["seq"] if self.events else None,
                    "blocked": sum(1 for event in self.events if event["status"] == "BLOCKED"),
                    "total_latency_ms": round(sum(latencies), 3),
                    "max_latency_ms": round(max(latencies), 3) if latencies else 0.0,
                    "actions": [event["action"] for event in self.events],
                },
            }

    def events_since(self, seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return [event for event in self.events if event["seq"] > seq][:limit]

    # ------------------------------------------------------------------ #
    # dispatch
    # ------------------------------------------------------------------ #
    def dispatch(self, action: str, params: dict[str, Any] | None = None, strict: bool = True) -> dict[str, Any]:
        params = dict(params or {})
        spec = ACTION_BY_NAME.get(action)
        if spec is None:
            return self._record(action, "orchestrator", False, 0.0, "UNKNOWN_ACTION", {"error": f"unknown action: {action}"}, strict)
        started = time.perf_counter()
        missing = [milestone for milestone in spec.requires if milestone not in self.milestones]
        if missing and strict:
            latency = (time.perf_counter() - started) * 1000.0
            return self._record(
                action,
                spec.engine,
                False,
                latency,
                "BLOCKED",
                {
                    "blocked_reason": "interaction chain out of order",
                    "missing_milestones": missing,
                    "expected_before": [name for name, milestone in _MILESTONE_SOURCES.items() if milestone in missing],
                },
                strict,
                params=params,
            )
        handler: Callable[[dict[str, Any]], dict[str, Any]] = getattr(self, "_do_" + action.replace(".", "_"))
        try:
            detail = handler(params)
            status = "OK"
            ok = True
        except (ValueError, KeyError, TypeError) as exc:
            detail = {"error": str(exc), "error_type": type(exc).__name__}
            status = "ERROR"
            ok = False
        latency = (time.perf_counter() - started) * 1000.0
        if ok and action != "chain.reset":
            self.milestones.add(_MILESTONE_SOURCES.get(action, action))
        result = self._record(action, spec.engine, ok, latency, status, detail, strict, params=params)
        if action == "chain.reset" and ok:
            # Ein Reset löscht die Kette inklusive seines eigenen Events, damit die
            # nächste Kette wieder bei seq 1 beginnt (deterministischer Export-Hash).
            with self._lock:
                self.events = []
                self._seq = 0
            result["state"] = self.state()
        return result

    def run_script(self, script: tuple[dict[str, Any], ...] | list[dict[str, Any]] = FULL_CHAIN_SCRIPT, strict: bool = True) -> dict[str, Any]:
        results = []
        for step in script:
            payload = dict(step)
            action = payload.pop("action")
            event = self.dispatch(action, payload, strict=strict)
            event.pop("state", None)  # State wird nur einmal am Ende geliefert
            results.append(event)
        ok = all(item["ok"] for item in results)
        state = self.state()
        return {
            "ok": ok,
            "steps": len(results),
            "actions": [item["action"] for item in results],
            "blocked": [item["action"] for item in results if item["status"] == "BLOCKED"],
            "strict": bool(strict),
            "chain": state["chain"],
            "results": results,
            "final_state": state,
        }

    def _record(
        self,
        action: str,
        engine: str,
        ok: bool,
        latency_ms: float,
        status: str,
        detail: dict[str, Any],
        strict: bool,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            event = {
                "seq": self._seq,
                "t_ms": self.uptime_ms(),
                "action": action,
                "engine": engine,
                "port": ENGINES.get(engine, {"port": 8080})["port"],
                "ok": ok,
                "status": status,
                "strict": bool(strict),
                "latency_ms": round(latency_ms, 3),
                "params": sanitize_params(params),
                "detail": detail,
            }
            self.events.append(event)
            if len(self.events) > 4096:
                del self.events[: len(self.events) - 4096]
            snapshot = self.state()
        # Pub/Sub für SSE (/api/events/stream) – außerhalb des State-Locks.
        self.hub.publish({key: value for key, value in event.items() if key != "detail"} | {"detail_summary": _shrink_detail(detail)})
        return {**event, "state": snapshot}

    # ------------------------------------------------------------------ #
    # action handlers
    # ------------------------------------------------------------------ #
    def _do_boot(self, params: dict[str, Any]) -> dict[str, Any]:
        self.reset_state()
        # Beim App-Start wird die letzte persistierte Sitzung *angezeigt*
        # (Neustart-Persistenz), nicht still in den frischen State übernommen.
        # ``restore=True`` (bzw. ``app.py --restore``) importiert sie explizit.
        restore = params.get("restore", self.restore_on_boot)
        restored: dict[str, Any] | None = None
        if restore:
            restored = self.restore_from_store()
        elif self.inspect_on_boot:
            restored = self.inspect_store()
        elif self.restored is None:
            self.restored = {"ok": False, "reason": "store inspection disabled", "source": "", "resumed": False}
        return {
            "booted": True,
            "zero_cloud": True,
            "version": self.version,
            "endpoints_ready": sorted(ENGINES),
            "restored": restored or dict(self.restored or {}),
        }

    def _do_input_select(self, params: dict[str, Any]) -> dict[str, Any]:
        selected = str(params.get("input", self.input))
        if selected not in INPUTS:
            raise ValueError(f"unsupported input: {selected}")
        payload = save_selection(selected)  # type: ignore[arg-type]
        self.input = selected
        device = next(item for item in payload["devices"] if item["id"] == selected)
        self.audio["mic_armed"] = False
        self.audio["mic_device"] = ""
        self.chain.sample_rate_hz = float(device["sample_rate_hz"])
        self.milestones.add("input.selected")
        return {
            "selected": selected,
            "label": device["label"],
            "status": device["status"],
            "sample_rate_hz": device["sample_rate_hz"],
            "bit_depth": device["bit_depth"],
            "latency_ms": device["latency_ms"],
            "route": device["route"],
            "hotplug_poll_ms": payload["hotplug_poll_ms"],
            "persisted": "dist/device-matrix.json",
        }

    def _do_permission_check(self, params: dict[str, Any]) -> dict[str, Any]:
        self.permission_checked = True
        required = [spec.key for spec in device_permissions() if self.input in spec.required_for]
        granted = [key for key in required if self.permission_grants.get(key)]
        return {
            "checked": True,
            "required": required,
            "granted": granted,
            "pending": [key for key in required if key not in granted],
            "all_granted": len(required) == len(granted),
            "runtime_note": "Browser prompts microphone permission; native Android declares USB/Bluetooth/audio permissions.",
        }

    def _do_permission_grant(self, params: dict[str, Any]) -> dict[str, Any]:
        key = str(params.get("key", "record_audio"))
        known = {spec.key for spec in device_permissions()}
        if key not in known:
            raise ValueError(f"unknown permission: {key}")
        granted = bool(params.get("granted", True))
        self.permission_grants[key] = granted
        self.permission_checked = True
        if not granted and key == "record_audio":
            self.audio["mic_armed"] = False
            self.milestones.discard("mic.armed")
        return {"key": key, "granted": granted, "runtime_grants": dict(self.permission_grants)}

    def _do_audio_start(self, params: dict[str, Any]) -> dict[str, Any]:
        sample_rate = _clamp(params.get("sample_rate_hz", self.chain.sample_rate_hz), 8_000.0, 192_000.0, 96_000.0)
        frames = int(_clamp(params.get("frames_per_buffer", 128), 32, 1024, 128))
        from dsp_chain import direct_pipe_roundtrip_ms, route_locked

        self.chain.sample_rate_hz = sample_rate
        from oboe_exclusive import open_stream as open_oboe

        self.audio["oboe"] = open_oboe(sample_rate, frames)
        probe: dict[str, Any] = {}
        try:
            from local_audio_probe import alsa_cards

            probe = alsa_cards()
        except Exception:  # noqa: BLE001
            probe = {}

        # Echte Capture-Pipeline öffnen (Mic / USB-UAC2 / BLE-IPC). Ohne Hardware
        # bleibt der Ring eine Fixture – aber ausdrücklich gekennzeichnet.
        capture_info = self.open_capture(
            mode=str(params.get("capture", "auto")),
            sample_rate_hz=sample_rate,
            frames_per_buffer=frames,
            device=params.get("capture_device"),
            file_path=params.get("capture_file"),
        )

        self.audio.update(
            {
                "running": True,
                "sample_rate_hz": sample_rate,
                "frames_per_buffer": frames,
                "roundtrip_ms": direct_pipe_roundtrip_ms(sample_rate, frames),
                "route_locked": route_locked(sample_rate, frames),
                "pcm_ring_frames": len(self.pcm_ring),
                "capture": dict(self.capture),
            }
        )
        return {
            **{key: self.audio[key] for key in ("running", "sample_rate_hz", "frames_per_buffer", "roundtrip_ms", "route_locked")},
            "pipe": "127.0.0.1:8081",
            "block_ms": round((frames / sample_rate) * 1000.0, 3),
            "pcm_ring_frames": len(self.pcm_ring),
            "probe": {k: probe.get(k) for k in ("has_capture", "snd_nodes", "alsa_cards") if probe},
            "oboe": self.audio.get("oboe"),
            "capture": dict(self.capture),
            "capture_open": capture_info,
        }

    def open_capture(
        self,
        mode: str = "auto",
        sample_rate_hz: float | None = None,
        frames_per_buffer: int | None = None,
        device: str | None = None,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Öffnet (oder schließt) die echte Capture-Route für die aktuelle Input-Route."""
        rate = float(sample_rate_hz or self.audio["sample_rate_hz"])
        frames = int(frames_per_buffer or self.audio["frames_per_buffer"])
        info = self.capture_router.open(
            route=self.input,
            sample_rate_hz=rate,
            frames_per_buffer=frames,
            mode=mode,
            device=str(device) if device else None,
            file_path=file_path,
        )
        armed = bool(info.get("opened"))
        # Nur Backends, die beim Öffnen bereits streamen (ALSA/UAC2), werden hier
        # vorgefüllt; eine IPC-Pipe wartet auf ihren Client und darf nicht blocken.
        if armed and info.get("live_on_open"):
            self.pcm_ring = []
            for _ in range(4):
                block = self.capture_router.pull(frames, timeout_s=0.15)
                if block is None:
                    break
                self.pcm_ring.extend(block.pcm)
                self.capture_stats["real_blocks"] += 1
                self.capture_stats["by_backend"][block.source] = self.capture_stats["by_backend"].get(block.source, 0) + 1
            self.pcm_ring = self.pcm_ring[-frames * 4 :]
        if not self.pcm_ring:
            self.pcm_ring = test_signal("mouth_bass", frames=frames * 4, sample_rate_hz=rate)

        status = self.capture_router.status()
        real = bool(status["real_capture"])
        self.capture = {
            "armed": armed,
            "backend": str(info.get("backend", "none")),
            "route": self.input,
            "mode": mode,
            "device": str(info.get("device", "")),
            "real_capture": real,
            "blocks": int(status["blocks"]),
            "frames": int(status["frames"]),
            "reason": str(info.get("reason", "")),
            "available": armed,
            "transport": str(info.get("transport", "")),
            "pcm_ring_frames": len(self.pcm_ring),
            "pcm_ring_source": "live-capture" if (armed and real) else "fixture",
        }
        self.audio["capture"] = dict(self.capture)
        return info

    def _do_mic_arm(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.permission_grants.get("record_audio"):
            raise ValueError("record_audio permission not granted")
        device_id = str(params.get("device_id", f"{self.input}-default"))
        self.audio["mic_armed"] = True
        self.audio["mic_device"] = device_id
        # Arming öffnet die echte Capture-Route (Mic/UAC2/BLE), sofern Hardware
        # bzw. eine Client-Pipe vorhanden ist; sonst bleibt es bei der Fixture.
        if params.get("capture") is not None:
            self.open_capture(mode=str(params.get("capture")), device=device_id)
        elif self.audio["running"] and not self.capture["armed"]:
            self.open_capture(mode="auto", device=device_id)
        self.audio["capture"] = dict(self.capture)
        return {
            "armed": True,
            "device_id": device_id,
            "input": self.input,
            "monitor": "safe (What-U-Hear loopback)",
            "agc": False,
            "noise_suppression": False,
            "echo_cancellation": False,
            "capture": dict(self.capture),
        }

    def _do_preset_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preset_id = str(params.get("preset", self.preset["id"]))
        preset = next((item for item in PRESETS if item["id"] == preset_id), None)
        if preset is None:
            raise ValueError(f"unknown preset: {preset_id}")
        self.preset = dict(preset)
        self.chain.bpm = float(preset["bpm"])
        self.transport["loop_step_ms"] = quantize_step_ms(preset["bpm"], self.transport["loop_subdivision"])
        self.chain.set_xy(0, preset["drive"], 0.5)
        self.chain.set_xy(2, preset["filter"], 1.0 - preset["filter"])
        self.chain.set_xy(3, preset["delay"], preset["delay"])
        return {
            "preset": dict(self.preset),
            "bpm": self.chain.bpm,
            "step_16_ms": self.transport["loop_step_ms"],
            "kaoss": self.chain.state(),
        }

    def _do_kaoss_xy(self, params: dict[str, Any]) -> dict[str, Any]:
        module = int(_clamp(params.get("module", 0), 0, 3, 0))
        result = self.chain.set_xy(module, _clamp(params.get("x"), 0.0, 1.0, 0.0), _clamp(params.get("y"), 0.0, 1.0, 0.0))
        result["bpm"] = self.chain.bpm
        return result

    def _do_kaoss_freeze(self, params: dict[str, Any]) -> dict[str, Any]:
        module = int(_clamp(params.get("module", 0), 0, 3, 0))
        frozen = params.get("frozen")
        enabled = (not self.chain.frozen[module]) if frozen is None else bool(frozen)
        result = self.chain.freeze(module, enabled)
        result["frozen_any"] = any(self.chain.frozen)
        return result

    def _do_dsp_process(self, params: dict[str, Any]) -> dict[str, Any]:
        frames = int(_clamp(params.get("frames", self.audio["frames_per_buffer"]), 16, 4096, 128))
        sample_rate = _clamp(params.get("sample_rate_hz", self.audio["sample_rate_hz"]), 8_000.0, 192_000.0, 96_000.0)
        signal = params.get("signal")
        source = str(params.get("source", "auto")).lower()
        if source not in {"auto", "capture", "fixture"}:
            raise ValueError(f"unknown dsp source: {source}")

        block = self.acquire_capture_block(params, frames=frames, sample_rate=sample_rate, signal=signal, source=source)
        pcm = block.pcm
        if len(pcm) < frames:
            pcm = pcm + [0.0] * (frames - len(pcm))
        elif len(pcm) > frames:
            pcm = pcm[:frames]

        rate = float(block.sample_rate_hz or sample_rate)
        report = process_block(pcm, self.chain, sample_rate_hz=rate)
        provenance = block.provenance()
        self.dsp["blocks"] += 1
        self.dsp["kick808"] += int(report["kick808"])
        self.dsp["snare"] += int(report["snare"])
        self.dsp["hat"] += int(report["hat"])
        self.dsp["max_peak_dbfs"] = max(self.dsp["max_peak_dbfs"], float(report["output_peak_dbfs"]))
        self.dsp["last"] = report
        self.dsp["capture"] = provenance
        self.dsp["checksums"].append(report["checksum"])
        self.dsp["checksums"] = self.dsp["checksums"][-64:]
        if block.real:
            self.capture_stats["real_blocks"] += 1
        else:
            self.capture_stats["fixture_blocks"] += 1
        self.capture_stats["by_backend"][block.source] = self.capture_stats["by_backend"].get(block.source, 0) + 1
        return {
            "signal": str(signal) if signal else block.source,
            "source": block.source,
            "real_capture": bool(block.real),
            "capture": provenance,
            "report": report,
            "blocks": self.dsp["blocks"],
            "limiter_safe": float(report["output_peak_dbfs"]) <= LIMITER_THRESHOLD_DBFS + 1e-6,
            "capture_stats": dict(self.capture_stats),
        }

    def acquire_capture_block(
        self,
        params: dict[str, Any],
        frames: int,
        sample_rate: float,
        signal: Any = None,
        source: str = "auto",
    ) -> Any:
        """Block-Herkunft für ``dsp.process``.

        Reihenfolge: explizites PCM im Request -> Fixture (wenn ``signal`` gesetzt
        oder ``source=fixture``) -> echte Capture (Mic/USB-UAC2/BLE-IPC) ->
        gekennzeichnete Fixture als Fallback. So bleibt CI deterministisch, während
        auf echter Hardware echte Blöcke durch Limiter/Transient/Quad laufen.
        """
        from audio_capture import CaptureBlock

        explicit = params.get("pcm")
        if isinstance(explicit, list) and explicit:
            pcm = [float(value) for value in explicit[:frames]]
            return CaptureBlock(
                pcm=pcm,
                frames=len(pcm),
                sample_rate_hz=sample_rate,
                source="client_pcm",
                device="api-payload",
                real=True,
                note="PCM aus dem Request-Payload",
            )
        if source == "fixture" or (signal is not None and source == "auto"):
            return fixture_block(str(signal or "mouth_bass"), frames, sample_rate)
        block = self.capture_router.pull(frames, timeout_s=0.25) if self.capture["armed"] else None
        if block is None:
            fallback = fixture_block(str(signal or "mouth_bass"), frames, sample_rate)
            fallback.note = (
                "capture armed, aber kein Block angekommen"
                if self.capture["armed"]
                else "kein Capture-Backend offen (keine Hardware/keine Client-Pipe)"
            )
            return fallback
        return block

    def _do_pad_trigger(self, params: dict[str, Any]) -> dict[str, Any]:
        bank = str(params.get("bank", "A")).upper()[:1]
        slots = next((item["slots"] for item in SAMPLE_BANKS if item["bank"] == bank), None)
        if slots is None:
            raise ValueError(f"unknown sample bank: {bank}")
        slot = str(params.get("slot", slots[0])).upper()
        if slot not in slots:
            raise ValueError(f"unknown slot '{slot}' in bank {bank}")
        signal = PAD_SIGNAL[bank]
        report = process_block(test_signal(signal, frames=128, sample_rate_hz=self.chain.sample_rate_hz), self.chain, self.chain.sample_rate_hz)
        voice_frames = len(synthesize_808(self.chain.sample_rate_hz, 60.0)) if bank == "A" else 0
        entry = {
            "seq": self._seq + 1,
            "bank": bank,
            "slot": slot,
            "signal": signal,
            "transient": report["transient"]["kind"],
            "peak_dbfs": report["output_peak_dbfs"],
            "voice_frames": voice_frames,
            "t_ms": self.uptime_ms(),
        }
        self.pads.append(entry)
        self.dsp["blocks"] += 1
        self.dsp["kick808"] += int(report["kick808"])
        self.dsp["snare"] += int(report["snare"])
        self.dsp["hat"] += int(report["hat"])
        self.dsp["last"] = report
        return {"pad": entry, "quantize_ms": quantize_step_ms(self.chain.bpm), "total_pads": len(self.pads)}

    def _do_transport_record(self, params: dict[str, Any]) -> dict[str, Any]:
        running = bool(params.get("running", not self.transport["recording"]))
        self.transport["recording"] = running
        if running:
            self.transport["started_seq"] = self._seq + 1
            self.transport["stopped_seq"] = None
        else:
            self.transport["stopped_seq"] = self._seq + 1
        return {
            "recording": running,
            "started_seq": self.transport["started_seq"],
            "stopped_seq": self.transport["stopped_seq"],
            "blocks_captured": self.dsp["blocks"],
            "format": ".cypher",
        }

    def _do_loop_capture(self, params: dict[str, Any]) -> dict[str, Any]:
        subdivision = int(_clamp(params.get("subdivision", 16), 4, 64, 16))
        step_ms = quantize_step_ms(self.chain.bpm, subdivision)
        frames = max(1, int((step_ms * 4.0 / 1000.0) * self.chain.sample_rate_hz))
        self.transport.update(
            {
                "loop_captured": True,
                "loop_frames": frames,
                "loop_subdivision": subdivision,
                "loop_step_ms": step_ms,
            }
        )
        self.chain.set_loop_frames(frames)
        freeze_report = self.chain.freeze(0, True)
        self.transport["loop_frozen"] = True
        return {
            "loop_frames": frames,
            "loop_ms": round((frames / self.chain.sample_rate_hz) * 1000.0, 3),
            "subdivision": subdivision,
            "step_ms": step_ms,
            "bpm": self.chain.bpm,
            "looper": freeze_report,
            "reverse_available": True,
        }

    def _do_transcribe(self, params: dict[str, Any]) -> dict[str, Any]:
        text = str(params.get("text", "")).strip()
        feature: dict[str, Any] = {}
        if not text:
            signal = str(params.get("signal", "vocal"))
            from transcriber import transcribe_signal

            feature = transcribe_signal(signal, frames=256, sample_rate_hz=self.chain.sample_rate_hz)
            text = str(feature.get("text") or f"mouth {feature.get('dsp_kind', 'none').lower()} cypher take")
        entry = {
            "text": text,
            "language": "de",
            "offline": True,
            "buffer_ms": int(feature.get("buffer_ms", 500)) if feature else 500,
            "t_ms": self.uptime_ms(),
            "engine": feature.get("engine", "whisper-shim" if text else "feature-transcriber"),
        }
        self.lyrics["transcripts"].append(entry)
        self.lyrics["transcripts"] = self.lyrics["transcripts"][-32:]
        words = [word.strip(".,!?") for word in text.lower().split() if word.strip(".,!?")]
        rhymes: dict[str, list[str]] = {}
        if words:
            from rhyme_matrix import ensure_database, lookup

            ensure_database(self.db_path)
            for word in dict.fromkeys(words[-4:]):
                rhymes[word] = lookup(self.db_path, word)
        self.lyrics["rhymes"].update(rhymes)
        tflite: dict[str, Any] = {}
        try:
            from tflite_runtime import model_status

            tflite = model_status()
        except Exception:  # noqa: BLE001
            tflite = {"loaded": False}
        return {"transcript": entry, "rhymes": rhymes, "partials": len(self.lyrics["transcripts"]), "tflite": tflite}

    def _do_rhyme_lookup(self, params: dict[str, Any]) -> dict[str, Any]:
        from rhyme_matrix import ensure_database, lookup

        word = str(params.get("word", "beton")).strip() or "beton"
        ensure_database(self.db_path)
        rhymes = lookup(self.db_path, word)
        self.lyrics["rhymes"][word.lower()] = rhymes
        return {"word": word, "rhymes": rhymes, "db": str(self.db_path.relative_to(ROOT)), "offline": True}

    def _do_avatar_mode(self, params: dict[str, Any]) -> dict[str, Any]:
        mode = str(params.get("mode", self.avatar["mode"])).upper()
        if mode not in AVATAR_MODES:
            raise ValueError(f"unknown avatar mode: {mode}")
        self.avatar["mode"] = mode
        self.avatar["avatars"] = 1 if mode == "SOLO_HUD" else 8
        self.avatar["bones"] = 33
        self.avatar["fps"] = 60
        self.mode = "CYPHER" if mode in {"CYPHER_CIRCLE", "SOLO_HUD"} else mode
        from pose import skeleton_frame

        energy = abs(self.dsp["max_peak_dbfs"] + 3.2) / 40.0 if self.dsp["last"] else 0.4
        frame = skeleton_frame(self.uptime_ms(), energy=min(1.0, max(0.05, energy)), mode=mode)
        self.avatar["skeleton"] = frame
        payload = {key: self.avatar[key] for key in ("mode", "fps", "avatars", "bones")}
        payload["skeleton_bones"] = frame["bones"]
        payload["skeleton_source"] = frame["source"]
        return payload

    def _do_neurallift_generate(self, params: dict[str, Any]) -> dict[str, Any]:
        # -- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 2, P2-2)
        # Erzeugt ein echtes glTF-2.0-Mesh aus der aktuellen 33-Punkt-Pose
        # (Röhren über die MediaPipe-Bone-Topologie) und liest Vertices,
        # Triangles, Größe und Checksumme aus der geschriebenen Datei zurück.
        # `generate_ms` ist gemessen, nicht mehr die erfundene 1800.0.
        started = time.perf_counter()
        source = str(params.get("source", "camera_frame_0001.jpg"))
        self.avatar["generated_from"] = source
        digest = hashlib.sha256(f"{source}|{self.avatar['mode']}".encode("utf-8")).hexdigest()[:12]
        from engine_service import mesh_payload
        from midas import depth_from_luma

        payload = mesh_payload(
            t_ms=float(params.get("t_ms", 0.0)),
            energy=float(params.get("energy", 0.5)),
            mode=str(self.avatar["mode"]),
            seed=digest,
            write=True,
        )
        glb_rel = str(Path(str(payload["glb_path"])).relative_to(ROOT))
        midas = depth_from_luma(seed=source)
        self.avatar["midas"] = midas
        self.avatar.update({
            "glb": payload["glb"],
            "glb_path": glb_rel,
            "glb_bytes": payload["glb_bytes"],
            "glb_sha256": payload["sha256"],
            "vertices": payload["vertices"],
            "lod0_tris": payload["lod0_tris"],
            "lod1_tris": 0,
            "rig_bones": payload["rig_bones"],
            "rigged": True,
            "fallback": True,
        })
        return {
            "glb": payload["glb"],
            "source": source,
            "vertices": payload["vertices"],
            "lod0_tris": payload["lod0_tris"],
            "lod1_tris": 0,
            "rig_bones": payload["rig_bones"],
            "rigged": True,
            "generate_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "fallback": True,
            "offline": True,
            "inference": False,
            "glb_bytes": payload["glb_bytes"],
            "glb_path": glb_rel,
            "glb_sha256": payload["sha256"],
            "magic": payload["magic"],
            "landmarks": payload["landmarks"],
            "midas": midas,
            "note": payload["note"],
        }

    def _do_session_export(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = self.export_payload()
        persist = bool(params.get("persist", True))
        path = None
        if persist:
            path = self.persist_session(payload)
        return {
            "session": payload,
            "checksum": payload["checksum"],
            "chain_length": payload["chain_length"],
            "params_recorded": payload["params_recorded"],
            "persisted": str(path.relative_to(ROOT)) if path else None,
            "store": str(SESSION_STORE.relative_to(ROOT)),
            "latest": str((SESSION_STORE / "latest.cypher.json").relative_to(ROOT)) if persist else None,
            "sessions": len(self.list_sessions()),
        }

    def persist_session(self, payload: dict[str, Any] | None = None) -> Path:
        SESSION_STORE.mkdir(parents=True, exist_ok=True)
        body = dict(payload or self.export_payload())
        body["persisted_at"] = round(time.time(), 3)
        body["persisted_from"] = {"app": "kaoss-one-app", "version": self.version, "uptime_ms": self.uptime_ms()}
        path = SESSION_STORE / f"{body['checksum'][:16]}.cypher.json"
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        latest = SESSION_STORE / "latest.cypher.json"
        latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        return path

    def load_session(self, path: Path | str | None = None) -> dict[str, Any]:
        target = Path(path) if path else SESSION_STORE / "latest.cypher.json"
        return json.loads(target.read_text(encoding="utf-8"))

    def list_sessions(self) -> list[dict[str, Any]]:
        """Session-Store-Inventar (``dist/sessions/*.cypher.json``)."""
        if not SESSION_STORE.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(SESSION_STORE.glob("*.cypher.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            stat = path.stat()
            rows.append(
                {
                    "file": path.name,
                    "path": str(path.relative_to(ROOT)),
                    "bytes": stat.st_size,
                    "modified": round(stat.st_mtime, 3),
                    "latest": path.name == "latest.cypher.json",
                    "checksum": payload.get("checksum"),
                    "chain_length": payload.get("chain_length"),
                    "preset": payload.get("preset"),
                    "input": payload.get("input"),
                    "bpm": payload.get("bpm"),
                    "params_recorded": sum(1 for event in payload.get("action_chain") or [] if event.get("params")),
                }
            )
        rows.sort(key=lambda row: (row["modified"], row["file"]), reverse=True)
        return rows

    def restore_session(self, payload: dict[str, Any], source: str = "") -> dict[str, Any]:
        """State aus einer ``.cypher``-Datei wiederherstellen (App-Neustart).

        Das Event-Log bleibt bewusst leer: die neue Sitzung zählt wieder bei seq 1,
        damit Export-Checksummen deterministisch bleiben. Die alte Kette steht als
        ``restored.actions`` und über ``/api/session/latest`` weiterhin zur Verfügung.
        """
        with self._lock:
            fields: list[str] = []
            input_id = payload.get("input")
            if input_id in INPUTS:
                self.input = str(input_id)
                fields.append("input")

            permissions = payload.get("permissions")
            if isinstance(permissions, list) and permissions:
                for item in permissions:
                    if isinstance(item, dict) and item.get("key"):
                        self.permission_grants[str(item["key"])] = bool(item.get("granted"))
                self.permission_checked = True
                fields.append("permissions")

            kaoss = payload.get("kaoss") or {}
            modules = kaoss.get("modules") or []
            for module in modules:
                index = module.get("index")
                if not isinstance(index, int) or not 0 <= index <= 3:
                    continue
                self.chain.frozen[index] = False
                self.chain.set_xy(index, float(module.get("x") or 0.0), float(module.get("y") or 0.0))
                if bool(module.get("frozen")):
                    self.chain.freeze(index, True)
            if kaoss.get("bpm"):
                self.chain.bpm = float(kaoss["bpm"])
            if modules:
                fields.append("kaoss")

            preset = next((item for item in PRESETS if item["id"] == payload.get("preset")), None)
            if preset:
                self.preset = dict(preset)
                fields.append("preset")

            audio = payload.get("audio") or {}
            for key in ("sample_rate_hz", "frames_per_buffer", "roundtrip_ms", "route_locked", "mic_armed", "mic_device", "monitor_db"):
                if key in audio:
                    self.audio[key] = audio[key]
            self.audio["running"] = bool(audio.get("running"))
            if audio.get("sample_rate_hz"):
                self.chain.sample_rate_hz = float(audio["sample_rate_hz"])
            if audio:
                fields.append("audio")

            transport = payload.get("transport") or {}
            for key in ("recording", "loop_captured", "loop_frames", "loop_subdivision", "loop_step_ms"):
                if key in transport:
                    self.transport[key] = transport[key]
            if transport:
                fields.append("transport")

            dsp = payload.get("dsp") or {}
            for key in ("blocks", "kick808", "snare", "hat", "max_peak_dbfs", "last", "capture"):
                if key in dsp:
                    self.dsp[key] = dsp[key]
            if dsp:
                fields.append("dsp")

            pads = payload.get("pads")
            if isinstance(pads, list) and pads:
                self.pads = [dict(pad) for pad in pads]
                fields.append("pads")

            lyrics = payload.get("lyrics")
            if isinstance(lyrics, dict) and lyrics:
                self.lyrics.update(lyrics)
                fields.append("lyrics")

            avatar = payload.get("avatar")
            if isinstance(avatar, dict) and avatar:
                self.avatar.update(avatar)
                fields.append("avatar")

            if payload.get("profile"):
                self.profile = str(payload["profile"])
                fields.append("profile")

            # Nur informativ: Ein Restore lädt den Zustand, aber keine Berechtigungen
            # für die Reihenfolge-Guards. Nach einem Neustart muss die Kette
            # (input.select -> … -> mic.arm) erneut gegangen oder per
            # ``/api/session/replay`` wiederholt werden.
            resumed = bool(self.audio["running"] and self.audio["mic_armed"] and payload.get("chain_length"))

            self.restored = {
                "ok": True,
                "imported": True,
                "source": source,
                "checksum": payload.get("checksum"),
                "chain_length": int(payload.get("chain_length") or 0),
                "actions": [event.get("action") for event in payload.get("action_chain") or []],
                "params_recorded": sum(1 for event in payload.get("action_chain") or [] if event.get("params")),
                "fields": fields,
                "resumed": resumed,
                "restored_at": round(time.time(), 3),
                "persisted_at": payload.get("persisted_at"),
                "version": payload.get("version"),
            }
            return dict(self.restored)

    def inspect_store(self) -> dict[str, Any]:
        """Beim Boot die letzte Sitzung *anzeigen*, ohne den frischen State zu ändern.

        Der One-App-Server startet deterministisch (Preset 90s_tape, leere Kette);
        die persistierte Sitzung liegt als ``state["restored"]`` und über
        ``/api/session/latest`` bereit und wird auf Wunsch explizit importiert
        (``/api/session/restore``) oder erneut ausgeführt (``/api/session/replay``).
        """
        latest = SESSION_STORE / "latest.cypher.json"
        if not latest.is_file():
            self.restored = {"ok": False, "reason": "no persisted session", "source": "", "resumed": False}
            return dict(self.restored)
        try:
            payload = self.load_session(latest)
        except (OSError, json.JSONDecodeError) as exc:
            self.restored = {"ok": False, "reason": f"unreadable session: {exc}", "source": str(latest), "resumed": False}
            return dict(self.restored)
        chain = payload.get("action_chain") or []
        kaoss = payload.get("kaoss") or {}
        self.restored = {
            "ok": True,
            "imported": False,
            "source": str(latest.relative_to(ROOT)),
            "checksum": payload.get("checksum"),
            "version": payload.get("version"),
            "persisted_at": payload.get("persisted_at"),
            "chain_length": int(payload.get("chain_length") or 0),
            "actions": [event.get("action") for event in chain],
            "params_recorded": sum(1 for event in chain if event.get("params")),
            "preset": payload.get("preset"),
            "bpm": payload.get("bpm"),
            "input": payload.get("input"),
            "kaoss": kaoss,
            "dsp_blocks": int((payload.get("dsp") or {}).get("blocks") or 0),
            "pads": len(payload.get("pads") or []),
            "transcripts": len((payload.get("lyrics") or {}).get("transcripts") or []),
            "avatar": (payload.get("avatar") or {}).get("mode"),
            "glb": (payload.get("avatar") or {}).get("glb"),
            "restored_at": round(time.time(), 3),
            "resume_hint": "POST /api/session/restore (State) oder /api/session/replay (Kette erneut ausführen)",
        }
        return dict(self.restored)

    def restore_from_store(self) -> dict[str, Any] | None:
        """Explizit: letzte persistierte Sitzung in den Live-State importieren."""
        latest = SESSION_STORE / "latest.cypher.json"
        if not latest.is_file():
            self.restored = {"ok": False, "reason": "no persisted session", "source": "", "resumed": False}
            return None
        try:
            payload = self.load_session(latest)
        except (OSError, json.JSONDecodeError) as exc:
            self.restored = {"ok": False, "reason": f"unreadable session: {exc}", "source": str(latest), "resumed": False}
            return dict(self.restored)
        return self.restore_session(payload, source=str(latest.relative_to(ROOT)))

    def replay_cypher(self, payload: dict[str, Any], strict: bool = True, reset: bool = True) -> dict[str, Any]:
        """Ketten-Replay aus ``.cypher``: Re-Import *mit* Parametern + erneute Ausführung.

        Ältere Exporte ohne ``params`` werden weiter akzeptiert (dann nur die
        Aktionsnamen); der Report weist das als ``params_restored=False`` aus.
        """
        chain = payload.get("action_chain") or []
        script: list[dict[str, Any]] = []
        params_events = 0
        for event in chain:
            action = event.get("action")
            if not action or action == "chain.reset":
                continue
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if params:
                params_events += 1
            script.append({"action": str(action), **params})
        params_restored = params_events > 0
        if not script:
            script = [dict(step) for step in FULL_CHAIN_SCRIPT]

        # Während des Replays darf kein Boot-Restore dazwischenfunken, sonst wäre
        # die Checksum-Vergleichbarkeit dahin.
        previous_restore = self.restore_on_boot
        self.restore_on_boot = False
        try:
            if reset:
                self.dispatch("chain.reset", {}, strict=False)
            report = self.run_script(script, strict=strict)
        finally:
            self.restore_on_boot = previous_restore
        replayed = self.export_payload()
        original_checksum = payload.get("checksum")
        drift = {
            "chain_length": {
                "expected": int(payload.get("chain_length") or 0),
                "replayed": int(report["chain"]["length"]),
            },
            "statuses": [
                {"seq": item["seq"], "action": item["action"], "status": item["status"]}
                for item in report["results"]
                if item["status"] != "OK"
            ],
        }
        return {
            "ok": report["ok"],
            "steps": report["steps"],
            "actions": report["actions"],
            "blocked": report["blocked"],
            "params_restored": params_restored,
            "params_events": params_events,
            "source": {
                "checksum": original_checksum,
                "chain_length": int(payload.get("chain_length") or 0),
                "version": payload.get("version"),
                "preset": payload.get("preset"),
                "input": payload.get("input"),
            },
            "replay_checksum": replayed["checksum"],
            "checksum_match": bool(original_checksum) and replayed["checksum"] == original_checksum,
            "drift": drift,
            "chain": report["chain"],
            "results": report["results"],
            "final_state": report["final_state"],
        }

    def _do_chain_reset(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            length = len(self.events)
            self.events = []
            self._seq = 0
            self.reset_state()
        return {"reset": True, "cleared_events": length}

    # ------------------------------------------------------------------ #
    # export
    # ------------------------------------------------------------------ #
    def export_payload(self, preset: str | None = None, selected_input: str | None = None) -> dict[str, Any]:
        with self._lock:
            snapshot = self.state()
            preset_id = preset or self.preset["id"]
            input_id = selected_input if selected_input in INPUTS else self.input
            bpm = next((item["bpm"] for item in PRESETS if item["id"] == preset_id), self.chain.bpm)
            chain_payload = [
                {
                    key: event.get(key)
                    for key in ("seq", "t_ms", "action", "engine", "port", "status", "latency_ms", "params")
                }
                for event in self.events
            ]
            # Checksum only over timing-independent fields: the same performance
            # always yields the same .cypher hash, which CI can assert on.
            canonical_chain = [
                {key: event[key] for key in ("seq", "action", "engine", "port", "status")}
                for event in self.events
            ]
            canonical = json.dumps(
                {
                    "chain": canonical_chain,
                    "kaoss": snapshot["kaoss"],
                    "dsp_blocks": self.dsp["blocks"],
                    "pads": [{key: pad[key] for key in ("bank", "slot", "transient")} for pad in self.pads],
                    "preset": preset_id,
                    "input": input_id,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            return {
                "format": ".cypher",
                "version": self.version,
                "created_offline": True,
                "zero_cloud": True,
                "profile": self.profile,
                "preset": preset_id,
                "input": input_id,
                "bpm": bpm,
                "limiter_dbfs": LIMITER_THRESHOLD_DBFS,
                "stems": ["vocal", "mouth_808", "kaoss_fx", "avatar_motion"],
                "sample_banks": SAMPLE_BANKS,
                "kaoss": snapshot["kaoss"],
                "transport": snapshot["transport"],
                "dsp": {key: value for key, value in self.dsp.items() if key != "checksums"},
                "pads": list(self.pads),
                "lyrics": snapshot["lyrics"],
                "avatar": snapshot["avatar"],
                "audio": snapshot["audio"],
                "permissions": snapshot["permissions"],
                "capture": dict(self.capture),
                "capture_stats": dict(self.capture_stats),
                "chain_length": len(chain_payload),
                "action_chain": chain_payload,
                "params_recorded": sum(1 for event in chain_payload if event.get("params")),
                "replayable": True,
                "checksum": checksum,
            }


_MILESTONE_SOURCES: dict[str, str] = {
    "input.select": "input.selected",
    "permission.check": "permission.checked",
    "permission.grant": "permission.granted",
    "audio.start": "audio.started",
    "mic.arm": "mic.armed",
    "dsp.process": "dsp.processed",
    "transport.record": "transport.recording",
    "avatar.mode": "avatar.mode",
}


def build_engine(db_path: Path = DB_PATH, restore: bool = False, inspect: bool = True) -> SessionEngine:
    """Engine bauen.

    ``inspect=True`` (Default) liest ``dist/sessions/latest.cypher.json`` beim Boot
    und legt die Zusammenfassung nach ``engine.restored`` (Neustart-Persistenz).
    ``restore=True`` importiert die persistierte Sitzung zusätzlich in den
    Live-State – deterministische Testläufe lassen das weg.
    """
    engine = SessionEngine(db_path=db_path)
    engine.restore_on_boot = bool(restore)
    engine.inspect_on_boot = bool(inspect)
    engine.dispatch("boot", {}, strict=False)
    return engine


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    import argparse

    parser = argparse.ArgumentParser(description="Kaoss session engine smoke run / .cypher replay")
    parser.add_argument("--replay", metavar="FILE", help="Kette aus einer .cypher.json erneut ausführen")
    parser.add_argument("--list-sessions", action="store_true", help="Session-Store-Inventar ausgeben")
    cli = parser.parse_args()

    if cli.list_sessions:
        engine = build_engine(restore=False)
        print(json.dumps(engine.list_sessions(), ensure_ascii=False, indent=2))
        raise SystemExit(0)

    if cli.replay:
        target = Path(cli.replay)
        if not target.is_absolute():
            target = ROOT / target
        engine = build_engine(restore=False)
        report = engine.replay_cypher(engine.load_session(target), strict=True)
        print(
            json.dumps(
                {
                    "ok": report["ok"],
                    "steps": report["steps"],
                    "params_restored": report["params_restored"],
                    "source_checksum": report["source"]["checksum"],
                    "replay_checksum": report["replay_checksum"],
                    "checksum_match": report["checksum_match"],
                    "blocked": report["blocked"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(0 if report["ok"] else 1)

    demo = build_engine()
    report = demo.run_script()
    print(json.dumps({"ok": report["ok"], "chain": report["chain"], "restored": demo.restored}, ensure_ascii=False, indent=2))
    for event in report["results"]:
        print(f"{event['seq']:>3} {event['action']:<20} {event['status']:<8} {event['latency_ms']:>7.3f}ms :{event['port']}")
