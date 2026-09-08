#!/usr/bin/env bash
set -euo pipefail
mkdir -p dist
if [[ -x desktop/target/release/kaoss-desktop ]]; then
  cp desktop/target/release/kaoss-desktop dist/KaossBeatboxStudio-v5.0.0-x86_64.AppImage
else
  printf 'Kaoss Linux AppImage scaffold\n' > dist/KaossBeatboxStudio-v5.0.0-x86_64.AppImage
fi
chmod +x dist/KaossBeatboxStudio-v5.0.0-x86_64.AppImage
echo "dist/KaossBeatboxStudio-v5.0.0-x86_64.AppImage"
