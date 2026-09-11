#!/usr/bin/env bash
# fetch_sample_library.sh — Sample-Library Alternative ohne teure Lizenzen
# Block: Sample-Library ⛔ → CC0/Splice-Free: Freesound.org, SonusLab, KVR-Forum
#        plus eigene Synthese mit Csound/SuperCollider (hier: deterministische DSP-Synthese)
#
# Erzeugt offline sofort lizenzfreie Samples via Python-DSP (synthesize_808/snare/hat)
# und, falls gewünscht, versucht CC0-Samples von Freesound zu laden (API-Key optional).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-assets/samples}"
MODE="${2:-offline}"  # offline | freesound | synth

usage() {
  cat <<'USAGE'
fetch_sample_library.sh [TARGET] [MODE]
  TARGET: Zielverzeichnis (default: assets/samples)
  MODE:   offline  — nur deterministische Synthese (immer offline, CC0, kein Netz)
          synth    — wie offline, plus Csound/SuperCollider Hooks wenn vorhanden
          freesound — versuche CC0 von Freesound.org (braucht FREESOUND_API_KEY)

Beispiele:
  ./scripts/fetch_sample_library.sh assets/samples offline
  FREESOUND_API_KEY=xxx ./scripts/fetch_sample_library.sh assets/samples freesound

Lizenz: alle erzeugten Samples sind CC0/synthetisch → keine Clearance nötig.
Quellen für manuelle Erweiterung:
  - https://freesound.org (Filter: License=CC0, Tag: 808, kick, snare, hat)
  - https://sonuslab.com / https://www.kvraudio.com/forum
  - Eigene Synthese: Csound, SuperCollider, engines/dsp_chain.py
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then usage; exit 0; fi
if [[ "$TARGET" == "--help" ]]; then usage; exit 0; fi

mkdir -p "$ROOT/$TARGET"

have() { command -v "$1" >/dev/null 2>&1; }

synthesize_offline() {
  echo "synthesize CC0 samples → $TARGET (deterministisch, lizenzfrei)"
  python3 - "$ROOT/$TARGET" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, 'engines')
from dsp_chain import synthesize_808, synthesize_snare, synthesize_hat
import struct, math, wave

target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)

def write_wav(path, pcm, sr=48000):
    # pcm: list[float] in [-1,1] → 16-bit mono
    with wave.open(str(path), 'w') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames = b''.join(struct.pack('<h', max(-32768, min(32767, int(s*32767)))) for s in pcm)
        w.writeframes(frames)

kits = [
    ("kick_808_sub_drop.wav", lambda: synthesize_808(sample_rate_hz=48000, duration_ms=180)),
    ("kick_808_boom.wav", lambda: synthesize_808(sample_rate_hz=48000, duration_ms=220)),
    ("snare_mpc.wav", lambda: synthesize_snare(sample_rate_hz=48000, duration_ms=140, seed=4200)),
    ("snare_clap.wav", lambda: synthesize_snare(sample_rate_hz=48000, duration_ms=140, seed=20260909)),
    ("hat_closed.wav", lambda: synthesize_hat(sample_rate_hz=48000, duration_ms=60, seed=777)),
    ("hat_roll16.wav", lambda: (synthesize_hat(48000,60,777)+synthesize_hat(48000,60,778))[: int(48000*0.12)]),
]

for name, fn in kits:
    pcm = fn()
    write_wav(target / name, pcm)
    print(f"  {name}: {len(pcm)} frames, peak {max(abs(s) for s in pcm):.3f}")

# Preset mapping note (KP3+ → KaoSS rebrand, rechtlich neu)
(target / "KIT.json").write_text('{"kit":"KaoSS CC0 Synthesized","license":"CC0","sources":["engines/dsp_chain.py synthesize_*","csound/supercollider-optional"],"slots":{"A":["SUB DROP","BOOM"],"B":["MPC SNARE","CLAP"],"C":["TS HAT","ROLL 16"]}}', encoding='utf-8')
print(f"kit: {target}/KIT.json (CC0, KaoSS rebrand — kein KP3+ Markenrisiko)")
PY
}

try_freesound() {
  local key="${FREESOUND_API_KEY:-}"
  if [[ -z "$key" ]]; then
    echo "Freesound: kein FREESOUND_API_KEY — überspringe Download, nutze Synthese" >&2
    return 1
  fi
  if ! have curl; then echo "curl fehlt für Freesound" >&2; return 1; fi
  echo "Freesound CC0 → $TARGET (Tags: 808,kick,snare,hat, CC0)"
  local tmp="$ROOT/$TARGET/.freesound.json"
  curl -fsSL "https://freesound.org/apiv2/search/text/?query=808%20kick&filter=license:%22Creative%20Commons%200%22&fields=id,name,license,previews&page_size=3&token=$key" -o "$tmp" || { echo "Freesound API fehlgeschlagen" >&2; return 1; }
  cat "$tmp" | python3 -m json.tool | head -n 40 || true
  echo "Freesound-JSON: $tmp — Download per preview URL manuell prüfen (Lizenz CC0)"
  return 0
}

maybe_csound() {
  if have csound; then
    echo "Csound gefunden: $(csound --version 2>&1 | head -1)"
    echo "  Beispiel: csound -o $TARGET/csound_kick.wav orc/csound_kick.orc"
  else
    echo "Csound nicht installiert (optional): sudo apt install csound"
  fi
  if have sclang; then
    echo "SuperCollider gefunden: $(sclang --version 2>&1 | head -1)"
  else
    echo "SuperCollider nicht installiert (optional): sudo apt install supercollider"
  fi
}

case "$MODE" in
  offline) synthesize_offline; maybe_csound ;;
  synth) synthesize_offline; maybe_csound ;;
  freesound) synthesize_offline; try_freesound || echo "fallback: Synthese bleibt CC0-Quelle"; maybe_csound ;;
  *) synthesize_offline ;;
esac

# Checksums für KIT
if have sha256sum; then (cd "$ROOT/$TARGET" && sha256sum *.wav 2>/dev/null > SHA256SUMS.txt || true); fi
echo "done: $ROOT/$TARGET ($(ls -1 "$ROOT/$TARGET" | wc -l) files)"
ls -lh "$ROOT/$TARGET" | head -n 20
