#!/usr/bin/env bash
# Baut den C++-DSP-Kern als WebAssembly: dist/wasm/kaoss_dsp.wasm
#
# Toolchain-Reihenfolge (erste verfügbare gewinnt):
#   1. emcc            (Emscripten – Produktionspfad, auch für die PWA)
#   2. zig c++         (pip install ziglang – ein Wheel, voller wasm32-Target)
#   3. clang/clang++   (--target=wasm32 + wasm-ld)
#
# Derselbe Quelltext (kaoss_dsp_abi.cpp + Kern) wird auch nativ gebaut
# (tests/dsp_parity_harness.cpp) – darum rechnen Browser und Native identisch.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CPP="$ROOT/android/app/src/main/cpp"
OUT="$ROOT/dist/wasm"
mkdir -p "$OUT"

SOURCES=(
  "$CPP/audio_flinger_hook.cpp"
  "$CPP/dsp_transient_splitter.cpp"
  "$CPP/kaoss_quad_engine.cpp"
  "$CPP/kaoss_dsp_abi.cpp"
)

EXPORTS=(
  kaoss_dsp_abi_version
  kaoss_dsp_limiter_dbfs
  kaoss_dsp_checksum
  kaoss_dsp_brickwall_sample
  kaoss_dsp_brickwall_buffer
  kaoss_dsp_peak_dbfs
  kaoss_dsp_detect_transient
  kaoss_dsp_synthesize_808
  kaoss_quad_create
  kaoss_quad_destroy
  kaoss_quad_set_xy
  kaoss_quad_freeze
  kaoss_quad_read_state
  kaoss_quad_process
  # malloc/free: der Browser-Loader legt PCM-Puffer im linearen Speicher an.
  malloc
  free
)

EXPORT_ARGS=()
for name in "${EXPORTS[@]}"; do
  EXPORT_ARGS+=("-Wl,--export=$name")
done
EXPORT_ARGS+=("-Wl,--export-memory" "-Wl,--no-entry" "-Wl,--initial-memory=33554432" "-Wl,--max-memory=134217728")

# Kein Toolchain vorhanden? Ein pip-Wheel (ziglang, ~50 MB) bringt clang+wasm-ld
# komplett offline-fähig mit. Abschaltbar mit KAOSS_WASM_BOOTSTRAP=0.
bootstrap_ziglang() {
  [[ "${KAOSS_WASM_BOOTSTRAP:-1}" == "1" ]] || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c "import ziglang" >/dev/null 2>&1 && return 0
  echo "kein wasm32-Toolchain – installiere ziglang via pip (einmalig)…" >&2
  python3 -m pip install --quiet --break-system-packages ziglang >/dev/null 2>&1 \
    || python3 -m pip install --quiet ziglang >/dev/null 2>&1 \
    || return 1
  python3 -c "import ziglang" >/dev/null 2>&1
}

pick_toolchain() {
  if [[ -n "${KAOSS_WASM_TOOLCHAIN:-}" ]]; then
    echo "$KAOSS_WASM_TOOLCHAIN"
    return
  fi
  if command -v emcc >/dev/null 2>&1; then echo "emcc"; return; fi
  if command -v zig >/dev/null 2>&1; then echo "zig"; return; fi
  if python3 -c "import ziglang" >/dev/null 2>&1; then echo "ziglang"; return; fi
  if command -v clang++ >/dev/null 2>&1 && command -v wasm-ld >/dev/null 2>&1; then echo "clang"; return; fi
  if bootstrap_ziglang; then echo "ziglang"; return; fi
  echo "none"
}

TOOLCHAIN="$(pick_toolchain)"
if [[ "$TOOLCHAIN" == "none" ]]; then
  echo "kein wasm32-Toolchain gefunden (emcc | zig | clang+wasm-ld) und Bootstrap fehlgeschlagen." >&2
  echo "Manuell: python3 -m pip install --break-system-packages ziglang   (oder: make install-toolchains)" >&2
  exit 3
fi

echo "wasm toolchain: $TOOLCHAIN"
case "$TOOLCHAIN" in
  emcc)
    emcc -O3 -std=c++17 -DKAOSS_NO_EXCEPTIONS -fno-exceptions -fno-rtti -ffunction-sections -fdata-sections -I "$CPP" \
      "${SOURCES[@]}" -o "$OUT/kaoss_dsp.wasm" \
      "${EXPORT_ARGS[@]}" -Wl,--gc-sections -s STANDALONE_WASM -s ERROR_ON_UNDEFINED_SYMBOLS=1
    ;;
  zig)
    zig c++ -target wasm32-wasi -O3 -std=c++17 -DKAOSS_NO_EXCEPTIONS -fno-exceptions -fno-rtti -w \
      -ffunction-sections -fdata-sections -I "$CPP" "${SOURCES[@]}" -o "$OUT/kaoss_dsp.wasm" "${EXPORT_ARGS[@]}" -Wl,--gc-sections
    ;;
  ziglang)
    python3 -m ziglang c++ -target wasm32-wasi -O3 -std=c++17 -DKAOSS_NO_EXCEPTIONS -fno-exceptions -fno-rtti -w \
      -ffunction-sections -fdata-sections -I "$CPP" "${SOURCES[@]}" -o "$OUT/kaoss_dsp.wasm" "${EXPORT_ARGS[@]}" -Wl,--gc-sections
    ;;
  clang)
    clang++ --target=wasm32-wasi -O3 -std=c++17 -DKAOSS_NO_EXCEPTIONS -fno-exceptions -fno-rtti -w \
      -ffunction-sections -fdata-sections -I "$CPP" "${SOURCES[@]}" -o "$OUT/kaoss_dsp.wasm" "${EXPORT_ARGS[@]}" -Wl,--gc-sections
    ;;
esac

SIZE=$(stat -c%s "$OUT/kaoss_dsp.wasm" 2>/dev/null || stat -f%z "$OUT/kaoss_dsp.wasm")
SHA=$(python3 - "$OUT/kaoss_dsp.wasm" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())
PY
)

python3 - "$OUT/build-manifest.json" "$TOOLCHAIN" "$SIZE" "$SHA" "${EXPORTS[@]}" <<'PY'
import json, sys, time
out, toolchain, size, sha = sys.argv[1:5]
exports = sys.argv[5:]
json.dump(
    {
        "module": "kaoss_dsp.wasm",
        "toolchain": toolchain,
        "built_at": round(time.time(), 3),
        "bytes": int(size),
        "sha256": sha,
        "target": "wasm32",
        "cxx_standard": 17,
        "sources": [
            "android/app/src/main/cpp/audio_flinger_hook.cpp",
            "android/app/src/main/cpp/dsp_transient_splitter.cpp",
            "android/app/src/main/cpp/kaoss_quad_engine.cpp",
            "android/app/src/main/cpp/kaoss_dsp_abi.cpp",
        ],
        "exports": exports,
        "served_at": "/wasm/kaoss_dsp.wasm",
    },
    open(out, "w", encoding="utf-8"),
    indent=2,
)
PY

echo "wasm gebaut: dist/wasm/kaoss_dsp.wasm (${SIZE} B, sha256 ${SHA:0:12}…)"
echo "manifest:    dist/wasm/build-manifest.json"
# ---------------------------------------------------------------------------
# Optionales zweites Artefakt (Pfad aus main/PR#4): Emscripten-ES6-Modul für
# den Browser (web/wasm/dsp_core.mjs + .wasm) mit den kaoss_wasm_*-Exports.
# emcc ist nicht überall verfügbar – dann wird nur das Rohmodul oben gebaut
# und die UI nutzt den JS-Spiegel. Kein Fehler.
# ---------------------------------------------------------------------------
build_emscripten_module() {
  command -v emcc >/dev/null 2>&1 || {
    echo "emcc fehlt: web/wasm/dsp_core.mjs wird übersprungen (UI nutzt JS-Spiegel)." >&2
    return 0
  }
  local WEB_OUT="$ROOT/web/wasm"
  [[ -f "$WEB_OUT/dsp_core_wasm.cpp" ]] || {
    echo "web/wasm/dsp_core_wasm.cpp fehlt: Emscripten-Modul übersprungen." >&2
    return 0
  }
  mkdir -p "$WEB_OUT"
  emcc "$WEB_OUT/dsp_core_wasm.cpp" \
    "$CPP/audio_flinger_hook.cpp" \
    "$CPP/dsp_transient_splitter.cpp" \
    "$CPP/kaoss_audio_processor.cpp" \
    "$CPP/kaoss_quad_engine.cpp" \
    -I"$CPP" \
    -std=c++17 -O3 \
    -s WASM=1 -s MODULARIZE=1 -s EXPORT_ES6=1 -s ENVIRONMENT=web,worker \
    -s EXPORT_NAME=KaossDspCore \
    -s EXPORTED_FUNCTIONS='["_kaoss_wasm_limiter_peak","_kaoss_wasm_detect_transient","_kaoss_wasm_process_block","_kaoss_wasm_set_xy","_kaoss_wasm_freeze","_kaoss_wasm_synth_808","_malloc","_free"]' \
    -s EXPORTED_RUNTIME_METHODS='["ccall","cwrap","HEAPF32","HEAPU8","HEAP32","HEAPF64"]' \
    -s ALLOW_MEMORY_GROWTH=1 \
    -o "$WEB_OUT/dsp_core.mjs"
  echo "zusätzlich gebaut: web/wasm/dsp_core.mjs + web/wasm/dsp_core.wasm"
}

build_emscripten_module
