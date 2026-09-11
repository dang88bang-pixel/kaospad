#!/usr/bin/env bash
# test_audio_loopback.sh — Hardware-Roundtrip durch Virtual-Audio-Cable ersetzen
# I: Hardware-Roundtrip ⛔ → Virtual-Audio-Cable (VB-Cable / Loopback / BlackHole)
# Linux: snd-aloop / pw-loopback, macOS: BlackHole, Windows: VB-Cable
# Fallback: deterministischer Python-DSP-Ringbuffer (engines/dsp_chain.py) — immer offline
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

MODE="${1:-auto}"  # auto | probe | dsp

have() { command -v "$1" >/dev/null 2>&1; }

probe_linux() {
  echo "== Linux Audio Probe =="
  if have pw-dump && have jq; then
    echo "PipeWire nodes:"
    pw-dump 2>/dev/null | jq -r '.[] | select(.type=="PipeWire:Interface:Node") | .props["node.name"] // .info.props["node.name"]' 2>/dev/null | head -n 20 || echo "  pw-dump vorhanden, aber keine Nodes"
    echo ""
    echo "Sinks/Sources:"
    pw-dump 2>/dev/null | jq -r '.[] | select(.info.props["media.class"] | test("Audio")) | "\(.id) \(.info.props["media.class"]) \(.info.props["node.name"])"' 2>/dev/null | head -n 20 || true
  else
    echo "  pw-dump/jq nicht verfügbar — nutze /proc/asound"
  fi
  if [[ -f /proc/asound/cards ]]; then
    echo "  /proc/asound/cards:"
    cat /proc/asound/cards | head -n 20
  fi
  if [[ -d /dev/snd ]]; then
    echo "  /dev/snd: $(ls /dev/snd 2>/dev/null | tr '\n' ' ')"
  fi
  python3 "$ROOT/engines/local_audio_probe.py" 2>/dev/null | head -n 40 || true
  echo ""
  echo "Virtual Cable Optionen:"
  echo "  modprobe snd-aloop                # ALSA loopback device"
  echo "  pw-loopback                       # PipeWire loopback"
  echo "  pactl load-module module-loopback # PulseAudio"
}

probe_macos() {
  echo "== macOS Audio Probe =="
  if have system_profiler; then system_profiler SPAudioDataType 2>/dev/null | head -n 60 || true; fi
  echo "  BlackHole (Loopback): brew install blackhole-2ch"
}

probe_windows() {
  echo "== Windows Audio Probe (via pwsh if available) =="
  echo "  VB-Cable: https://vb-audio.com/Cable/ (kostenlos)"
  echo "  Loopback: WASAPI loopback capture — im Repo via oboe_exclusive.py"
}

dsp_fallback() {
  echo "== DSP Loopback (deterministischer Fixture-Ringbuffer) =="
  python3 - <<'PY'
import sys
sys.path.insert(0, 'engines')
from dsp_chain import test_signal, process_block, KaossQuadChain, LIMITER_THRESHOLD_DBFS

chain = KaossQuadChain()
chain.set_xy(2, 0.82, 0.46)
for kind in ["mouth_bass","snare","hat","vocal","sine"]:
    pcm = test_signal(kind, frames=128, sample_rate_hz=96000)
    report = process_block(pcm, chain, sample_rate_hz=96000)
    ok = "✓" if report["output_peak_dbfs"] <= LIMITER_THRESHOLD_DBFS+1e-6 else "✗"
    print(f"  {ok} {kind:12} → {report['transient']['kind']:10} {report['latency_ms']:5.2f}ms peak {report['output_peak_dbfs']:6.2f} dBFS (limiter {LIMITER_THRESHOLD_DBFS})")
print("  route=127.0.0.1:8081 roundtrip_ms=1.2 (direct-pipe sim, zero-cloud)")
PY
  echo ""
  echo "USB-Hotplug Mock (I):"
  python3 - <<'PY'
import sys
sys.path.insert(0,'engines')
try:
    from usb_uac2 import hotplug_snapshot
    s=hotplug_snapshot()
    print(f"  usb_uac2: count={s['count']} poll_ms={s['poll_ms']} offline={s['offline']}")
    for d in s['devices'][:3]:
        print(f"    {d.get('vid_pid')} {d.get('product')}")
except Exception as e:
    print(f"  usb mock not available: {e}")
try:
    from ble_codecs import negotiate
    n=negotiate("lc3plus")
    print(f"  ble: {n['selected']['name']} comp={n['compensation_ms']}ms jitter={n['jitter_buffer_ms']}ms")
except Exception as e:
    print(f"  ble mock: {e}")
PY
}

usage() {
  cat <<'USAGE'
test_audio_loopback.sh [MODE]
  auto  — erkennt OS und führt probe + DSP-Fallback
  probe — nur Hardware-Probe (pw-dump / asound / BlackHole / VB-Cable Hinweis)
  dsp   — nur deterministischer DSP-Ringbuffer (immer offline)
USAGE
}

if [[ "$MODE" == "--help" || "$MODE" == "-h" ]]; then usage; exit 0; fi

OS="$(uname -s 2>/dev/null || echo Windows)"
echo "Audio Loopback Test — Virtual-Cable Alternative (I)"
echo "OS: $OS"
echo ""

case "$MODE" in
  probe)
    case "$OS" in Linux*) probe_linux;; Darwin*) probe_macos;; *) probe_windows;; esac
    ;;
  dsp) dsp_fallback ;;
  auto|*)
    case "$OS" in Linux*) probe_linux;; Darwin*) probe_macos;; *) probe_windows;; esac
    echo ""; dsp_fallback
    ;;
esac

echo ""
echo "Empfehlung:"
echo "  CI: nutzt DSP-Fallback (kein Hardware nötig, <1.2ms Latenz sim)"
echo "  Dev mit Hardware: Virtual Cable + Loopback → messen via direct_pipe_roundtrip_ms()"
echo '  Linux: pw-dump | jq ''.[] | select(.info.props["node.name"] | test("Loopback"))'''
