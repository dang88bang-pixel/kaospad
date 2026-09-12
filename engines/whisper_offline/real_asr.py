#!/usr/bin/env python3
"""Optionaler echter Offline-ASR-Pfad (pocketsphinx) -- REAL-IMPLEMENTATION 2026-09-12.

Ergebnis der Online-Alternativen-Evaluation (`docs/audit/ONLINE-ALTERNATIVEN.md`):
Whisper-/MiDaS-Gewichte sind nicht erreichbar (HuggingFace `000`,
GitHub-Release-Assets `302 -> 0 Bytes`), aber **pocketsphinx 5.1.1** kommt per PyPI
und enthält ein vollständiges akustisches Modell (`mdef`, `means`, `variances`,
`sendump`, `transition_matrices`, LMs, CMU-Wörterbuch). Damit ist echte,
vollständig lokale Spracherkennung ohne Cloud möglich.

Bewusst **opt-in**:
  * Der deterministische Feature-Transkriber bleibt der Standard, weil die
    Paritätstests des Projekts auf reproduzierbarer Ausgabe beruhen.
  * Ein echter Dekoder ist nicht deterministisch im Sinne der SHA-256-Parität;
    seine Ergebnisse werden deshalb klar gekennzeichnet
    (`engine: "pocketsphinx"`, `deterministic: False`, `real_weights: True`).
  * Ohne installiertes `pocketsphinx` liefert dieses Modul eine ehrliche
    Fehlermeldung statt still zurückzufallen.

Zero-Cloud: pocketsphinx läuft ausschließlich lokal, es wird nichts übertragen.
"""

from __future__ import annotations

import math
import os
import struct
from pathlib import Path
from typing import Any, Dict, List, Sequence

TARGET_RATE = 16_000          # pocketsphinx-Modell erwartet 16 kHz Mono
SAMPLE_WIDTH = 2              # 16-Bit-PCM


class RealAsrUnavailable(RuntimeError):
    """pocketsphinx (oder sein Modell) ist nicht verfügbar."""


def availability() -> Dict[str, object]:
    """Ehrlicher Verfügbarkeitsbericht -- wirft nie."""
    try:
        import pocketsphinx  # noqa: F401
    except Exception as exc:  # pragma: no cover - hängt von der Umgebung ab
        return {
            "ok": False,
            "engine": "pocketsphinx",
            "reason": f"{type(exc).__name__}: {exc}",
            "hint": "pip3 install --break-system-packages pocketsphinx",
            "offline": True,
        }
    try:
        from pocketsphinx import Config
        config = Config()
        hmm = config.get_string("-hmm") or ""
        lm = config.get_string("-lm") or ""
        dictionary = config.get_string("-dict") or ""
        missing = [
            name for name, path in (("hmm", hmm), ("lm", lm), ("dict", dictionary))
            if not path or not Path(path).exists()
        ]
    except Exception as exc:
        return {
            "ok": False,
            "engine": "pocketsphinx",
            "reason": f"Modellkonfiguration fehlgeschlagen: {type(exc).__name__}: {exc}",
            "offline": True,
        }
    if missing:
        return {
            "ok": False,
            "engine": "pocketsphinx",
            "reason": f"Modelldateien fehlen: {', '.join(missing)}",
            "offline": True,
        }
    return {
        "ok": True,
        "engine": "pocketsphinx",
        "version": getattr(pocketsphinx, "__version__", "unbekannt"),
        "acoustic_model": hmm,
        "language_model": lm,
        "dictionary": dictionary,
        "sample_rate_hz": TARGET_RATE,
        "real_weights": True,
        "offline": True,
        "deterministic": False,
    }


def resample_linear(pcm: Sequence[float], source_rate_hz: float,
                    target_rate_hz: int = TARGET_RATE) -> List[float]:
    """Lineare Interpolation auf ``target_rate_hz`` (abhängigkeitsfrei)."""
    if source_rate_hz <= 0:
        raise ValueError("sample_rate_hz muss positiv sein")
    if not pcm:
        return []
    if abs(source_rate_hz - target_rate_hz) < 1e-9:
        return list(pcm)
    ratio = target_rate_hz / source_rate_hz
    out_len = max(1, int(round(len(pcm) * ratio)))
    out: List[float] = []
    last = len(pcm) - 1
    for i in range(out_len):
        pos = i / ratio
        idx = int(math.floor(pos))
        frac = pos - idx
        if idx >= last:
            out.append(float(pcm[last]))
            continue
        a = float(pcm[idx])
        b = float(pcm[idx + 1])
        out.append(a + (b - a) * frac)
    return out


def to_pcm16(pcm: Sequence[float]) -> bytes:
    """float32 (-1.0..1.0) -> little-endian 16-Bit-PCM mit Clipping."""
    out = bytearray()
    for value in pcm:
        sample = max(-1.0, min(1.0, float(value)))
        out += struct.pack("<h", int(sample * 32767.0))
    return bytes(out)


def _load_decoder():
    from pocketsphinx import Config, Decoder

    config = Config()
    config.set_float("-samprate", float(TARGET_RATE))
    # pocketsphinx schreibt Diagnosezeilen nach stderr; das gehört nicht in
    # Produkt- oder Testausgaben.
    try:
        config.set_string("-logfn", os.devnull)
    except Exception:
        pass
    try:
        return Decoder(config)
    except Exception as exc:
        raise RealAsrUnavailable(
            f"pocketsphinx-Decoder ließ sich nicht initialisieren: {type(exc).__name__}: {exc}"
        ) from exc


def transcribe_pcm_real(pcm: Sequence[float], sample_rate_hz: float = 96_000.0) -> Dict[str, Any]:
    """Echte Dekodierung mit dem mitgelieferten akustischen Modell.

    Wirft :class:`RealAsrUnavailable`, wenn pocketsphinx fehlt -- kein stiller
    Rückfall auf den Platzhalter.
    """
    status = availability()
    if not status["ok"]:
        raise RealAsrUnavailable(str(status["reason"]))
    if not pcm:
        raise ValueError("leerer PCM-Puffer")

    decoder = _load_decoder()
    mono16k = resample_linear(pcm, float(sample_rate_hz))
    raw = to_pcm16(mono16k)

    decoder.start_utt()
    try:
        decoder.process_raw(raw, full_utt=True)
    finally:
        decoder.end_utt()

    hypothesis = decoder.hyp()
    text = hypothesis.hypstr if hypothesis is not None else ""
    # Ohne Hypothese liefert seg() None -- kein Fehler, sondern "nichts erkannt".
    raw_segments = decoder.seg() if hasattr(decoder, "seg") else None
    segments = [seg.word for seg in (raw_segments or []) if getattr(seg, "word", None)]

    return {
        "text": text,
        "language": "en",                 # das mitgelieferte Modell ist en-us
        "offline": True,
        "engine": "pocketsphinx",
        "model": os.path.basename(str(status["acoustic_model"])) or "en-us",
        "real_weights": True,
        "deterministic": False,
        "score": float(hypothesis.score) if hypothesis is not None else 0.0,
        "segments": len(segments),
        "words": segments,
        "input_frames": len(pcm),
        "decoded_frames": len(mono16k),
        "sample_rate_hz": TARGET_RATE,
        "source_sample_rate_hz": float(sample_rate_hz),
        "buffer_ms": round((len(pcm) / float(sample_rate_hz)) * 1000.0, 3),
        "availability": status,
    }
