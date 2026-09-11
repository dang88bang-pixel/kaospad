#!/usr/bin/env bash
# Wrapper für J: Modelle in assets/tmp/ per Script herunterladen
# Spec erwähnt download_models.sh — delegiert an download_open_models.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/download_open_models.sh" "$@"
