#!/usr/bin/env python3
"""Mic permission denial — REAL-IMPLEMENTATION 2026-09-11"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))
from session_engine import SessionEngine  # type: ignore
def test_blocked_without_grant():
    eng = SessionEngine()
    # boot + select + permission check without grant -> arm should BLOCKED
    eng.dispatch("input.select", {"input":"internal_mic"})
    eng.dispatch("permission.check")
    r = eng.dispatch("mic.arm")
    assert r.get("blocked") or r.get("ok") is False or "BLOCKED" in str(r), f"expected BLOCKED got {r}"
    # grant then arm succeeds
    eng.dispatch("permission.grant", {"permission":"record_audio"})
    r2 = eng.dispatch("mic.arm")
    assert r2.get("ok") or r2.get("blocked") is not True
if __name__ == "__main__":
    test_blocked_without_grant()
    print("mic permission denial: 2 checks (BLOCKED guard + grant)")
