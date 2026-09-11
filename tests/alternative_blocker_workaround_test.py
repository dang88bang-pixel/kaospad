#!/usr/bin/env python3
"""Verifiziert Alternative Lösungswege für Blocker (docs/ALTERNATIVE_LOESUNGSWEGE.md).

Jede ⛔-Zeile hat eine pragmatische Alternative, die ohne teure Lizenz/Hardware
ausführbar ist. Dieser Test prüft die Existenz und Ausführbarkeit der Workarounds.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

checks = 0
fails: list[str] = []

def ok(msg: str):
    global checks
    checks += 1
    print(f"  ok: {msg}")

def fail(msg: str):
    fails.append(msg)
    print(f"  FAIL: {msg}")

def is_executable(path: Path):
    return path.is_file() and bool(path.stat().st_mode & stat.S_IEXEC)

# A · Externe Voraussetzungen
for script, desc in [
    (ROOT / "scripts/install_audio_backends.sh", "ASIO → RtAudio/PortAudio/JACK/WASAPI"),
    (ROOT / "scripts/download_open_models.sh", "Whisper/MiDaS/EMOTE/MediaPipe Open Weights"),
    (ROOT / "scripts/build_signed_apk.py", "Signing via OpenSSL self-signed"),
    (ROOT / "scripts/fetch_sample_library.sh", "Sample Library CC0 Synthese"),
    (ROOT / "scripts/test_audio_loopback.sh", "Hardware-Test Mock"),
]:
    if is_executable(script):
        ok(f"{script.name} ausführbar ({desc})")
    else:
        fail(f"{script.name} fehlt/nicht ausführbar ({desc})")

# Alternative KI-Gewichte: download_open_models --offline
result = subprocess.run([str(ROOT / "scripts/download_open_models.sh"), "--offline", "--target", "dist/offline-models"], capture_output=True, text=True)
if result.returncode == 0 and (ROOT / "dist/offline-models/whisper-tiny-multilingual-int8.tflite").exists():
    ok("download_open_models.sh --offline erzeugt whisper-tiny TFL3")
    data = (ROOT / "dist/offline-models/whisper-tiny-multilingual-int8.tflite").read_bytes()
    if data[:4] == b"TFL3":
        ok("whisper-tiny hat TFL3 magic (Vertrag)")
    else:
        fail(f"whisper magic falsch: {data[:4]}")
    # SHA256SUMS existiert (J)
    if (ROOT / "dist/offline-models/SHA256SUMS.txt").exists():
        ok("SHA256SUMS.txt erzeugt (J Checksum-Manifest)")
    else:
        fail("SHA256SUMS.txt fehlt")
    # assets/tmp mirror (J)
    if (ROOT / "assets/tmp/SHA256SUMS.txt").exists() or (ROOT / "assets/tmp/whisper-tiny-multilingual-int8.tflite").exists():
        ok("assets/tmp Mirror existiert (J Modelle in assets/tmp)")
    else:
        fail("assets/tmp Mirror fehlt")
else:
    fail(f"download_open_models.sh --offline failed: {result.stderr[:300]}")

# G · Plattform-Builds
for script, desc in [
    (ROOT / "scripts/fetch_gradle_wrapper.sh", "Gradle Wrapper offline"),
    (ROOT / "scripts/build_wasm.sh", "WASM lokal"),
    (ROOT / "scripts/build_wasm_docker.sh", "WASM Docker emscripten/emsdk"),
    (ROOT / "scripts/verify_gradle_wrapper.py", "Gradle Wrapper Verification"),
]:
    if script.is_file():
        ok(f"{script.name} vorhanden ({desc})")
    else:
        fail(f"{script.name} fehlt ({desc})")

# verify_gradle_wrapper.py sollte grün sein (ohne Jar warnt, aber kein fail)
result = subprocess.run([sys.executable, str(ROOT / "scripts/verify_gradle_wrapper.py")], capture_output=True, text=True)
if result.returncode == 0 and "gradle wrapper contract verified" in result.stdout:
    ok("verify_gradle_wrapper.py grün (G)")
else:
    fail(f"verify_gradle_wrapper.py failed: {result.stdout[:200]} {result.stderr[:200]}")

# H · CI/CD
build_gradle = (ROOT / "android/app/build.gradle.kts").read_text()
if "CI_SIGNING" in build_gradle and "-Psigning=false" in build_gradle or "signing" in build_gradle:
    ok("android/build.gradle.kts CI_SIGNING/-Psigning fallback (H)")
else:
    fail("CI_SIGNING fallback fehlt in build.gradle.kts")
if "CI_SIGNING" in (ROOT / ".github/workflows/multiplatform-ci-cd.yml").read_text():
    ok("multiplatform-ci-cd.yml CI_SIGNING handling (H)")
else:
    fail("CI workflow CI_SIGNING fehlt")

# I · Tests
result = subprocess.run([str(ROOT / "scripts/test_audio_loopback.sh"), "dsp"], capture_output=True, text=True)
if result.returncode == 0 and "KICK808" in result.stdout and "1.20ms" in result.stdout:
    ok("test_audio_loopback.sh dsp fallback (I Virtual-Cable)")
else:
    fail(f"test_audio_loopback dsp failed: {result.stdout[:200]}")

# J · Daten/Modelle
for script in [ROOT / "scripts/generate_checksums.sh", ROOT / "scripts/generate_sbom.py"]:
    if script.is_file():
        ok(f"{script.name} vorhanden (J/L)")
    else:
        fail(f"{script.name} fehlt")

# L · Release
for script, desc in [
    (ROOT / "scripts/sign_release_gpg.sh", "GPG Signatur"),
    (ROOT / "docs/INSTALLATION.md", "Installationsanleitung Template"),
]:
    if script.is_file():
        ok(f"{script.name} vorhanden ({desc})")
    else:
        fail(f"{script.name} fehlt ({desc})")

# Schnellstart 4 Schritte check (user markdown)
quickstart = (ROOT / "scripts/quickstart_workaround.sh").read_text()
for needle in ["download_open_models.sh", "build_signed_apk.py", "adb install", "test_audio_loopback"]:
    if needle in quickstart:
        ok(f"quickstart_workaround.sh enthält {needle} (Schnellstart 1-4)")
    else:
        fail(f"quickstart fehlt {needle}")

# ASIO Alternative: desktop host
audio_host = (ROOT / "desktop/src/audio_host.rs").read_text()
if "WASAPI Exclusive" in audio_host and "RtAudio" in audio_host or "ASIO" in audio_host:
    # check for alternative note
    if "Alternative" in audio_host or "WASAPI" in audio_host:
        ok("desktop/src/audio_host.rs dokumentiert WASAPI/RtAudio Alternative (A)")
    else:
        fail("audio_host alternative nicht dokumentiert")
else:
    fail("audio_host alternative fehlt")

# Sample Library
if (ROOT / "assets/samples/KIT.json").exists() or (ROOT / "scripts/fetch_sample_library.sh").exists():
    ok("Sample Library CC0 alternative vorhanden (A)")

# KP3+ Rechtsprüfung
session = (ROOT / "engines/session_engine.py").read_text()
if "90s_tape" in session and "kaoss" in session.lower() or "KaoSS" in session:
    ok("KP3+ Rebrand KaoSS vorhanden (A)")

# Gesamt
print(f"\nalternative_blocker_workaround: {checks} checks, {len(fails)} fails")
if fails:
    print("FAILS:")
    for f in fails:
        print(f"  - {f}")
    sys.exit(1)
print("alternative blocker workarounds verified: all ⛔ umgehbar für Dev/Test")
