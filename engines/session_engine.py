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
DB_PATH = ROOT / "dist" / "offline-rhymes.sqlite3"

# Importable both as top-level module (engines/ on sys.path) and via package path.
for _path in (str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / "whisper_offline")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

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
            self.avatar = {
                "mode": "CYPHER_CIRCLE",
                "fps": 60,
                "avatars": 8,
                "bones": 33,
                "glb": "procedural_default_avatar.glb",
                "lod0_tris": 45_000,
                "lod1_tris": 18_000,
                "rig_bones": 24,
                "fallback": True,
                "generated_from": None,
            }
            self.profile = "A"
            self.mode = "CYPHER"

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
        result = self._record(action, spec.engine, ok, latency, status, detail, strict)
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
                "detail": detail,
            }
            self.events.append(event)
            if len(self.events) > 4096:
                del self.events[: len(self.events) - 4096]
            return {**event, "state": self.state()}

    # ------------------------------------------------------------------ #
    # action handlers
    # ------------------------------------------------------------------ #
    def _do_boot(self, params: dict[str, Any]) -> dict[str, Any]:
        self.reset_state()
        return {"booted": True, "zero_cloud": True, "version": self.version, "endpoints_ready": sorted(ENGINES)}

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
        self.audio.update(
            {
                "running": True,
                "sample_rate_hz": sample_rate,
                "frames_per_buffer": frames,
                "roundtrip_ms": direct_pipe_roundtrip_ms(sample_rate, frames),
                "route_locked": route_locked(sample_rate, frames),
            }
        )
        return {
            **{key: self.audio[key] for key in ("running", "sample_rate_hz", "frames_per_buffer", "roundtrip_ms", "route_locked")},
            "pipe": "127.0.0.1:8081",
            "block_ms": round((frames / sample_rate) * 1000.0, 3),
        }

    def _do_mic_arm(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.permission_grants.get("record_audio"):
            raise ValueError("record_audio permission not granted")
        device_id = str(params.get("device_id", f"{self.input}-default"))
        self.audio["mic_armed"] = True
        self.audio["mic_device"] = device_id
        return {
            "armed": True,
            "device_id": device_id,
            "input": self.input,
            "monitor": "safe (What-U-Hear loopback)",
            "agc": False,
            "noise_suppression": False,
            "echo_cancellation": False,
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
        signal = str(params.get("signal", "mouth_bass"))
        frames = int(_clamp(params.get("frames", self.audio["frames_per_buffer"]), 16, 4096, 128))
        sample_rate = _clamp(params.get("sample_rate_hz", self.audio["sample_rate_hz"]), 8_000.0, 192_000.0, 96_000.0)
        pcm = params.get("pcm")
        if isinstance(pcm, list) and pcm:
            pcm = [float(value) for value in pcm[:frames]]
        else:
            pcm = test_signal(signal, frames=frames, sample_rate_hz=sample_rate)
        report = process_block(pcm, self.chain, sample_rate_hz=sample_rate)
        self.dsp["blocks"] += 1
        self.dsp["kick808"] += int(report["kick808"])
        self.dsp["snare"] += int(report["snare"])
        self.dsp["hat"] += int(report["hat"])
        self.dsp["max_peak_dbfs"] = max(self.dsp["max_peak_dbfs"], float(report["output_peak_dbfs"]))
        self.dsp["last"] = report
        self.dsp["checksums"].append(report["checksum"])
        self.dsp["checksums"] = self.dsp["checksums"][-64:]
        return {
            "signal": signal,
            "report": report,
            "blocks": self.dsp["blocks"],
            "limiter_safe": float(report["output_peak_dbfs"]) <= LIMITER_THRESHOLD_DBFS + 1e-6,
        }

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
        if not text:
            signal = str(params.get("signal", "vocal"))
            report = process_block(test_signal(signal, frames=256, sample_rate_hz=self.chain.sample_rate_hz), self.chain, self.chain.sample_rate_hz)
            text = f"mouth {report['transient']['kind'].lower()} cypher take"
        entry = {"text": text, "language": "de", "offline": True, "buffer_ms": 500, "t_ms": self.uptime_ms()}
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
        return {"transcript": entry, "rhymes": rhymes, "partials": len(self.lyrics["transcripts"])}

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
        return {key: self.avatar[key] for key in ("mode", "fps", "avatars", "bones")}

    def _do_neurallift_generate(self, params: dict[str, Any]) -> dict[str, Any]:
        source = str(params.get("source", "camera_frame_0001.jpg"))
        self.avatar["generated_from"] = source
        digest = hashlib.sha256(f"{source}|{self.avatar['mode']}".encode("utf-8")).hexdigest()[:12]
        return {
            "glb": f"neurallift_{digest}.glb",
            "source": source,
            "lod0_tris": self.avatar["lod0_tris"],
            "lod1_tris": self.avatar["lod1_tris"],
            "rig_bones": self.avatar["rig_bones"],
            "generate_ms": 1800.0,
            "fallback": True,
            "offline": True,
            "note": "procedural offline fallback; production path swaps in MiDaS/ZoeDepth + MediaPipe + GLB export",
        }

    def _do_session_export(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = self.export_payload()
        return {"session": payload, "checksum": payload["checksum"], "chain_length": payload["chain_length"]}

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
                {key: event[key] for key in ("seq", "t_ms", "action", "engine", "port", "status", "latency_ms")}
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
                "chain_length": len(chain_payload),
                "action_chain": chain_payload,
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


def build_engine(db_path: Path = DB_PATH) -> SessionEngine:
    engine = SessionEngine(db_path=db_path)
    engine.dispatch("boot", {}, strict=False)
    return engine


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    demo = build_engine()
    report = demo.run_script()
    print(json.dumps({"ok": report["ok"], "chain": report["chain"]}, ensure_ascii=False, indent=2))
    for event in report["results"]:
        print(f"{event['seq']:>3} {event['action']:<20} {event['status']:<8} {event['latency_ms']:>7.3f}ms :{event['port']}")
