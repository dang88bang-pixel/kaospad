#!/usr/bin/env python3
"""Prüft den opt-in echten Offline-ASR-Pfad (pocketsphinx).

-- REAL-IMPLEMENTATION 2026-09-12 (Online-Alternativen-Evaluation)

Der deterministische Feature-Transkriber bleibt Standard; dieser Test prüft
  1. die Vorverarbeitung (Resampling, 16-Bit-Konversion, Clipping) -- immer,
  2. die ehrliche Verfügbarkeitsmeldung und den harten Fehler ohne pocketsphinx,
  3. den echten Dekodierlauf, **falls** pocketsphinx installiert ist,
  4. dass der Standardweg unverändert deterministisch bleibt,
  5. dass nichts ins Netz geht (Zero-Cloud).

Aufruf:  python3 tests/real_asr_test.py
"""

from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))

import real_asr  # noqa: E402
import tflite_runtime  # noqa: E402

FAILED: list[str] = []
SKIPPED: list[str] = []
CHECKS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}",
          flush=True)
    if not ok:
        FAILED.append(f"{label} {detail}".strip())


def section(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def preprocessing_tests() -> None:
    section("Vorverarbeitung ohne Fremdabhängigkeit")

    same = real_asr.resample_linear([0.0, 0.5, 1.0], 16000.0)
    check("gleiche Rate gibt unveränderte Werte zurück", same == [0.0, 0.5, 1.0], str(same))

    down = real_asr.resample_linear([float(i) for i in range(960)], 96000.0, 16000)
    check("96 kHz -> 16 kHz ergibt ein Sechstel der Frames", len(down) == 160,
          f"{len(down)} Frames")
    check("erster Wert bleibt erhalten", abs(down[0]) < 1e-9, str(down[0]))
    # 160 Ausgabeframes tasten die Eingangspositionen i*6 ab, d. h. 0..954 --
    # der letzte Eingangswert (959) liegt hinter dem Abtastraster.
    check("letzter Wert entspricht Position 954", abs(down[-1] - 954.0) < 1e-9, str(down[-1]))
    check("Abtastraster ist exakt i*6", all(abs(down[i] - 6 * i) < 1e-9 for i in range(160)))

    up = real_asr.resample_linear([0.0, 1.0], 8000.0, 16000)
    check("8 kHz -> 16 kHz verdoppelt", len(up) == 4, f"{len(up)} Frames")
    check("interpolierter Mittelpunkt ist 0.5", abs(up[1] - 0.5) < 1e-6, str(up[1]))

    check("leerer Puffer ergibt leere Liste", real_asr.resample_linear([], 48000.0) == [])
    try:
        real_asr.resample_linear([0.0], 0.0)
        check("Rate 0 wird abgelehnt", False, "keine Exception")
    except ValueError:
        check("Rate 0 wird abgelehnt", True)

    pcm16 = real_asr.to_pcm16([0.0, 1.0, -1.0, 2.0, -2.0])
    check("16-Bit-Ausgabe hat 2 Bytes pro Sample", len(pcm16) == 10, f"{len(pcm16)} Bytes")
    values = struct.unpack("<5h", pcm16)
    check("Null bleibt Null", values[0] == 0, str(values))
    check("+1.0 wird 32767", values[1] == 32767, str(values[1]))
    check("-1.0 wird -32767", values[2] == -32767, str(values[2]))
    check("Übersteuerung wird geclippt (+)", values[3] == 32767, str(values[3]))
    check("Übersteuerung wird geclippt (-)", values[4] == -32767, str(values[4]))
    check("leerer Puffer ergibt leere Bytes", real_asr.to_pcm16([]) == b"")


def availability_tests() -> None:
    section("Verfügbarkeit wird ehrlich gemeldet")
    status = real_asr.availability()
    check("availability() liefert ein dict", isinstance(status, dict))
    check("Feld ok vorhanden", "ok" in status, str(status.get("ok")))
    check("Feld engine == pocketsphinx", status.get("engine") == "pocketsphinx")
    check("Zero-Cloud-Kennzeichnung", status.get("offline") is True)
    if status["ok"]:
        for key in ("acoustic_model", "language_model", "dictionary"):
            path = status.get(key)
            check(f"{key} zeigt auf eine existierende Datei",
                  bool(path) and Path(str(path)).exists(), str(path))
        check("Modell ist als 16 kHz deklariert", status.get("sample_rate_hz") == 16000)
        check("echte Gewichte gekennzeichnet", status.get("real_weights") is True)
        check("Nicht-Determinismus gekennzeichnet", status.get("deterministic") is False)
    else:
        check("Grund für Nichtverfügbarkeit genannt", bool(status.get("reason")),
              str(status.get("reason"))[:80])
        check("Installationshinweis vorhanden", "pip3 install" in str(status.get("hint")))


def hard_failure_tests() -> None:
    section("Ohne pocketsphinx: harter Fehler statt stillem Platzhalter")
    status = real_asr.availability()
    if status["ok"]:
        # Verfügbarkeit kurz wegnehmen, um den Fehlerpfad zu erzwingen
        original = real_asr.availability
        real_asr.availability = lambda: {"ok": False, "reason": "Testabschaltung"}
        try:
            real_asr.transcribe_pcm_real([0.0] * 64, 16000.0)
            check("transcribe_pcm_real wirft ohne pocketsphinx", False, "keine Exception")
        except real_asr.RealAsrUnavailable as exc:
            check("transcribe_pcm_real wirft ohne pocketsphinx", True, str(exc)[:60])
        finally:
            real_asr.availability = original
    else:
        try:
            real_asr.transcribe_pcm_real([0.0] * 64, 16000.0)
            check("transcribe_pcm_real wirft ohne pocketsphinx", False, "keine Exception")
        except real_asr.RealAsrUnavailable as exc:
            check("transcribe_pcm_real wirft ohne pocketsphinx", True, str(exc)[:60])

    try:
        real_asr.transcribe_pcm_real([], 16000.0)
        check("leerer Puffer wird abgelehnt", False, "keine Exception")
    except (ValueError, real_asr.RealAsrUnavailable):
        check("leerer Puffer wird abgelehnt", True)


def real_decode_tests() -> None:
    section("Echter Dekodierlauf (nur mit installiertem pocketsphinx)")
    if not real_asr.availability()["ok"]:
        SKIPPED.append("pocketsphinx nicht installiert "
                       "(pip3 install --break-system-packages pocketsphinx)")
        print("[SKIP] pocketsphinx fehlt -- echter Dekodierlauf übersprungen", flush=True)
        return

    frames = 16000
    tone = [0.25 * math.sin(2 * math.pi * 220.0 * i / 16000.0) for i in range(frames)]
    result = real_asr.transcribe_pcm_real(tone, 16000.0)

    check("Ergebnis ist ein dict", isinstance(result, dict))
    check("engine == pocketsphinx", result.get("engine") == "pocketsphinx")
    check("echte Gewichte gekennzeichnet", result.get("real_weights") is True)
    check("Nicht-Determinismus gekennzeichnet", result.get("deterministic") is False)
    check("offline gekennzeichnet", result.get("offline") is True)
    check("akustisches Modell benannt", result.get("model") == "en-us", str(result.get("model")))
    check("Zielrate 16 kHz", result.get("sample_rate_hz") == 16000)
    check("Quellrate übernommen", result.get("source_sample_rate_hz") == 16000.0)
    check("dekodierte Frames == Eingabeframes", result.get("decoded_frames") == frames,
          str(result.get("decoded_frames")))
    check("Text ist ein String", isinstance(result.get("text"), str))
    check("Score ist eine Zahl", isinstance(result.get("score"), float),
          str(result.get("score")))
    check("Segmentanzahl ist eine Zahl", isinstance(result.get("segments"), int))
    check("buffer_ms berechnet", abs(result.get("buffer_ms", 0) - 1000.0) < 1.0,
          str(result.get("buffer_ms")))
    check("Verfügbarkeitsbericht mitgeliefert",
          isinstance(result.get("availability"), dict)
          and result["availability"].get("ok") is True)

    # Ton ist keine Sprache: die Hypothese muss leer oder sehr kurz sein
    check("bei reinem Ton keine lange Fantasie-Transkription",
          len(result["text"].split()) <= 3, repr(result["text"]))

    down = real_asr.transcribe_pcm_real(tone, 96000.0)
    # 16000 Frames @ 96 kHz = 0,16667 s -> 2667 Frames @ 16 kHz
    check("96-kHz-Eingang wird auf 16 kHz umgerechnet",
          down.get("sample_rate_hz") == 16000 and down.get("decoded_frames") == 2667,
          str(down.get("decoded_frames")))
    check("Quellrate 96 kHz wird berichtet",
          down.get("source_sample_rate_hz") == 96000.0, str(down.get("source_sample_rate_hz")))


def default_path_tests() -> None:
    section("Standardweg bleibt deterministisch (Regression)")
    first = tflite_runtime.infer(signal="vocal", sample_rate_hz=16000.0)
    second = tflite_runtime.infer(signal="vocal", sample_rate_hz=16000.0)
    check("Standard-Engine ist der Feature-Transkriber",
          first.get("engine") == "feature-transcriber", str(first.get("engine")))
    check("zwei Läufe liefern identischen Text",
          first.get("text") == second.get("text"), repr(first.get("text")))
    check("Standardweg kennzeichnet keine echten Gewichte",
          "real_asr_result" not in first)
    check("Verfügbarkeitsbericht wird trotzdem mitgeliefert",
          isinstance(first.get("real_asr"), dict) and "ok" in first["real_asr"])
    check("tflite-Status weiterhin geladen",
          first.get("tflite", {}).get("loaded") is True)

    if real_asr.availability()["ok"]:
        active = tflite_runtime.infer(signal="vocal", sample_rate_hz=16000.0,
                                      real_asr_enabled=True)
        check("Opt-in ergänzt real_asr_result", "real_asr_result" in active)
        check("Opt-in ändert den Standardtext nicht",
              active.get("text") == first.get("text"))
        check("Opt-in nutzt pocketsphinx",
              active["real_asr_result"].get("engine") == "pocketsphinx")
    else:
        try:
            tflite_runtime.infer(signal="vocal", sample_rate_hz=16000.0,
                                 real_asr_enabled=True)
            check("Opt-in ohne pocketsphinx wirft", False, "keine Exception")
        except real_asr.RealAsrUnavailable:
            check("Opt-in ohne pocketsphinx wirft", True)


def zero_cloud_tests() -> None:
    section("Zero-Cloud: kein Netzwerk im Modul")
    source = (ROOT / "engines" / "whisper_offline" / "real_asr.py").read_text(encoding="utf-8")
    for forbidden in ("import requests", "import urllib", "import http.client",
                      "import socket", "http://", "https://"):
        check(f"real_asr.py enthält kein {forbidden}", forbidden not in source)


def main() -> int:
    preprocessing_tests()
    availability_tests()
    hard_failure_tests()
    real_decode_tests()
    default_path_tests()
    zero_cloud_tests()

    print("", flush=True)
    if SKIPPED:
        print("übersprungen:", " | ".join(SKIPPED), flush=True)
    if FAILED:
        print(f"FEHLER ({len(FAILED)}):", flush=True)
        for item in FAILED:
            print(f"  - {item}", flush=True)
        return 1
    mode = "echter Dekodierlauf ausgeführt" if not SKIPPED else "ohne pocketsphinx"
    print(f"real asr verified: {CHECKS} checks // Vorverarbeitung exakt // "
          f"Standardweg deterministisch // {mode}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
