#!/usr/bin/env bash
# release_dry_run.sh — REAL-IMPLEMENTATION 2026-09-11
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[dry-run] make release-bundle"
make -C "$ROOT" release-bundle 2>&1 | tail -n 20
echo "[dry-run] verify"
python3 "$ROOT/scripts/verify_release_artifacts.py" 2>&1 | tail -n 20
python3 "$ROOT/scripts/generate_sbom.py" 2>&1 | tail -n 20
sha256sum "$ROOT/dist/"* 2>/dev/null | head -n 20 || true
echo "[dry-run] done"
