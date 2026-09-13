#!/usr/bin/env python3
"""Probe real local audio devices without leaving localhost / the machine.

Reads ALSA cards from /proc/asound and /dev/snd. Never opens a network socket.
Missing hardware still returns an empty probe list; the public device-matrix IDs
stay stable for the action chain.
"""
from __future__ import annotations

import os
from pathlib import Path


def alsa_cards() -> dict[str, object]:
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
        cards.append({"id": "pcm", "name": pcm.read_text(encoding="utf-8", errors="replace").strip().split("\n")[0][:80], "source": "/proc/asound/pcm"})
    snd = Path("/dev/snd")
    nodes = sorted(p.name for p in snd.iterdir()) if snd.is_dir() else []
    return {
        "ok": True,
        "alsa_cards": [c for c in cards if isinstance(c, dict) and c.get("id") != "pcm"],
        "pcm_summary": next((c.get("name") for c in cards if c.get("id") == "pcm"), ""),
        "snd_nodes": nodes,
        "has_capture": any(name.startswith("pcmC") and "c" in name for name in nodes) or bool(cards),
        "pulse_runtime": os.path.exists(os.path.expanduser("~/.config/pulse")) or Path("/run/user").exists(),
        "offline": True,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(alsa_cards(), indent=2))
