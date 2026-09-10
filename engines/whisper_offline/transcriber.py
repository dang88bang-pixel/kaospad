#!/usr/bin/env python3
"""Offline feature transcriber: maps DSP transients to German cypher text.

This is not OpenAI Whisper weights. It is a real, deterministic local pipeline:
PCM → energy/transient class → syllable template → rhyme lookup. Zero cloud.
"""
from __future__ import annotations

from pathlib import Path

from dsp_chain import detect_mouth_transient, process_block, KaossQuadChain, test_signal

TEMPLATES = {
    "KICK808": "drück und laber beton sektor dämon",
    "SNARE_CLAP": "clap im sektor beton fliegt",
    "HAT_ROLL": "hat roll neon berlin cypher",
    "NONE": "flow bleibt offline im bunker",
}


def transcribe_pcm(pcm: list[float], sample_rate_hz: float = 96_000.0) -> dict[str, object]:
    event = detect_mouth_transient(pcm, sample_rate_hz)
    text = TEMPLATES.get(event.kind, TEMPLATES["NONE"])
    return {
        "text": text,
        "language": "de",
        "offline": True,
        "engine": "feature-transcriber",
        "transient": event.as_dict(),
        "buffer_ms": round((len(pcm) / sample_rate_hz) * 1000.0, 3),
        "model": "offline-feature-v1",
    }


def transcribe_signal(signal: str, frames: int = 256, sample_rate_hz: float = 96_000.0) -> dict[str, object]:
    chain = KaossQuadChain()
    pcm = test_signal(signal, frames=frames, sample_rate_hz=sample_rate_hz)
    report = process_block(pcm, chain, sample_rate_hz)
    payload = transcribe_pcm(pcm, sample_rate_hz)
    payload["dsp_kind"] = report["transient"]["kind"]
    return payload
