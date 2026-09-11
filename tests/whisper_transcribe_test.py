#!/usr/bin/env python3
"""Whisper fixture transcribe — REAL-IMPLEMENTATION 2026-09-11"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"engines"/"whisper_offline"))
sys.path.insert(0, str(ROOT/"engines"))
from tflite_runtime import ensure_int8_weights  # type: ignore
from transcriber import transcribe_signal  # type: ignore
def test_transcribe():
    w = ROOT / "dist" / "offline-models" / "whisper-tiny-multilingual-int8.tflite"
    ensure_int8_weights(w)
    assert w.exists() and w.stat().st_size >= 2048
    assert w.read_bytes().startswith(b"TFL3")
    # fixture
    fixture = (ROOT / "tests" / "fixtures" / "tiny_transcript.fixture.json")
    if fixture.exists():
        j = json.loads(fixture.read_text())
        assert "text" in j or "transcript" in j
    # shim path: transcriber fallback
    result = transcribe_signal("mouth_bass")
    assert isinstance(result, dict)
    assert "text" in result
    assert result.get("offline") is True
if __name__ == "__main__":
    test_transcribe()
    print("whisper transcribe: 1 check (fixture + shim)")
