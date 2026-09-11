#!/usr/bin/env python3
"""Audio underrun stress — REAL-IMPLEMENTATION 2026-09-11"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"engines"))
from dsp_chain import brickwall_soft_knee_buffer, peak_dbfs, KaossQuadChain  # type: ignore
def test_burst():
    chain = KaossQuadChain()
    for _ in range(100):
        sig = [0.9] * 128
        limited = brickwall_soft_knee_buffer(sig)
        peak = peak_dbfs(limited)
        assert peak < 0
        report = chain.process(sig)
        assert isinstance(report, list)
if __name__ == "__main__":
    test_burst()
    print("underrun stress: 1 check (100 bursts)")
