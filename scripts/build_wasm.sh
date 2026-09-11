#!/usr/bin/env bash
# Build the portable Kaoss DSP core as a standalone WASM module for the browser
# fallback. Requires Emscripten (emcc). Runs on the CI runner or a developer
# machine; the web UI degrades to the pure-JS DSP mirror when the module is
# absent (zero-cloud offline cache).
set -euo pipefail

cd "$(dirname "$0")/.."
CPP="android/app/src/main/cpp"
OUT="web/wasm"

command -v emcc >/dev/null 2>&1 || {
  echo "emcc not found: install Emscripten (https://emscripten.org) or skip WASM build." >&2
  exit 1
}

mkdir -p "$OUT"

emcc "$OUT/dsp_core_wasm.cpp" \
  "$CPP/audio_flinger_hook.cpp" \
  "$CPP/dsp_transient_splitter.cpp" \
  "$CPP/kaoss_audio_processor.cpp" \
  "$CPP/kaoss_quad_engine.cpp" \
  -I"$CPP" \
  -std=c++17 -O3 \
  -s WASM=1 \
  -s MODULARIZE=1 \
  -s EXPORT_ES6=1 \
  -s ENVIRONMENT=web,worker \
  -s EXPORT_NAME=KaossDspCore \
  -s EXPORTED_FUNCTIONS='["_kaoss_wasm_limiter_peak","_kaoss_wasm_detect_transient","_kaoss_wasm_process_block","_kaoss_wasm_set_xy","_kaoss_wasm_freeze","_kaoss_wasm_synth_808","_malloc","_free"]' \
  -s EXPORTED_RUNTIME_METHODS='["ccall","cwrap","HEAPF32","HEAPU8","HEAP32","HEAPF64"]' \
  -s ALLOW_MEMORY_GROWTH=1 \
  -o "$OUT/dsp_core.mjs"

echo "built web/wasm/dsp_core.mjs + web/wasm/dsp_core.wasm"
