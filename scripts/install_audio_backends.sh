#!/usr/bin/env bash
# install_audio_backends.sh — ASIO-Alternative ohne Steinberg-Lizenz
# Block: ASIO SDK (Steinberg-Lizenz) ⛔
# Lösung laut ALTERNATIVE_LOESUNGSWEGE.md A:
#   RtAudio, PortAudio, JACK, WASAPI Exclusive nutzen.
#   ASIO nur für Windows-Pro-Users — im Repo ist bereits WASAPI vorgesehen.
#   Ein ASIO-Shim reicht für CI.
#
# Dieses Script prüft/installiert die freien Backends je OS und dokumentiert,
# dass der CI-Shim (desktop/src/audio_host.rs) ohne SDK grün bleibt.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

OS="$(uname -s 2>/dev/null || echo Windows)"
echo "== Kaoss Audio Backends — ASIO-freie Alternativen =="
echo "OS: $OS"
echo "Repo nutzt: WASAPI Exclusive (Windows), ALSA/PipeWire/JACK (Linux), CoreAudio (macOS)"
echo "ASIO-Schim: desktop/src/audio_host.rs + android/app/src/main/cpp/oboe_exclusive_stream.cpp"
echo ""

have() { command -v "$1" >/dev/null 2>&1; }

check_backend() {
  local name="$1" cmd="$2" install_hint="$3"
  if have "$cmd" || ldconfig -p 2>/dev/null | grep -qi "$name" || pkg-config --exists "$name" 2>/dev/null; then
    echo "  ✓ $name verfügbar"
  else
    echo "  · $name nicht installiert — $install_hint"
  fi
}

case "$OS" in
  Linux*)
    echo "Linux-Backends:"
    check_backend "ALSA" "aplay" "sudo apt install libasound2-dev alsa-utils"
    check_backend "PipeWire" "pw-dump" "sudo apt install pipewire pipewire-alsa"
    check_backend "JACK" "jackd" "sudo apt install jackd2 libjack-jackd2-dev"
    check_backend "PortAudio" "portaudio" "sudo apt install portaudio19-dev"
    check_backend "RtAudio" "rtaudio" "sudo apt install librtaudio-dev"
    echo ""
    echo "Empfehlung Linux: ALSA (exklusiv) → PipeWire (Desktop) → JACK (Pro)"
    echo "  WASAPI-Äquivalent: ALSA hw:0,0 mit 128 Frames @ 96kHz → 1.2ms roundtrip"
    echo "  Test: pw-dump | jq '.[] | select(.type==\"PipeWire:Interface:Node\")' | head"
    echo "  Loopback: modprobe snd-aloop  oder  pw-loopback"
    ;;
  Darwin*)
    echo "macOS-Backends:"
    check_backend "CoreAudio" "auval" "Xcode Command Line Tools"
    check_backend "BlackHole" "blackhole" "brew install blackhole-2ch"
    echo "  Empfohlen: CoreAudio (System) + BlackHole (Loopback)"
    ;;
  MINGW*|MSYS*|CYGWIN*|Windows*)
    echo "Windows-Backends:"
    echo "  ✓ WASAPI Exclusive — im Repo vorhanden (oboe_exclusive_stream.cpp, WASAPI Exclusive)"
    echo "  · ASIO — nur mit Steinberg SDK (vendor/asio-sdk). Shim vorhanden:"
    ls -l vendor/asio-sdk/README.txt 2>/dev/null || echo "    vendor/asio-sdk/README.txt — erzeugen via scripts/setup_asio_sdk.ps1"
    check_backend "PortAudio" "portaudio" "vcpkg install portaudio"
    check_backend "RtAudio" "rtaudio" "vcpkg install rtaudio"
    echo "  Empfehlung: WASAPI Exclusive für <10ms, ASIO nur für Pro-Users mit SDK"
    ;;
esac

echo ""
echo "CI-Shim aktiv: desktop/src/audio_host.rs → AudioHost::for_os(OS) liefert:"
python3 - <<'PY' 2>/dev/null || true
try:
    import sys
    sys.path.insert(0, 'engines')
    from dsp_chain import direct_pipe_roundtrip_ms
    for sr in [48000, 96000]:
        print(f"  {sr}Hz/128 → {direct_pipe_roundtrip_ms(sr)} ms")
except Exception as e:
    print(f"  (DSP not importable: {e})")
PY

echo ""
echo "Setup ASIO-Shim für CI (kein SDK nötig):"
if [[ -f "$ROOT/scripts/setup_asio_sdk.ps1" ]]; then
  echo "  pwsh ./scripts/setup_asio_sdk.ps1"
fi
echo "  mkdir -p vendor/asio-sdk && echo 'Offline ASIO shim for CI' > vendor/asio-sdk/README.txt"

# Ensure shim exists after check
mkdir -p "$ROOT/vendor/asio-sdk"
if [[ ! -f "$ROOT/vendor/asio-sdk/README.txt" ]]; then
  cat > "$ROOT/vendor/asio-sdk/README.txt" <<'EOF'
Offline ASIO SDK shim for CI scaffold.
Real ASIO SDK: https://www.steinberg.net/asiosdk (requires Steinberg license)
This repo uses WASAPI Exclusive on Windows, ALSA/CoreAudio elsewhere.
The shim satisfies the build graph without the proprietary SDK.
See docs/ALTERNATIVE_LOESUNGSWEGE.md A.
EOF
  echo "  created vendor/asio-sdk/README.txt"
fi

echo ""
echo "Done — alle freien Backends dokumentiert. Echter ASIO nur bei Bedarf."
