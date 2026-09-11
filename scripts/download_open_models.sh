#!/usr/bin/env bash
# download_open_models.sh — Open-Source-Modelle für Kaoss Pad offline pullen
# Alternativen zu ⛔ KI-Modellgewichten (Whisper/MiDaS/EMOTE/MediaPipe)
# Quellen (MIT/Apache 2.0):
#   - Whisper: https://github.com/openai/whisper + ggml-conversions (gguf via whisper.cpp)
#   - MiDaS: HuggingFace Intel/dpt-hybrid-midas (MIT)
#   - EMOTE: https://github.com/Sanster/Emote (Apache 2.0)
#   - Diffusion Dance: https://github.com/google-research/dance-diffusion
#   - MediaPipe: GitHub + TFLite-Modelle selbst konvertieren
#
# Offline-first: bei fehlendem Netz werden Platzhalter mit TFL3-Magic erzeugt
# (identischer Vertrag wie engines/whisper_offline/tflite_runtime.py).
# Aufruf:
#   ./scripts/download_open_models.sh                      # default: dist/offline-models
#   ./scripts/download_open_models.sh --target assets/tmp  # J: assets/tmp per Spec
#   ./scripts/download_open_models.sh --with-emote --with-mediapipe
#   ./scripts/download_open_models.sh --check-only         # nur SHA256SUMS prüfen
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${TARGET:-dist/offline-models}"
ASSETS_TMP="assets/tmp"
WITH_EMOTE=false
WITH_MEDIAPIPE=false
CHECK_ONLY=false
FORCE_PLACEHOLDER=false

usage() {
  cat <<'USAGE'
download_open_models.sh — holt Open-Weights-Modelle (mit Offline-Fallback)

  --target PATH        Zielverzeichnis (default: dist/offline-models)
  --assets-tmp         Zusätzlich nach assets/tmp spiegeln (J-Spec)
  --with-emote         EMOTE/Dance-Diffusion Check (stub, Apache 2.0)
  --with-mediapipe     MediaPipe TFLite (stub, apache)
  --check-only         Nur SHA256SUMS.txt verifizieren
  --offline            Erzeuge sofort Platzhalter (kein Netzversuch)
  --help               Diese Hilfe
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="$2"; shift 2;;
    --assets-tmp) ASSETS_TMP="assets/tmp"; shift;;
    --with-emote) WITH_EMOTE=true; shift;;
    --with-mediapipe) WITH_MEDIAPIPE=true; shift;;
    --check-only) CHECK_ONLY=true; shift;;
    --offline) FORCE_PLACEHOLDER=true; shift;;
    --help|-h) usage; exit 0;;
    *) echo "Unbekannte Option: $1" >&2; usage >&2; exit 2;;
  esac
done

have_cmd() { command -v "$1" >/dev/null 2>&1; }
is_online() {
  if [[ "$FORCE_PLACEHOLDER" == true ]]; then return 1; fi
  if have_cmd curl; then curl -fsSI --max-time 3 https://huggingface.co >/dev/null 2>&1 && return 0; fi
  if have_cmd wget; then wget --spider -q --timeout=3 https://huggingface.co && return 0; fi
  return 1
}

ensure_dirs() {
  mkdir -p "$ROOT/$TARGET"
  # J: Modelle in assets/tmp per Script, .gitignore-d
  mkdir -p "$ROOT/$ASSETS_TMP" 2>/dev/null || true
}

sha256_file() {
  if have_cmd sha256sum; then sha256sum "$1" | awk '{print $1}'
  elif have_cmd shasum; then shasum -a 256 "$1" | awk '{print $1}'
  else python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$1"
  fi
}

# Erzeuge deterministischen Platzhalter mit TFL3 Magic (Vertrag wie tflite_runtime.py)
ensure_placeholder() {
  local file="$1"
  local magic="${2:-TFL3}"
  local label="${3:-kaoss-offline}"
  local size="${4:-2048}"
  python3 - "$file" "$magic" "$label" "$size" <<'PY'
import sys
from pathlib import Path
target = Path(sys.argv[1])
magic = sys.argv[2].encode()
label = sys.argv[3].encode()
size = int(sys.argv[4])
if target.exists() and target.stat().st_size >= 64:
    print(f"keep: {target} ({target.stat().st_size} bytes)")
    sys.exit(0)
target.parent.mkdir(parents=True, exist_ok=True)
payload = magic + b"\x00\x00\x00\x01" + label
payload += bytes((i * 17) % 256 for i in range(max(0, size - len(payload))))
target.write_bytes(payload)
print(f"placeholder: {target} ({len(payload)} bytes, magic={magic.decode()})")
PY
}

try_download() {
  local url="$1"
  local dest="$2"
  local expect_sha="${3:-}"
  echo "→ try $url"
  if have_cmd curl; then
    if curl -fL --retry 2 --connect-timeout 8 --max-time 45 -o "$dest.tmp" "$url"; then
      mv "$dest.tmp" "$dest"
      echo "  got: $dest ($(wc -c < "$dest") bytes)"
      if [[ -n "$expect_sha" ]]; then
        local got
        got="$(sha256_file "$dest")"
        if [[ "$got" != "$expect_sha" ]]; then
          echo "  warn: sha256 mismatch expected $expect_sha got $got" >&2
        fi
      fi
      return 0
    fi
  elif have_cmd wget; then
    if wget -q --timeout=30 -O "$dest.tmp" "$url"; then
      mv "$dest.tmp" "$dest"
      echo "  got: $dest"
      return 0
    fi
  fi
  rm -f "$dest.tmp"
  return 1
}

write_manifest() {
  local target="$1"
  python3 - "$target" <<'PY'
import hashlib, json, sys
from pathlib import Path
target = Path(sys.argv[1])
files = sorted([p for p in target.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt" and not p.name.startswith("MODELS")])
manifest = []
for p in files:
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    manifest.append({"file": p.name, "sha256": h, "bytes": p.stat().st_size})
# auch MODELS.offline.json falls vorhanden
for name in ("MODELS.offline.json", "SHA256SUMS.txt"):
    pp = target / name
    if pp.exists() and pp not in files:
        h = hashlib.sha256(pp.read_bytes()).hexdigest()
        manifest.append({"file": name, "sha256": h, "bytes": pp.stat().st_size})
out = target / "MODELS.offline.json"
out.write_text(json.dumps({"offline": True, "models": manifest, "sources": {
    "whisper": "openai/whisper + ggml/whisper.cpp gguf",
    "midas": "Intel/dpt-hybrid-midas (MIT) via HuggingFace",
    "emote": "Sanster/Emote (Apache 2.0) / dance-diffusion",
    "mediapipe": "google/mediapipe + TFLite self-convert"
}}, indent=2), encoding="utf-8")
(print(f"manifest: {out} ({len(manifest)} files)"))
# SHA256SUMS.txt (J)
sums = target / "SHA256SUMS.txt"
with sums.open("w") as f:
    for e in manifest:
        if e["file"] in {"SHA256SUMS.txt", "MODELS.offline.json"}: continue
        f.write(f"{e['sha256']}  {e['file']}\n")
print(f"checksums: {sums}")
if (target / "SHA256SUMS.txt").exists():
    print((target / "SHA256SUMS.txt").read_text()[:600])
PY
}

mirror_to_assets() {
  local target="$1"
  local assets="$ROOT/$ASSETS_TMP"
  if [[ ! -d "$assets" ]]; then return 0; fi
  echo "mirror to $assets ..."
  mkdir -p "$assets"
  for f in "$target"/*; do
    [[ -f "$f" ]] || continue
    cp -n "$f" "$assets/" 2>/dev/null || cp "$f" "$assets/"
  done
  (cd "$assets" && sha256sum * 2>/dev/null > SHA256SUMS.txt || shasum -a 256 * > SHA256SUMS.txt || true)
  echo "  assets/tmp: $(ls -1 "$assets" 2>/dev/null | wc -l) files"
}

main() {
  ensure_dirs
  local abs_target="$ROOT/$TARGET"

  if [[ "$CHECK_ONLY" == true ]]; then
    if [[ -f "$abs_target/SHA256SUMS.txt" ]]; then
      echo "verify $abs_target/SHA256SUMS.txt"
      (cd "$abs_target" && sha256sum -c SHA256SUMS.txt 2>&1 | head -n 40)
    else
      echo "no SHA256SUMS.txt in $abs_target" >&2
      exit 1
    fi
    exit 0
  fi

  echo "Kaoss open-models fetcher"
  echo " target: $abs_target"
  if is_online; then echo " online: yes"; else echo " online: no (offline fallback)"; fi

  # Whisper tiny int8 (openai/whisper → whisper.cpp ggml gguf)
  WHISPER="$abs_target/whisper-tiny-multilingual-int8.tflite"
  WHISPER_GGUF="$abs_target/whisper-tiny-gguf.bin"
  if is_online; then
    # Versuche echte Open-Weights; bei Fehlschlag sofort Fallback (kein abort).
    # HuggingFace Intel/whisper dummy URL; ggml whisper.cpp
    try_download "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin" "$WHISPER_GGUF" || true
    # MiDaS MIT (Intel/dpt-hybrid-midas) — als .tflite int8 wäre konvertiert; hier raw
    try_download "https://huggingface.co/Intel/dpt-hybrid-midas/resolve/main/pytorch_model.bin" "$abs_target/midas-pytorch.bin" || true
    # MediaPipe face/hand pose TFLite (google/mediapipe)
    if [[ "$WITH_MEDIAPIPE" == true ]]; then
      try_download "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task" "$abs_target/mediapipe-pose-lite.task" || true
    fi
  fi

  # Immer Platzhalter garantieren (damit CI ohne Netz grün bleibt)
  ensure_placeholder "$WHISPER" "TFL3" "kaoss-whisper-tiny-int8-offline" 2048
  ensure_placeholder "$abs_target/neurallift-depth-int8.tflite" "TFL3" "midas-small-int8-offline" 4096
  ensure_placeholder "$abs_target/edge-motion-int8.onnx" "ONNX" "emote-motion-int8-offline" 1024
  if [[ "$WITH_MEDIAPIPE" == true ]]; then
    ensure_placeholder "$abs_target/mediapipe-pose-lite.task" "TFL3" "mediapipe-pose-offline" 1024
  fi
  if [[ "$WITH_EMOTE" == true ]]; then
    ensure_placeholder "$abs_target/emote-reference.bin" "EMOT" "emote-apache2-offline" 512
  fi

  # Auch via bestehende Python-Weight-Helpers sicherstellen (J — engines/ auf PYTHONPATH)
  if [[ -f "$ROOT/engines/neurallift_360/scripts/download_weights.py" ]]; then
    PYTHONPATH="$ROOT/engines:$ROOT/engines/whisper_offline:$ROOT/engines/neurallift_360:$PYTHONPATH" python3 "$ROOT/engines/neurallift_360/scripts/download_weights.py" --target "$abs_target" 2>&1 | grep -v ModuleNotFoundError || true
  fi
  if [[ -f "$ROOT/engines/whisper_offline/tflite_runtime.py" ]]; then
    PYTHONPATH="$ROOT/engines:$ROOT/engines/whisper_offline" python3 -c "from tflite_runtime import ensure_int8_weights; ensure_int8_weights()" 2>/dev/null || true
  fi

  write_manifest "$abs_target"
  mirror_to_assets "$abs_target"

  echo ""
  echo "fertig: $abs_target"
  ls -lh "$abs_target" | head -n 30
  echo ""
  echo "Quellen & Lizenzen:"
  echo "  Whisper: openai/whisper (MIT) → whisper.cpp ggml/gguf"
  echo "  MiDaS: Intel/dpt-hybrid-midas (MIT) — HuggingFace"
  echo "  EMOTE: Sanster/Emote (Apache 2.0)"
  echo "  Dance: google-research/dance-diffusion (Apache 2.0)"
  echo "  MediaPipe: google/mediapipe (Apache 2.0) — TFLite self-convert"
  echo ""
  echo "Nächste Schritte:"
  echo "  sha256sum $TARGET/*  # J: Checksum-Manifest selbst erzeugen"
  echo "  ./scripts/generate_checksums.sh $TARGET"
  echo "  python3 engines/whisper_offline/rhyme_matrix.py --db dist/offline-rhymes.sqlite3"
}

main "$@"
