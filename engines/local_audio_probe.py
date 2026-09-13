#!/usr/bin/env python3
"""Probe real local audio devices without leaving localhost / the machine.

Reads ALSA cards from /proc/asound and /dev/snd. Never opens a network socket.
Missing hardware still returns an empty probe list; the public device-matrix IDs
stay stable for the action chain.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 3)
Vorher: ein einzelner, ungeschützter Lesezugriff auf ``/proc/asound`` und
``/dev/snd``. Beim Abziehen/Anstecken eines USB-Audio-Interfaces liefert der
Kernel dort kurzzeitig ``ENODEV``/``EACCES`` – der Aufruf meldete dann einfach
eine leere Geräteliste, ohne dass jemand wusste, warum.

Jetzt läuft der gleiche Lesevorgang durch ``engines.resilience``: bis zu drei
Versuche mit exponentiellem Backoff und ein Circuit Breaker ``alsa_probe``, der
nach fünf Fehlern für fünf Sekunden öffnet, damit eine tote Schnittstelle nicht
pro Frame erneut ausgelesen wird. Das Ergebnis behält alle bisherigen Felder und
meldet zusätzlich unter ``resilience``, wie der Zugriff zustande kam.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from resilience import REGISTRY, AttemptRecord, RetryPolicy  # noqa: E402

BREAKER_NAME = "alsa_probe"
PROBE_POLICY = RetryPolicy(attempts=3, base_delay_s=0.02, factor=2.0, max_delay_s=0.2, jitter=0.25)


def _read_probe() -> dict[str, object]:
    """Ein einzelner, ungeschützter Lesezugriff auf ALSA-/snd-Quellen."""
    cards: list[dict[str, object]] = []
    cards_path = Path("/proc/asound/cards")
    if cards_path.exists():
        text = cards_path.read_text(encoding="utf-8", errors="replace")
        current: dict[str, object] | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped[:1].isdigit():
                idx, _, rest = stripped.partition(" [")
                name = rest.split("]", 1)[0].strip() if "]" in rest else rest
                current = {"id": int(idx.split()[0]), "name": name or "ALSA", "source": "/proc/asound/cards"}
                cards.append(current)
            elif current is not None and "driver" not in current:
                current["driver"] = stripped
    pcm = Path("/proc/asound/pcm")
    if pcm.exists():
        cards.append({
            "id": "pcm",
            "name": pcm.read_text(encoding="utf-8", errors="replace").strip().split("\n")[0][:80],
            "source": "/proc/asound/pcm",
        })
    snd = Path("/dev/snd")
    nodes = sorted(p.name for p in snd.iterdir()) if snd.is_dir() else []
    return {
        "alsa_cards": [c for c in cards if isinstance(c, dict) and c.get("id") != "pcm"],
        "pcm_summary": next((c.get("name") for c in cards if c.get("id") == "pcm"), ""),
        "snd_nodes": nodes,
        "has_capture": any(name.startswith("pcmC") and "c" in name for name in nodes) or bool(cards),
        "pulse_runtime": os.path.exists(os.path.expanduser("~/.config/pulse")) or Path("/run/user").exists(),
    }


def _resilience_view(record: AttemptRecord) -> dict[str, object]:
    breaker = REGISTRY.get(BREAKER_NAME, failure_threshold=5, reset_timeout_s=5.0)
    return {
        "guarded_by": "engines/resilience.py",
        "breaker": breaker.name,
        "breaker_state": breaker.state,
        "tries": record.tries,
        "ok": record.ok,
        "error": record.error,
        "attempts": record.attempts,
        "retry_policy": {
            "attempts": PROBE_POLICY.attempts,
            "base_delay_s": PROBE_POLICY.base_delay_s,
            "factor": PROBE_POLICY.factor,
        },
    }


def alsa_cards() -> dict[str, object]:
    """Liest die lokalen Audio-Quellen – mit Retry, Backoff und Circuit Breaker."""
    breaker = REGISTRY.get(BREAKER_NAME, failure_threshold=5, reset_timeout_s=5.0)
    record = breaker.call(_read_probe, PROBE_POLICY)
    probe = record.value if record.ok and isinstance(record.value, dict) else {
        "alsa_cards": [],
        "pcm_summary": "",
        "snd_nodes": [],
        "has_capture": False,
        "pulse_runtime": False,
    }
    payload: dict[str, object] = {"ok": True, **probe, "offline": True}
    if not record.ok:
        # Degradiert, aber nie abgestürzt: leere Liste + ehrlicher Grund.
        payload["reason"] = record.error or "alsa probe nicht möglich"
    payload["resilience"] = _resilience_view(record)
    return payload


if __name__ == "__main__":
    import json

    print(json.dumps(alsa_cards(), indent=2))
