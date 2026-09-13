#!/usr/bin/env python3
"""Phase-5-Test: rotierende Logs bleiben größenbegrenzt und lesbar.

Schreibt in ein temporäres Verzeichnis unter ``dist/tmp/`` (bleibt im Repo-
Arbeitsbereich, kein /tmp-Pfad außerhalb des Snapshots) und prüft, dass die
belegten Bytes die Grenze ``max_bytes * (backups + 1)`` nie überschreiten.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

from log_rotation import DEFAULT_BACKUPS, DEFAULT_MAX_BYTES, RotatingLog, rotation_status  # noqa: E402

CHECKS = 0
WORKDIR = ROOT / "dist" / "tmp" / "log-rotation-test"


def check(label: str, condition: bool, detail: object = "") -> None:
    global CHECKS
    CHECKS += 1
    assert condition, f"CHECK FAILED: {label} // {detail}"


def main() -> int:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True, exist_ok=True)

    check("Default-Grenze 256 KiB", DEFAULT_MAX_BYTES == 256 * 1024, DEFAULT_MAX_BYTES)
    check("Default-Backups 3", DEFAULT_BACKUPS == 3, DEFAULT_BACKUPS)
    for kwargs in ({"max_bytes": 0}, {"backups": -1}):
        try:
            RotatingLog(WORKDIR / "x.log", **kwargs)
        except ValueError:
            check(f"Parameter validiert {kwargs}", True)
        else:
            check(f"Parameter validiert {kwargs}", False, kwargs)

    # -- Rotation und harte Obergrenze ------------------------------------
    log = RotatingLog(WORKDIR / "app.log", max_bytes=512, backups=2)
    for index in range(200):
        log.write("info", f"Zeile {index} mit etwas Inhalt", index=index, route="internal_mic")
    status = log.status()
    check("Alle Schreibvorgänge angenommen", status["writes"] == 200, status["writes"])
    check("Rotationen ausgelöst", status["rotations"] > 0, status["rotations"])
    check("Älteste Dateien verworfen", status["dropped"] > 0, status["dropped"])
    check(
        "Belegte Bytes bleiben unter der Grenze",
        status["bytes"] <= status["bounded_by_bytes"],
        (status["bytes"], status["bounded_by_bytes"]),
    )
    names = [row["name"] for row in status["files"]]
    check("Aktive Datei plus Backups", names[0] == "app.log" and all(name.startswith("app.log.") for name in names[1:]), names)
    check("Nicht mehr Dateien als backups+1", len(names) <= 3, names)

    # -- Inhalt bleibt gültiges JSON Lines --------------------------------
    lines = (WORKDIR / "app.log").read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    check("Aktive Datei ist JSON Lines", len(parsed) == len(lines) and len(parsed) > 0, len(lines))
    check("Felder vorhanden", {"ts", "level", "message", "index"} <= set(parsed[-1]), parsed[-1])
    check("Level großgeschrieben", parsed[-1]["level"] == "INFO", parsed[-1]["level"])
    check("Backups ebenfalls lesbar", all(
        json.loads(line) for line in (WORKDIR / "app.log.1").read_text(encoding="utf-8").splitlines()
    ), "app.log.1")

    # -- tail() liefert die letzten Einträge ------------------------------
    tail = log.tail(5)
    check("tail() begrenzt die Zeilenzahl", 0 < len(tail) <= min(5, len(lines)), (len(tail), len(lines)))
    check("tail() liefert die jüngsten", tail[-1]["message"] == "Zeile 199 mit etwas Inhalt", tail[-1]["message"])

    # -- Level-Helfer und nicht serialisierbare Werte ---------------------
    class Odd:
        def __repr__(self) -> str:
            return "odd"

    check("warning() schreibt", log.warning("Warnung", extra={"a": 1}) is True)
    check("error() schreibt", log.error("Fehler", payload=Odd()) is True)
    odd_line = json.loads((WORKDIR / "app.log").read_text(encoding="utf-8").splitlines()[-1])
    check("Nicht serialisierbar wird als Text abgelegt", odd_line["payload"] == "odd", odd_line)

    # -- Umlaute bleiben UTF-8 --------------------------------------------
    log.info("Mikrofon nicht erreichbar – DÄMON", grund="usb getrennt")
    umlaut = json.loads((WORKDIR / "app.log").read_text(encoding="utf-8").splitlines()[-1])
    check("Umlaute bleiben erhalten", "DÄMON" in umlaut["message"], umlaut)

    # -- Schreibfehler auf totem Pfad crashen nicht -----------------------
    broken = RotatingLog(WORKDIR / "app.log" / "unmoeglich.log", max_bytes=64, backups=1)
    ok = broken.write("error", "das darf nicht crashen")
    check("Schreibfehler wird gemeldet statt geworfen", ok is False, broken.status())
    check("Schreibfehler im Status sichtbar", bool(broken.status()["errors"]), broken.status()["errors"])

    # -- rotation_status() bündelt mehrere Logs ---------------------------
    second = RotatingLog(WORKDIR / "daemon.log", max_bytes=256, backups=1)
    second.info("daemon bereit")
    rows = rotation_status(log, second)
    check("rotation_status liefert beide Logs", [row["path"].split("/")[-1] for row in rows] == ["app.log", "daemon.log"], rows)
    check("Statusmeldungen ok", all(row["ok"] is True for row in rows), rows)
    check("Grenze pro Log korrekt", rows[1]["bounded_by_bytes"] == 256 * 2, rows[1])

    shutil.rmtree(WORKDIR, ignore_errors=True)
    print(
        "log rotation verified: "
        f"{CHECKS} checks // Grenze max_bytes*(backups+1) // JSON Lines // "
        "Umlaute // Schreibfehler ohne Crash"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
