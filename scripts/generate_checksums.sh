#!/usr/bin/env bash
# generate_checksums.sh — Checksum-Manifest für Modelle/Assets (J)
# Alternative zu ⛔ Checksum-Manifest per Hand: sha256sum models/* > SHA256SUMS.txt
# Nutzt sha256sum oder python3 Fallback, zero-cloud.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

TARGET="${1:-dist/offline-models}"
MANIFEST="${2:-SHA256SUMS.txt}"

if [[ "$TARGET" == "--help" || "$TARGET" == "-h" ]]; then
  cat <<'USAGE'
generate_checksums.sh [TARGET_DIR] [MANIFEST_NAME]
  Erzeugt SHA256SUMS.txt für J: Modelle in assets/tmp per Script, .gitignore-d

  TARGET_DIR   Verzeichnis mit Modellen (default: dist/offline-models)
  MANIFEST     Dateiname (default: SHA256SUMS.txt im Zielverzeichnis)

Beispiele:
  ./scripts/generate_checksums.sh dist/offline-models
  ./scripts/generate_checksums.sh assets/tmp
  ./scripts/generate_checksums.sh dist/offline-models SHA256SUMS.txt
USAGE
  exit 0
fi

ABS="$ROOT/$TARGET"
if [[ ! -d "$ABS" ]]; then
  echo "Verzeichnis nicht gefunden: $ABS" >&2
  echo "Lege es an: mkdir -p $ABS" >&2
  exit 1
fi

OUT="$ABS/$MANIFEST"
echo "checksums: $ABS → $OUT"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$ABS" && sha256sum -- * 2>/dev/null | grep -v "$MANIFEST" > "$MANIFEST" || sha256sum -- * > "$MANIFEST")
elif command -v shasum >/dev/null 2>&1; then
  (cd "$ABS" && shasum -a 256 -- * 2>/dev/null | grep -v "$MANIFEST" > "$MANIFEST" || shasum -a 256 * > "$MANIFEST")
else
  python3 - "$ABS" "$MANIFEST" <<'PY'
import hashlib, sys
from pathlib import Path
target = Path(sys.argv[1]); manifest = sys.argv[2]
out = target / manifest
with out.open("w") as f:
    for p in sorted(target.iterdir()):
        if p.is_file() and p.name != manifest:
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            f.write(f"{h}  {p.name}\n")
print(f"python fallback: {out}")
PY
fi

echo "ok: $OUT ($(wc -l < "$OUT") files)"
cat "$OUT"
echo ""
echo "Verify: (cd $TARGET && sha256sum -c SHA256SUMS.txt)"
