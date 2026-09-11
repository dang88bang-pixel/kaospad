#!/usr/bin/env bash
# Paketiert die PWA (web/) als Offline-ZIP. Versucht vorher den WASM-DSP-Build,
# fällt aber ohne Emscripten auf den reinen JS-Spiegel zurück (zero-cloud).
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p dist

# WASM-DSP-Kern bauen, wenn Emscripten verfügbar ist (sonst: JS-Spiegel).
WASM_BUILT=false
if command -v emcc >/dev/null 2>&1; then
  if ./scripts/build_wasm.sh; then
    WASM_BUILT=true
  fi
fi

# Build-Manifest: ehrlicher Nachweis, welcher DSP-Backend ins Paket wandert.
printf '{"name":"KaossBeatboxStudio","version":"5.0.0","wasm_built":%s,"dsp_fallback":"js-mirror"}\n' \
  "$WASM_BUILT" > web/build-info.json

(cd web && zip -qr ../dist/KaossBeatboxStudio-WebAssembly-Offline.zip .)
rm -f web/build-info.json

echo "dist/KaossBeatboxStudio-WebAssembly-Offline.zip (wasm_built=${WASM_BUILT})"
