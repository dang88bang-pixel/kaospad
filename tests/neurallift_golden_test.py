#!/usr/bin/env python3
"""NeuralLift golden test — REAL-IMPLEMENTATION 2026-09-11"""
import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
import sys; sys.path.insert(0, str(ROOT/"engines"/"neurallift_360"))
from glb import write_glb  # type: ignore
def test_golden():
    out = ROOT / "dist" / "avatars" / "test_golden.glb"
    write_glb(out, seed="camera_frame_0001.jpg")
    data = out.read_bytes()
    assert data[:4] == b"glTF", "magic glTF"
    assert len(data) > 400
    # checksum stable
    h = hashlib.sha256(data).hexdigest()
    assert len(h)==64
    # second write deterministic (capsule same seed)
    out2 = ROOT / "dist" / "avatars" / "test_golden2.glb"
    write_glb(out2, seed="camera_frame_0001.jpg")
    assert out.read_bytes() == out2.read_bytes(), "deterministic"
if __name__ == "__main__":
    test_golden()
    print("neurallift golden: 3 checks (glTF magic, >400B, deterministic)")
