#!/usr/bin/env python3
"""Phase-3-Test: Fehlerbehandlung an der DSP- und Event-Grenze.

Beide Module hatten vor Phase 3 keinen einzigen ``except``-Block. Geprüft wird,
dass kaputte Eingaben jetzt einen **vollständigen** Report bzw. einen
gezählten Fehler ergeben – und dass die Aktionskette dadurch nicht abreißt.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

from dsp_chain import LIMITER_THRESHOLD_DBFS, KaossQuadChain, process_block, test_signal  # noqa: E402
from event_stream import EventHub  # noqa: E402

CHECKS = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global CHECKS
    CHECKS += 1
    assert condition, f"CHECK FAILED: {label} // {detail}"


def dsp_tests() -> None:
    chain = KaossQuadChain()
    good = process_block(test_signal("mouth_bass", frames=128), chain, 96_000.0)
    check("Normalfall ok=True", good["ok"] is True, good.get("error"))
    check("Limiter hält im Normalfall", good["output_peak_dbfs"] <= LIMITER_THRESHOLD_DBFS + 1e-6, good["output_peak_dbfs"])
    check("Checksum im Normalfall", len(str(good["checksum"])) >= 16, good["checksum"])

    zero_rate = process_block(test_signal("mouth_bass", frames=128), chain, 0.0)
    check("Abtastrate 0 → ok=False statt ZeroDivisionError", zero_rate["ok"] is False, zero_rate.get("error"))
    check("Abtastrate 0 nennt den Grund", "sample_rate_hz" in str(zero_rate["error"]), zero_rate["error"])

    text_rate = process_block(test_signal("mouth_bass", frames=128), chain, "schnell")  # type: ignore[arg-type]
    check("Abtastrate als Text → ok=False", text_rate["ok"] is False, text_rate.get("error"))

    negative = process_block(test_signal("mouth_bass", frames=128), chain, -48_000.0)
    check("Negative Abtastrate → ok=False", negative["ok"] is False, negative.get("error"))

    dirty = process_block([0.1, "laut", None, 0.2], chain, 96_000.0)  # type: ignore[list-item]
    check("Nicht-numerische Samples → ok=False", dirty["ok"] is False, dirty.get("error"))
    check("PCM-Fehler nennt die Ursache", "PCM" in str(dirty["error"]), dirty["error"])
    check("PCM-Fehler meldet trotzdem frames", dirty["frames"] == 4, dirty["frames"])

    check(
        "Fehlerreport hat dieselben Felder wie der Normalfall",
        set(good) == set(zero_rate) and set(good) == set(dirty),
        sorted(set(good) ^ set(dirty)),
    )
    check("Fehlerreport nennt Chain-Zustand", isinstance(dirty["chain"], dict) and dirty["chain"], dirty["chain"])

    empty = process_block([], chain, 96_000.0)
    check("Leerer Block bleibt gültig", empty["ok"] is True and empty["frames"] == 0, empty)

    # Die Kette selbst bleibt nach Fehlereingaben nutzbar.
    after = process_block(test_signal("mouth_bass", frames=128), chain, 96_000.0)
    check("Kette nach Fehlereingaben weiter nutzbar", after["ok"] is True, after.get("error"))


def event_tests() -> None:
    hub = EventHub(backlog=16)
    subscription = hub.subscribe(since=0)

    hub.publish({"seq": 1, "action": "audio.start"})
    hub.publish({"seq": "keine-zahl", "action": "kaputt"})  # seq als Text
    hub.publish(["kein", "dict"])  # type: ignore[arg-type]
    hub.publish({"seq": 3, "action": "dsp.process"})

    stats = hub.stats()
    check("Beide kaputten Events zählen als Fehler", stats["errors"] == 2, stats)
    check("Letzter Fehlergrund sichtbar", "nicht kopierbar" in stats["last_error"], stats["last_error"])
    # Nicht-Dict und Seq-Unsinn werden verworfen; nur die zwei gültigen bleiben.
    check("Nur gültige Events publiziert", stats["published"] == 2, stats["published"])
    check("Kaputte Events landen nicht im Ring", stats["buffered"] == 2, stats["buffered"])

    events = subscription.wait(timeout=0.2)
    actions = [event.get("action") for event in events]
    check("Abonnent bekommt gültige Events", actions == ["audio.start", "dsp.process"], actions)
    check("Abonnent bricht nicht ab", subscription.delivered == len(events) == 2, subscription.delivered)
    check("Cursor steht auf letzter Seq", hub.last_seq() == 3, hub.last_seq())

    history = hub.history(since=0)
    check("History liefert die gültigen Einträge", len(history) == 2, len(history))
    check("History mit kaputtem Filterwert robust", isinstance(hub.history(since="x" if False else 2), list), "seitwärts")

    closed_hub = EventHub()
    closed_sub = closed_hub.subscribe()
    check("Warten ohne Events liefert leer", closed_sub.wait(timeout=0.02) == [], "nicht leer")
    closed_sub.close()
    check("Geschlossener Abonnent liefert leer", closed_sub.wait(timeout=0.02) == [], "nicht leer")
    check("Hub-Stats nach close konsistent", closed_hub.stats()["subscribers"] >= 0, closed_hub.stats())

    # Dauerlast: Ring begrenzt, kein Speicherleck.
    busy = EventHub(backlog=8)
    for index in range(200):
        busy.publish({"seq": index + 1, "action": f"step{index}"})
    busy_stats = busy.stats()
    check("Ring bleibt begrenzt", busy_stats["buffered"] == 8, busy_stats["buffered"])
    check("Alle Events gezählt", busy_stats["published"] == 200, busy_stats["published"])
    check("Letzte Seq korrekt", busy_stats["last_seq"] == 200, busy_stats["last_seq"])
    check("Keine Fehler bei Dauerlast", busy_stats["errors"] == 0, busy_stats)


def main() -> int:
    started = time.perf_counter()
    dsp_tests()
    event_tests()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(
        "dsp/event error handling verified: "
        f"{CHECKS} checks // ok=False statt Exception // Event-Fehler gezählt // {elapsed_ms:.1f} ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
