#!/usr/bin/env bash
# build_wasm_docker.sh — WASM-DSP via Docker statt lokaler Emscripten-Installation
# Alternative zu ⛔ Emscripten/WASM lokal installieren.
# Nutzt emscripten/emsdk Docker-Image wie in ALTERNATIVE_LOESUNGSWEGE.md G beschrieben.
# Fallback: lokales emcc falls Docker nicht verfügbar.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

EMSDK_IMAGE="${EMSDK_IMAGE:-emscripten/emsdk:4.0.8}"
USE_DOCKER=true
if ! command -v docker >/dev/null 2>&1; then
  USE_DOCKER=false
fi
if [[ "${1:-}" == "--local" ]]; then USE_DOCKER=false; shift; fi
if [[ "${1:-}" == "--docker" ]]; then USE_DOCKER=true; shift; fi

if [[ "$USE_DOCKER" == true ]]; then
  echo "WASM build via Docker: $EMSDK_IMAGE"
  if ! docker image inspect "$EMSDK_IMAGE" >/dev/null 2>&1; then
    echo "pull $EMSDK_IMAGE ..."
    docker pull "$EMSDK_IMAGE" || { echo "docker pull failed — versuche lokales emcc"; USE_DOCKER=false; }
  fi
fi

if [[ "$USE_DOCKER" == true ]]; then
  docker run --rm -v "$ROOT:/src" -w /src "$EMSDK_IMAGE" bash -lc '
    set -e
    echo "emcc $(emcc --version | head -1)"
    ./scripts/build_wasm.sh
  '
else
  echo "WASM build lokal (emcc erforderlich)"
  if ! command -v emcc >/dev/null 2>&1; then
    echo "emcc not found. Installieren:" >&2
    echo "  docker: ./scripts/build_wasm_docker.sh --docker" >&2
    echo "  lokal: git clone https://github.com/emscripten-core/emsdk && ./emsdk install latest && ./emsdk activate latest" >&2
    echo "  fallback: web/src/dsp-core.js JS-Spiegel ist zahlen-identisch (zero-cloud)" >&2
    exit 1
  fi
  "$ROOT/scripts/build_wasm.sh"
fi

echo "built web/wasm/dsp_core.{mjs,wasm} (oder JS-Fallback aktiv)"
ls -lh "$ROOT/web/wasm/" 2>/dev/null | head -n 20 || echo "web/wasm/ leer — JS-Mirror aktiv"
