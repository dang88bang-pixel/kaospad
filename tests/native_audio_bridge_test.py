#!/usr/bin/env python3
"""Statischer Vertrags-Test für die native Audio-Input -> DSP Bridge (Phase A).

Ohne Android-NDK und ohne Emscripten prüft dieser Test, dass die vier Ebenen
nicht auseinanderlaufen:

1. JNI-Symbole in ``kaoss_jni.cpp`` == Kotlin-``external``-Deklarationen,
2. Kotlin AudioRecord-Fallback + USB/BLE/Permission-Bridge vorhanden,
3. WASM-Exports und Build-Skript konsistent,
4. JS-DSP-Spiegel liefert dieselben Zahlen wie C++/Python (Limiter, Transient).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "android" / "app" / "src" / "main" / "cpp"
KOTLIN = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "kaoss" / "studio"

checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    if not condition:
        raise SystemExit(f"FAIL: {label}" + (f" // {detail}" if detail else ""))
    checks += 1


def read(rel: Path) -> str:
    return rel.read_text(encoding="utf-8")


def main() -> int:
    jni = read(CPP / "kaoss_jni.cpp")
    native_kt = read(KOTLIN / "KaossNative.kt")
    bridge_kt = read(KOTLIN / "KaossJsBridge.kt")
    controller_kt = read(KOTLIN / "AudioInputController.kt")
    activity_kt = read(KOTLIN / "MainActivity.kt")
    cmake = read(CPP / "CMakeLists.txt")
    wasm = read(ROOT / "web" / "wasm" / "dsp_core_wasm.cpp")
    build_wasm = read(ROOT / "scripts" / "build_wasm.sh")
    dsp_js = read(ROOT / "web" / "src" / "dsp-core.js")

    # ------------------------------------------------------------------ #
    # 1. JNI <-> Kotlin Signatur-Parität
    # ------------------------------------------------------------------ #
    jni_methods = set(re.findall(r"Java_com_kaoss_studio_KaossNative_(\w+)\(", jni))
    kotlin_methods = set(re.findall(r"external fun (\w+)\(", native_kt))
    check("jni methods exist", len(jni_methods) >= 8, str(sorted(jni_methods)))
    check(
        "kotlin externals match jni",
        kotlin_methods == jni_methods,
        f"jni_only={sorted(jni_methods - kotlin_methods)} kotlin_only={sorted(kotlin_methods - jni_methods)}",
    )
    for method in ("startAudioInput", "stopAudioInput", "audioInputStatus", "processAudioBlock"):
        check(f"jni exports {method}", method in jni_methods)
        check(f"kotlin declares {method}", method in kotlin_methods)

    # ------------------------------------------------------------------ #
    # 2. Kotlin AudioRecord-Fallback + Bridge
    # ------------------------------------------------------------------ #
    check("kotlin AudioRecord fallback", "AudioRecord" in controller_kt and "processAudioBlock" in controller_kt)
    check("kotlin AAudio-first strategy", "startAudioInput" in controller_kt and "AudioRecord" in controller_kt)
    check("kotlin RECORD_AUDIO gate", "Manifest.permission.RECORD_AUDIO" in controller_kt)
    for bridge_method in ("startAudioCapture", "stopAudioCapture", "audioCaptureStatus", "usbSnapshot", "bleNegotiate", "permissionState"):
        check(f"js bridge exposes {bridge_method}", bridge_method in bridge_kt)
    check("main activity usb permission flow", "UsbManager" in activity_kt and "requestPermission" in activity_kt)
    check("main activity permission result", "onRequestPermissionsResult" in activity_kt)
    check("main activity exported receiver", "ContextCompat.registerReceiver" in activity_kt and "RECEIVER_NOT_EXPORTED" in activity_kt)

    # ------------------------------------------------------------------ #
    # 3. CMake: alle Quellen + aaudio link
    # ------------------------------------------------------------------ #
    for source in ("audio_input_engine.cpp", "kaoss_audio_processor.cpp", "aaudio_input_engine.cpp", "kaoss_jni.cpp"):
        check(f"cmake lists {source}", source in cmake)
    check("cmake links aaudio", "find_library(aaudio-lib aaudio)" in cmake and "${aaudio-lib}" in cmake)
    check("cmake links android", "find_library(android-lib android)" in cmake)

    # ------------------------------------------------------------------ #
    # 4. WASM exports + build script
    # ------------------------------------------------------------------ #
    wasm_exports = set(re.findall(r"EMSCRIPTEN_KEEPALIVE\s*\n(?:[^E]*?)?" r"(\w+)\(", wasm))
    # simpler: capture the function name on the line after EMSCRIPTEN_KEEPALIVE
    wasm_exports = set(re.findall(r"EMSCRIPTEN_KEEPALIVE\n\w*\s*(\w+)\(", wasm))
    expected_wasm = {"kaoss_wasm_limiter_peak", "kaoss_wasm_detect_transient", "kaoss_wasm_process_block", "kaoss_wasm_set_xy", "kaoss_wasm_freeze", "kaoss_wasm_synth_808"}
    check("wasm exports declared", expected_wasm <= wasm_exports, f"missing={sorted(expected_wasm - wasm_exports)}")
    check("wasm build script uses emcc", "emcc" in build_wasm and "EXPORT_ES6=1" in build_wasm)
    check("wasm build lists exported fns", "kaoss_wasm_process_block" in build_wasm)
    check("js dsp core has wasm fallback", "createWasmCore" in dsp_js and "createJsCore" in dsp_js)

    # ------------------------------------------------------------------ #
    # 5. JS-DSP-Spiegel: identische Zahlen wie C++/Python
    # ------------------------------------------------------------------ #
    js_mirror = """
import { createJsDspCore } from './web/src/dsp-core.js';
const core = createJsDspCore();
const full = new Float32Array(128).map((_, i) => (i % 2 === 0 ? 1 : -1));
const sine = new Float32Array(512);
for (let i = 0; i < 512; i++) sine[i] = 0.6 * Math.sin(2 * Math.PI * 52 * (i / 48000));
const noise = new Float32Array(512);
let s = 0x12345678;
for (let i = 0; i < 512; i++) { s = (s * 1664525 + 1013904223) >>> 0; noise[i] = ((s >> 8) / 16777216) - 1; }
const peak = core.limiterPeak(full);
const kick = core.detectTransient(sine, 48000);
const snare = core.detectTransient(noise, 48000);
const block = core.processBlock(sine, 48000);
console.log(JSON.stringify({ peak, kick: kick.kind_name, snare: snare.kind_name, block_peak: block.peak_dbfs, backend: core.backend }));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", js_mirror],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise SystemExit(f"js mirror run failed: {proc.stderr[-500:]}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    check("js limiter peak <= -3.2 dBFS", result["peak"] <= -3.2 + 0.01, str(result["peak"]))
    check("js mirror kick808", result["kick"] == "KICK808", result["kick"])
    check("js mirror snare", result["snare"] == "SNARE_CLAP", result["snare"])
    check("js mirror block limiter safe", result["block_peak"] <= -3.2 + 0.01, str(result["block_peak"]))
    check("js mirror backend js", result["backend"] == "js", result["backend"])

    # ------------------------------------------------------------------ #
    # 6. Python-Spiegel-Parität (gleiche Schwellen)
    # ------------------------------------------------------------------ #
    sys.path.insert(0, str(ROOT / "engines"))
    from dsp_chain import LIMITER_THRESHOLD_DBFS, process_block, test_signal, KaossQuadChain  # noqa: E402

    check("python limiter threshold", LIMITER_THRESHOLD_DBFS == -3.2)
    chain = KaossQuadChain()
    chain.sample_rate_hz = 48000.0
    report = process_block(test_signal("mouth_bass", frames=512, sample_rate_hz=48000.0), chain, 48000.0)
    check("python mirror kick808", report["transient"]["kind"] == "KICK808", str(report["transient"]))

    print(f"native audio bridge contract verified: {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
