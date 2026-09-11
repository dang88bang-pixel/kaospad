#!/usr/bin/env bash
# sign_release_gpg.sh — GPG-Signatur für Release-Artefakte (L)
# Alternative: gpg --detach-sign -a <file> (kostenlos, lokaler Key)
# Erzeugt .asc für jede Datei im Release-Verzeichnis.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

TARGET="${1:-release-assets}"
KEYID="${2:-}"

if [[ "$TARGET" == "--help" || "$TARGET" == "-h" ]]; then
  cat <<'USAGE'
sign_release_gpg.sh [TARGET_DIR] [GPG_KEY_ID]
  Signiert jede Datei in TARGET_DIR mit gpg --detach-sign --armor

  TARGET_DIR   Verzeichnis (default: release-assets / dist)
  GPG_KEY_ID   Optional: Key ID / Email für -u

Voraussetzung: gpg vorhanden, Key lokal: gpg --gen-key
Beispiel: ./scripts/sign_release_gpg.sh release-assets
          ./scripts/sign_release_gpg.sh dist ABC123DEF
USAGE
  exit 0
fi

ABS="$ROOT/$TARGET"
if [[ ! -d "$ABS" ]]; then
  # Falls relativ ohne ROOT
  ABS="$(realpath -m "$TARGET" 2>/dev/null || echo "$TARGET")"
fi
if [[ ! -d "$ABS" ]]; then
  echo "Verzeichnis nicht gefunden: $TARGET" >&2
  exit 1
fi

if ! command -v gpg >/dev/null 2>&1; then
  echo "gpg not found — install gnupg" >&2
  echo "  sudo apt install gnupg" >&2
  exit 1
fi

# Wenn kein Key, zeige Hinweis aber erstelle SHA256 als Alternative (SBOM)
if ! gpg --list-secret-keys >/dev/null 2>&1 || [[ -z "$(gpg --list-secret-keys 2>/dev/null)" ]]; then
  echo "Kein GPG-Key gefunden. Erzeuge einen lokalen:" >&2
  echo "  gpg --gen-key   (RSA 4096, 2y, Name: Kaoss Offline)" >&2
  echo "Alternative: SHA256SUMS + sbom.json (bereits via scripts/generate_checksums.sh)" >&2
  echo "Fahre trotzdem fort — falls --batch ohne Key fehlschlägt, nutze SHA256." >&2
fi

count=0
for file in "$ABS"/*; do
  [[ -f "$file" ]] || continue
  [[ "$file" == *.asc ]] && continue
  [[ "$file" == *.sig ]] && continue
  echo "sign: $file"
  if [[ -n "$KEYID" ]]; then
    gpg --detach-sign --armor -u "$KEYID" "$file"
  else
    gpg --detach-sign --armor "$file"
  fi
  count=$((count+1))
  echo "  → $file.asc"
done

if [[ $count -eq 0 ]]; then
  echo "Keine Dateien in $ABS" >&2
  exit 1
fi

echo "ok: $count Signaturen in $ABS/*.asc"
ls -lh "$ABS"/*.asc | head -n 20

echo ""
echo "Verify: gpg --verify <file>.asc <file>"
echo "Oder: sha256sum -c $ABS/SHA256SUMS"
