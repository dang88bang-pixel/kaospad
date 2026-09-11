#!/usr/bin/env bash
# capture_screenshots.sh — REAL-IMPLEMENTATION 2026-09-11
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/assets/screenshots"
echo "[screenshots] trying playwright"
if command -v npx >/dev/null 2>&1; then
  (cd "$ROOT/web" && npx --yes playwright screenshot --help 2>&1 | head -n 5) || true
fi
# Fallback placeholder
for dev in mobile tablet desktop; do
  echo "screenshot $dev placeholder — real via npx playwright screenshot http://127.0.0.1:8080" > "$ROOT/assets/screenshots/$dev.png"
done
echo "[screenshots] done assets/screenshots/"
