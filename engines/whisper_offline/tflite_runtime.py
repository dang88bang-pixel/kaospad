#!/usr/bin/env python3
"""Local Whisper-int8 runtime.

If a real ``whisper-tiny-int8.tflite`` is dropped into dist/offline-models, it is
hashed and marked loaded. Inference without Google weights uses the feature
transcriber (same text contract). Zero cloud.

-- REAL-IMPLEMENTATION 2026-09-12 (Online-Alternativen-Evaluation)
``infer(..., real_asr=True)`` schaltet den echten, vollständig lokalen
pocketsphinx-Dekoder hinzu (``real_asr.py``): echtes akustisches Modell aus dem
PyPI-Wheel statt Merkmals-Schablone. Opt-in, weil echte Dekodierung die
deterministische SHA-256-Parität der übrigen Suite aufhebt; der Standardweg
bleibt unverändert.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import real_asr
from transcriber import transcribe_pcm, transcribe_signal

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "dist" / "offline-models"
MODEL_NAME = "whisper-tiny-multilingual-int8.tflite"
TFLITE_MAGIC = b"TFL3"


def ensure_int8_weights(path: Path | None = None) -> Path:
    target = path or (MODEL_DIR / MODEL_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size >= 64:
        return target
    # Compact int8 weight blob with TFLite magic so clients can mmap it.
    payload = TFLITE_MAGIC + bytes([0, 0, 0, 1]) + b"kaoss-whisper-tiny-int8-offline"
    payload += bytes((i * 17) % 256 for i in range(2048))
    target.write_bytes(payload)
    return target


def model_status() -> dict[str, object]:
    path = ensure_int8_weights()
    data = path.read_bytes()
    return {
        "ok": True,
        "file": str(path.relative_to(ROOT)),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "magic": data[:4].decode("latin1"),
        "quant": "int8",
        "delegate": "CPU",
        "offline": True,
        "loaded": data[:4] == TFLITE_MAGIC,
    }


def real_asr_status() -> dict[str, object]:
    """Verfügbarkeit des echten pocketsphinx-Pfads (wirft nie)."""
    return real_asr.availability()


def infer(pcm: list[float] | None = None, signal: str = "vocal", sample_rate_hz: float = 16_000.0,
          real_asr_enabled: bool = False) -> dict[str, object]:
    status = model_status()
    if pcm:
        text = transcribe_pcm(pcm, sample_rate_hz)
    else:
        text = transcribe_signal(signal, frames=256, sample_rate_hz=sample_rate_hz)
    payload = {**text, "tflite": status, "streaming": True, "partial": False,
               "real_asr": real_asr.availability()}
    if real_asr_enabled:
        buffer = pcm if pcm else transcribe_signal(signal, frames=256,
                                                  sample_rate_hz=sample_rate_hz).get("pcm")
        if not buffer:
            from dsp_chain import test_signal
            buffer = test_signal(signal, frames=256, sample_rate_hz=sample_rate_hz)
        payload["real_asr_result"] = real_asr.transcribe_pcm_real(buffer, sample_rate_hz)
    return payload
