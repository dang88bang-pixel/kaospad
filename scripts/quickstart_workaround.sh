#!/usr/bin/env bash
# quickstart_workaround.sh — Alles-ohne-⛔ Schnellstart (docs/ALTERNATIVE_LOESUNGSWEGE.md)
# Führt die vier Workaround-Schritte hintereinander, bricht bei fehlender Hardware sanft ab.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Kaoss Schnellstart-Workaround — alles ohne ⛔ ==="
echo "Datum $(date -u +%Y-%m-%d)  Branch $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo detached)"
echo ""

step() { echo ""; echo "━━ $1 ━━"; }

step "1/4 Open-Source-Modelle pullen (Whisper-tiny, MiDaS, MediaPipe)"
if [[ -x scripts/download_open_models.sh ]]; then
  ./scripts/download_open_models.sh --target dist/offline-models || {
    echo "download_open_models.sh fehlgeschlagen — Fallback Platzhalter"
    python3 engines/neurallift_360/scripts/download_weights.py --target=dist/offline-models || true
  }
else
  python3 engines/neurallift_360/scripts/download_weights.py --target=dist/offline-models || true
fi

step "2/4 Selbstsigniert bauen (CI_SIGNING=false / -Psigning=false)"
# Bevorzuge offline-Signer ohne JDK
if [[ -f scripts/build_signed_apk.py ]]; then
  echo "baue Offline-APK via Python/OpenSSL (kein Gradle/SDK nötig)"
  python3 scripts/build_signed_apk.py || echo "  build_signed_apk.py warn — weiter"
fi
# Gradle nur wenn vorhanden
if [[ -x android/gradlew ]]; then
  if command -v gradle >/dev/null 2>&1; then
    echo "gradle assembleDebug -Psigning=false"
    (cd android && gradle assembleDebug -Psigning=false --no-daemon 2>&1 | tail -n 30) || echo "  Gradle ohne SDK/Daemon — übersprungen (offline ok)"
  else
    echo "gradle nicht im PATH — nutze gradle/actions/setup-gradle in CI"
    echo "  lokal: sdkman install gradle 8.7  &&  gradle --no-daemon wrapper --gradle-version 8.7"
  fi
else
  echo "android/gradlew nicht ausführbar — CI nutzt gradle/actions/setup-gradle 8.7"
fi

step "3/4 Per ADB installieren (sideload, kein Store)"
if command -v adb >/dev/null 2>&1; then
  apk="$(ls -t dist/*.apk releases/*.apk android/app/build/outputs/apk/debug/*.apk 2>/dev/null | head -1 || true)"
  if [[ -n "${apk:-}" && -f "$apk" ]]; then
    echo "adb install $apk"
    adb install -r "$apk" || echo "  adb install fehlgeschlagen — Gerät/Emulator angeschlossen? (emulator -avd ... & scrcpy)"
  else
    echo "kein APK gefunden — sideload vorbereitet:"
    echo "  adb install app/build/outputs/apk/debug/app-debug.apk"
    echo "  adb install releases/KaossBeatboxStudio-v5.0.0-Universal-Signed.apk"
  fi
  echo "  Alternative ohne Store: F-Droid-Repo, GitHub Releases, itch.io"
else
  echo "adb nicht installiert — Emulator/Scrcpy Hinweis:"
  echo "  sudo apt install android-tools-adb scrcpy"
  echo "  adb devices  # Emulator mit audio-record-Mock"
  echo "  scrcpy        # Device-Mirroring für Tests"
fi

step "4/4 Audio-Loopback testen (Linux)"
if command -v pw-dump >/dev/null 2>&1; then
  echo "pw-dump vorhanden — zeige sinks"
  pw-dump 2>/dev/null | jq -r '.[] | select(.info.props["media.class"]=="Audio/Sink") | .info.props["node.name"]' 2>/dev/null | head -n 10 || echo "  keine sinks oder jq fehlt"
else
  echo "pw-dump nicht vorhanden — nutze ALSA probe"
  cat /proc/asound/cards 2>/dev/null | head -n 20 || echo "  keine /proc/asound/cards"
fi
echo ""
echo "DSP Loopback (deterministisch, offline):"
python3 - <<'PY' 2>/dev/null || echo "  python fallback fehlgeschlagen"
import sys
sys.path.insert(0,'engines')
from dsp_chain import test_signal, process_block, KaossQuadChain
chain=KaossQuadChain()
report=process_block(test_signal("mouth_bass"), chain)
print(f"  route=127.0.0.1:8081 roundtrip_ms={report['roundtrip_ms']} latency_ms={report['latency_ms']} peak={report['output_peak_dbfs']} dBFS")
PY
./scripts/test_audio_loopback.sh dsp 2>/dev/null | tail -n 20 || true

echo ""
echo "=== Fertig — alle ⛔ umgehbar für Dev/Test ==="
echo "Nächste Schritte:"
echo "  make test              # alle Gates (inkl. zero-cloud)"
echo "  make run-app           # http://127.0.0.1:8080 (One App, auto port)"
echo "  python3 engines/session_engine.py  # demo-chain in Konsole"
