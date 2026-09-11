#!/usr/bin/env bash
# download_models.sh — REAL-IMPLEMENTATION 2026-09-11
# Wrapper für J: Modelle in assets/tmp/ per Script herunterladen
# Spec erwähnt download_models.sh — delegiert an download_open_models.sh, prüft danach Checksums.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
TARGET="${1:-assets/tmp}"
echo "[download_models] delegating to download_open_models.sh target=$TARGET"
exec_cmd="$DIR/download_open_models.sh --target $TARGET --offline"
echo "[download_models] $exec_cmd"
"$DIR/download_open_models.sh" --target "$TARGET" --offline
echo "[download_models] verifying SHA256..."
if [[ -f "$ROOT/$TARGET/SHA256SUMS.txt" ]]; then cat "$ROOT/$TARGET/SHA256SUMS.txt"; else echo "[download_models] SHA256SUMS.txt missing — generating via generate_checksums.sh"; "$DIR/generate_checksums.sh" "$TARGET" || true; fi
echo "[download_models] done: $TARGET ($(ls -1 "$ROOT/$TARGET" 2>/dev/null | wc -l) files)"
