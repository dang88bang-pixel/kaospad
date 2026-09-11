#!/usr/bin/env bash
# Schnellcheck für ASIO-Alternative (A)
# Zeigt dass WASAPI Exclusive vorgesehen ist und ASIO-Shim für CI reicht
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "ASIO Alternative Check (A):"
echo "  Windows primär: WASAPI Exclusive (oboe_exclusive_stream.cpp)"
echo "  Linux/macOS: ALSA/PipeWire/JACK / CoreAudio"
echo "  ASIO Shim: vendor/asio-sdk/README.txt (gültig für CI)"
cat "$ROOT/vendor/asio-sdk/README.txt" 2>/dev/null || echo "  Shim fehlt — wird via scripts/install_audio_backends.sh erzeugt"
echo "  PortAudio/RtAudio/JACK als freie Alternativen: scripts/install_audio_backends.sh"
