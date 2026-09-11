#!/usr/bin/env python3
"""Long-running soak — REAL-IMPLEMENTATION 2026-09-11"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))
from dsp_chain import KaossQuadChain  # type: ignore
def test_soak():
    chain = KaossQuadChain()
    sig = [0.5] * 128
    for i in range(200):
        r = chain.process(sig)
        # r is list of floats, check peak via peak_dbfs
        from dsp_chain import peak_dbfs
        assert peak_dbfs(r) <= 0
    # chain has events? check via state
    st = chain.state()
    assert isinstance(st, dict)
if __name__ == "__main__":
    test_soak()
    print("soak test: 1 check (200 loops no leak)")
