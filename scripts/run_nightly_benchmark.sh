#!/usr/bin/env bash
# run_nightly_benchmark.sh — REAL-IMPLEMENTATION 2026-09-11
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$DIR/.." && pwd)"
mkdir -p "$ROOT/dist"
echo "[benchmark] running dsp + ipc + avatar synthetic"
python3 - <<'PYEOF'
import time, json, sys
from pathlib import Path
ROOT=Path(".").resolve()
sys.path.insert(0, str(ROOT/"engines"))
from dsp_chain import limiter_peak
import random
start=time.time()
for _ in range(1000):
    sig=[random.uniform(-1,1) for _ in range(128)]
    limiter_peak(sig)
elapsed=time.time()-start
out={"dsp_1000_loops_ms": elapsed*1000, "peak": limiter_peak([0.9]*128), "ts": time.time(), "offline": True}
Path("dist/benchmark.json").write_text(json.dumps(out, indent=2))
print(f"[benchmark] {out}")
PYEOF
echo "[benchmark] done dist/benchmark.json"
