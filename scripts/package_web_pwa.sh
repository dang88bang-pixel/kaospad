#!/usr/bin/env bash
set -euo pipefail
mkdir -p dist
(cd web && zip -qr ../dist/KaossBeatboxStudio-WebAssembly-Offline.zip .)
echo "dist/KaossBeatboxStudio-WebAssembly-Offline.zip"
