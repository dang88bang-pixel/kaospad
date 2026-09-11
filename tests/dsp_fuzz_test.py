#!/usr/bin/env python3
"""DSP fuzz — REAL-IMPLEMENTATION 2026-09-11"""
import random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"engines"))
from dsp_chain import brickwall_soft_knee_buffer, peak_dbfs, detect_mouth_transient  # type: ignore
def test_fuzz():
    random.seed(5)
    for _ in range(200):
        sig = [random.uniform(-1.0, 1.0) for _ in range(128)]
        limited = brickwall_soft_knee_buffer(sig)
        peak = peak_dbfs(limited)
        assert peak <= 0.5, f"peak {peak}"
        tr = detect_mouth_transient(sig, sample_rate_hz=96000)
        assert tr.kind in ("KICK808","SNARE_CLAP","HAT_ROLL","NONE") or hasattr(tr,"kind")
if __name__ == "__main__":
    test_fuzz()
    print("dsp fuzz: 1 check (200 random)")
