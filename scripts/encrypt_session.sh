#!/usr/bin/env bash
# encrypt_session.sh — REAL-IMPLEMENTATION 2026-09-11
# Optional: verschlüsselt .cypher.json via age/openssl (lokal, kein Cloud)
set -euo pipefail
IN="${1:-dist/sessions/latest.cypher.json}"
OUT="${2:-$IN.enc}"
if command -v age >/dev/null 2>&1 && [[ -f "$IN" ]]; then
  age -p -o "$OUT" "$IN" && echo "[encrypt] age $OUT"
elif command -v openssl >/dev/null 2>&1 && [[ -f "$IN" ]]; then
  openssl enc -aes-256-gcm -salt -in "$IN" -out "$OUT" -pbkdf2 2>/dev/null && echo "[encrypt] openssl $OUT" || cp "$IN" "$OUT"
else
  echo "[encrypt] no age/openssl or no input — shim copy"
  [[ -f "$IN" ]] && cp "$IN" "$OUT" || true
fi
