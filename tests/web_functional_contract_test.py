#!/usr/bin/env python3
"""Statischer Vertrags-Test für Web-UI, Audio-Engine und Aktionskette.

Prüft drei Ebenen:
  1. alle benötigten DOM-IDs sind in ``web/index.html`` vorhanden,
  2. Audio-Engine und ``app.js`` enthalten die Funktions-Token (WebAudio,
     Device-Matrix, Reime, XY, Presets, Export, Ketten-Dispatch),
  3. Parität zwischen Browser-Modul ``web/src/action-chain.js`` und
     Server-Modul ``engines/session_engine.py``: identischer Aktionskatalog,
     identische Engine-Ports und identische kanonische Kette – damit UI und
     Backend nicht auseinanderlaufen können.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web/index.html"
APP = ROOT / "web/src/app.js"
ENGINE = ROOT / "web/src/audio-engine.js"
CHAIN_JS = ROOT / "web/src/action-chain.js"
SW = ROOT / "web/sw.js"

sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))
from session_engine import ACTION_CATALOGUE, ENGINES, FULL_CHAIN_SCRIPT  # noqa: E402

REQUIRED_IDS = {
    "start-audio",
    "arm-mic",
    "trigger-808",
    "trigger-snare",
    "browser-device-select",
    "audio-state",
    "meter-fill",
    "meter-readout",
    "rhyme-word",
    "lookup-rhyme",
    "rhyme-output",
    "input-select",
    "permission-check",
    "portview-auto",
    "runtime-port",
    "runtime-base",
    "runtime-endpoints",
    "preset-select",
    "apply-preset",
    "export-session",
    "vault-state",
    "bank-grid",
    "live-log",
    # Aktions- & Interaktionskette
    "run-full-chain",
    "chain-reset",
    "chain-strict",
    "chain-state",
    "chain-length",
    "chain-seq",
    "chain-blocked",
    "chain-latency",
    "chain-total",
    "action-chain-log",
    "state-input",
    "state-route",
    "state-bpm",
    "state-transport",
    "state-peak",
    "state-limiter",
    "state-freeze",
    "state-loop",
    "state-avatar",
    "state-glb",
    "record-toggle",
    "loop-capture",
    "transport-state",
    "pad-grid",
    "avatar-mode",
    "avatar-apply",
    "neurallift-run",
    "avatar-state",
    "transcribe-input",
    "transcribe-run",
    "transcribe-output",
    "xy-pad",
    "xy-readout",
}
REQUIRED_ENGINE_TOKENS = {
    "class WebAudioCypherEngine",
    "getUserMedia",
    "enumerateDevices",
    "trigger808",
    "triggerSnare",
    "brickwallCurve",
    "createBiquadFilter",
    "createDelay",
    "createWaveShaper",
}
REQUIRED_APP_TOKENS = {
    "WebAudioCypherEngine",
    "refreshDeviceMatrix",
    "lookupRhymes",
    "applyXY",
    "BRIDGE: LOCALHOST IPC LIVE",
    "loadPresets",
    "exportSession",
    "freezeState",
    "loadRuntimeConfig",
    "/api/runtime",
    # Ketten-Integration
    "from './action-chain.js'",
    "dispatchAction",
    "runFullChain",
    "chainReducer",
    "FULL_CHAIN_SCRIPT",
    "formatChainLine",
    "renderChain",
    "renderPadGrid",
    "hydrateFromServer",
    "/api/action",
    "/api/state",
    "__KAOSS_CHAIN__",
}
REQUIRED_CHAIN_JS_TOKENS = {
    "export const ACTION_CATALOGUE",
    "export const FULL_CHAIN_SCRIPT",
    "export function chainReducer",
    "export async function runChain",
    "export function offlineDispatcher",
    "export function formatChainLine",
    "export function missingMilestones",
    "export function summarize",
    "LIMITER_DBFS = -3.2",
}


def slice_between(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    stop = source.index(end, begin)
    return source[begin:stop]


def js_actions(section: str) -> list[str]:
    return re.findall(r"action: '([^']+)'", section)


def main() -> int:
    index = INDEX.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    engine = ENGINE.read_text(encoding="utf-8")
    chain_js = CHAIN_JS.read_text(encoding="utf-8")
    sw = SW.read_text(encoding="utf-8")

    missing_ids = sorted(item for item in REQUIRED_IDS if f'id="{item}"' not in index)
    missing_engine = sorted(item for item in REQUIRED_ENGINE_TOKENS if item not in engine)
    missing_app = sorted(item for item in REQUIRED_APP_TOKENS if item not in app)
    missing_chain = sorted(item for item in REQUIRED_CHAIN_JS_TOKENS if item not in chain_js)
    if missing_ids or missing_engine or missing_app or missing_chain:
        raise SystemExit(
            f"missing ids={missing_ids} engine={missing_engine} app={missing_app} chain={missing_chain}"
        )

    if "./src/action-chain.js" not in sw:
        raise SystemExit("service worker does not cache the action chain module (offline PWA broken)")

    # Parität Browser-Modul <-> Server-Engine
    catalogue_section = slice_between(chain_js, "export const ACTION_CATALOGUE", "export const ACTION_BY_NAME")
    script_section = slice_between(chain_js, "export const FULL_CHAIN_SCRIPT", "export const SAMPLE_BANKS")
    js_catalogue = js_actions(catalogue_section)
    py_catalogue = [spec.action for spec in ACTION_CATALOGUE]
    if sorted(js_catalogue) != sorted(py_catalogue):
        raise SystemExit(
            "action catalogue drift: js_only="
            f"{sorted(set(js_catalogue) - set(py_catalogue))} py_only={sorted(set(py_catalogue) - set(js_catalogue))}"
        )

    js_script = js_actions(script_section)
    py_script = [step["action"] for step in FULL_CHAIN_SCRIPT]
    if js_script != py_script:
        raise SystemExit(f"chain script drift:\n js={js_script}\n py={py_script}")

    js_ports = dict(re.findall(r"(\w+): \{ port: (\d{4})", slice_between(chain_js, "export const ENGINES", "export const ACTION_CATALOGUE")))
    py_ports = {name: str(meta["port"]) for name, meta in ENGINES.items()}
    if js_ports != py_ports:
        raise SystemExit(f"engine port drift: js={js_ports} py={py_ports}")

    js_requires = dict(re.findall(r"action: '([^']+)'[^}]*requires: \[([^\]]*)\]", catalogue_section))
    for spec in ACTION_CATALOGUE:
        js_raw = js_requires.get(spec.action, "")
        js_needs = sorted(re.findall(r"'([^']+)'", js_raw))
        py_needs = sorted(spec.requires)
        if js_needs != py_needs:
            raise SystemExit(f"guard drift for {spec.action}: js={js_needs} py={py_needs}")

    print(
        "web functional audio/device/rhyme contract declared // "
        f"action chain parity: {len(py_catalogue)} actions, {len(py_script)} chain steps, {len(py_ports)} engine ports"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
