#!/usr/bin/env python3
"""Phase-5-Test: Watchdog startet hängende Einheiten nach 5 Sekunden neu.

Deterministisch über eine injizierte Uhr – es wird keine echte Sekunde
gewartet und kein Prozess gestartet.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

from watchdog import DEFAULT_TIMEOUT_S, Watchdog  # noqa: E402

CHECKS = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global CHECKS
    CHECKS += 1
    assert condition, f"CHECK FAILED: {label} // {detail}"


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def main() -> int:
    check("Standard-Timeout ist 5 s", DEFAULT_TIMEOUT_S == 5.0, DEFAULT_TIMEOUT_S)
    try:
        Watchdog("ungueltig", timeout_s=0)
    except ValueError:
        check("timeout_s=0 abgelehnt", True)
    else:
        check("timeout_s=0 abgelehnt", False)

    # -- gesunder Dienst wird nie neu gestartet ---------------------------
    clock = FakeClock()
    logs: list[str] = []
    wd = Watchdog("kaoss-watchdog-test", timeout_s=5.0, clock=clock, logger=logs.append)
    restarts: list[str] = []
    wd.register("engine:8082", restart=lambda name: restarts.append(name) or {"ok": True})
    for _ in range(10):
        clock.advance(1.0)
        wd.beat("engine:8082")
        wd.sweep()
    check("Herzschlag hält den Dienst am Leben", restarts == [], restarts)
    check("Kein Neustart im Status", wd.restart_count == 0, wd.status()["restarts"])
    check("Zustand healthy", wd.status()["units"][0]["state"] == "healthy", wd.status()["units"][0])

    # -- hängender Dienst: Neustart nach >5 s -----------------------------
    clock.advance(5.0)
    triggered = wd.sweep()
    check("Nach 5 s ohne Herzschlag ausgelöst", len(triggered) == 1, triggered)
    check("Restart-Callback aufgerufen", restarts == ["engine:8082"], restarts)
    record = triggered[0]
    check("Grund nennt die Stille", "kein Heartbeat seit" in record.reason and record.silent_for_s >= 5.0, record.as_dict())
    check("Neustart als ok gemeldet", record.ok is True and record.restarts == 1, record.as_dict())
    check("Logzeile geschrieben", any("engine:8082" in line and "neugestartet" in line for line in logs), logs)
    check("Frist nach Neustart zurückgesetzt", wd.sweep() == [], wd.status()["units"][0])
    check("Status zählt einen Neustart", wd.restart_count == 1 and wd.status()["restarts"] == 1, wd.status()["restarts"])

    # -- kaputte Restart-Funktion wird nicht weitergeworfen ---------------
    clock2 = FakeClock()
    wd2 = Watchdog("kaputt", timeout_s=2.0, clock=clock2)

    def exploding(name: str) -> dict:
        raise RuntimeError("respawn fehlgeschlagen")

    wd2.register("audio:8081", restart=exploding)
    clock2.advance(3.0)
    failed = wd2.sweep()
    check("Fehler im Restart wird gemeldet statt geworfen", failed[0].ok is False, failed[0].as_dict())
    check("Fehlertext protokolliert", "RuntimeError" in failed[0].error, failed[0].error)
    check("Einheit bleibt hung", wd2.status()["units"][0]["state"] == "hung", wd2.status()["units"][0])

    # -- Restart-Sturm wird begrenzt (degraded) ---------------------------
    clock3 = FakeClock()
    wd3 = Watchdog("begrenzt", timeout_s=1.0, clock=clock3)
    attempts: list[str] = []
    wd3.register("dsp:8084", restart=lambda name: attempts.append(name) or {"ok": True}, max_restarts=2)
    states = []
    for _ in range(5):
        clock3.advance(1.5)
        wd3.sweep()
        states.append(wd3.status()["units"][0]["state"])
    check("Restart-Limit greift", len(attempts) == 2, attempts)
    check("Danach degraded", states[-1] == "degraded", states)
    check("Degraded löst nichts mehr aus", wd3.restart_count == 2, wd3.status())
    degraded_note = [row for row in wd3.status()["history"] if not row["ok"]]
    check("Degradierung im Verlauf", bool(degraded_note) and "max_restarts" in degraded_note[-1]["reason"], wd3.status()["history"])

    # -- Einheiten ohne Restart-Funktion werden nur markiert --------------
    clock4 = FakeClock()
    wd4 = Watchdog("beobachter", timeout_s=1.0, clock=clock4)
    wd4.register("nur-beobachtet")
    clock4.advance(2.0)
    observed = wd4.sweep()
    check("Ohne Callback kein Absturz", observed[0].ok is True, observed[0].as_dict())
    check("Ohne Callback zählt der Versuch", wd4.restart_count == 1, wd4.restart_count)

    # -- Hintergrundschleife mit echter Uhr (kurz, aber real) -------------
    events: list[str] = []
    live = Watchdog("live-loop", timeout_s=0.05, sweep_s=0.01, logger=lambda line: events.append(line))
    live.register("worker", restart=lambda name: events.append(f"restart:{name}") or {"ok": True})
    live.start()
    check("Schleife läuft", live.status()["running"] is True, live.status())
    deadline = time.time() + 2.0
    while time.time() < deadline and not any(item.startswith("restart:") for item in events):
        time.sleep(0.01)
    live.stop()
    check("Schleife startet hängende Einheit automatisch", any(item.startswith("restart:") for item in events), events)
    check("Nach stop() nicht mehr aktiv", live.status()["running"] is False, live.status())
    check("beat() auf unbekannte Einheit ist harmlos", (live.beat("gibt-es-nicht") is None) is True)
    live.unregister("worker")
    check("unregister entfernt die Einheit", [row["unit"] for row in live.status()["units"]] == [], live.status()["units"])

    # -- unregister/beat im Parallelbetrieb (Thread-Sicherheit) -----------
    clock5 = FakeClock()
    wd5 = Watchdog("parallel", timeout_s=1.0, clock=clock5)
    for index in range(8):
        wd5.register(f"unit-{index}", restart=lambda name: {"ok": True})

    def hammer() -> None:
        for _ in range(50):
            wd5.beat("unit-0")
            wd5.status()

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    check("Paralleler Zugriff ohne Exception", True)
    check("Status bleibt konsistent", len(wd5.status()["units"]) == 8, wd5.status()["units"])

    print(
        "watchdog verified: "
        f"{CHECKS} checks // Neustart nach >5 s Stille // Restart-Limit + degraded // "
        "Hintergrundschleufe // thread-sicher"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
