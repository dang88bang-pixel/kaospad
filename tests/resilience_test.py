#!/usr/bin/env python3
"""Phase-3-Test: Retry mit Backoff + Circuit Breaker + Deadline (rein lokal).

Geprüft wird die Schicht ``engines/resilience.py`` **und** ihre Verdrahtung an
den echten Grenzen (ALSA-Probe, Capture-Router). Alle Zeitfunktionen sind
injiziert, damit keine Wall-Clock-Schlaferei die Laufzeit oder das Ergebnis
bestimmt. Es wird kein Socket geöffnet und kein Prozess gestartet.
"""
from __future__ import annotations

import ast
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

from resilience import (  # noqa: E402
    CLOSED,
    HALF_OPEN,
    OPEN,
    REGISTRY,
    AttemptRecord,
    Deadline,
    DeadlineExceeded,
    RetryPolicy,
    call_with_timeout,
    with_retry,
)
from resilience import CircuitBreaker  # noqa: E402

CHECKS = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global CHECKS
    CHECKS += 1
    assert condition, f"CHECK FAILED: {label} // {detail}"


class FakeClock:
    """Deterministische Uhr, die nur auf Zuruf weiterläuft."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class Flaky:
    """Erst ``failures`` Fehler, dann Erfolg – zählt jeden Aufruf."""

    def __init__(self, failures: int, error: type[BaseException] = ConnectionRefusedError) -> None:
        self.failures = failures
        self.error = error
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error(f"transient #{self.calls}")
        return {"value": self.calls}


def policy_tests() -> None:
    for kwargs in (
        {"attempts": 0},
        {"factor": 0.5},
        {"jitter": 1.5},
        {"deadline_s": 0.0},
        {"base_delay_s": -0.01},
    ):
        try:
            RetryPolicy(**kwargs)
        except ValueError:
            check(f"Policy validiert {kwargs}", True)
        else:
            check(f"Policy validiert {kwargs}", False, kwargs)

    pol = RetryPolicy(attempts=5, base_delay_s=0.01, factor=2.0, max_delay_s=0.03, jitter=0.0)
    check(
        "Backoff exponentiell + gedeckelt",
        [round(pol.delay(n), 5) for n in (1, 2, 3, 4)] == [0.01, 0.02, 0.03, 0.03],
        [pol.delay(n) for n in (1, 2, 3, 4)],
    )
    jittered = [RetryPolicy(attempts=2, base_delay_s=0.1, jitter=0.25).delay(1, random.Random(seed)) for seed in range(8)]
    check(
        "Jitter bleibt in ±25 %",
        all(0.075 <= value <= 0.125 for value in jittered) and len(set(jittered)) > 1,
        jittered,
    )


def retry_tests() -> None:
    sleeper = RecordingSleep()
    flaky = Flaky(failures=2)
    pol = RetryPolicy(attempts=4, base_delay_s=0.01, factor=2.0, jitter=0.0)
    record = with_retry(flaky, pol, name="probe", sleep=sleeper)
    check("Retry: Erfolg im 3. Versuch", record.ok and record.value == {"value": 3}, record.as_dict())
    check("Retry: genau 3 Versuche protokolliert", record.tries == 3, record.attempts)
    check(
        "Retry: Backoff 10 ms dann 20 ms",
        [round(call * 1000, 3) for call in sleeper.calls] == [10.0, 20.0],
        sleeper.calls,
    )
    check("Retry: kein Fehler im Protokoll", record.error == "", record.error)

    hopeless = Flaky(failures=99)
    sleeper2 = RecordingSleep()
    lost = with_retry(hopeless, RetryPolicy(attempts=3, base_delay_s=0.005, jitter=0.0), sleep=sleeper2)
    check("Retry: nach 3 Versuchen aufgegeben", not lost.ok and hopeless.calls == 3, lost.as_dict())
    check("Retry: Fehlermeldung benennt letzte Ausnahme", "ConnectionRefusedError" in lost.error, lost.error)

    class Boom(ValueError):
        pass

    stubborn = Flaky(failures=99, error=Boom)
    no_retry = with_retry(stubborn, RetryPolicy(attempts=3), sleep=RecordingSleep())
    check("Retry: nicht-transienter Fehler wird nicht wiederholt", not no_retry.ok and stubborn.calls == 1, no_retry.as_dict())
    check("Retry: nicht-transient als nicht retryable markiert", no_retry.attempts[0]["retryable"] is False, no_retry.attempts)

    clock = FakeClock()
    calls = {"n": 0}

    def slow_fail() -> object:
        calls["n"] += 1
        clock.advance(0.02)
        raise TimeoutError("socket drain")

    limited = with_retry(
        slow_fail,
        RetryPolicy(attempts=10, base_delay_s=0.001, jitter=0.0, deadline_s=0.05),
        sleep=RecordingSleep(),
        clock=clock,
    )
    check("Retry: Deadline begrenzt die Versuche", not limited.ok and calls["n"] <= 3, (calls, limited.attempts))
    check("Retry: Deadline-Fehler benannt", "deadline" in limited.error, limited.error)

    def ok_fast() -> str:
        return "sofort"

    instant = with_retry(ok_fast, RetryPolicy(), sleep=RecordingSleep())
    check("Retry: sofortiger Erfolg ohne Sleep", instant.ok and instant.value == "sofort", instant.as_dict())


def breaker_tests() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker("unit", failure_threshold=3, reset_timeout_s=5.0, clock=clock)
    check("Breaker startet CLOSED", breaker.state == CLOSED, breaker.state)

    failing = Flaky(failures=99)
    for _ in range(3):
        result = breaker.call(failing, RetryPolicy(attempts=1, jitter=0.0), sleep=RecordingSleep())
        check("Breaker: Fehlversuch protokolliert", not result.ok, result.as_dict())
    check("Breaker öffnet nach 3 Fehlern", breaker.state == OPEN, breaker.state)

    probe = Flaky(failures=0)
    refused = breaker.call(probe, RetryPolicy(attempts=1), sleep=RecordingSleep())
    check("Breaker: Aufruf bei OFFEN verweigert", refused.refused and not refused.ok, refused.as_dict())
    check("Breaker: verweigerte Aufrufe rufen nichts auf", probe.calls == 0, probe.calls)
    check("Breaker: Verweigerung zählt", breaker.stats()["refusals"] >= 1, breaker.stats())

    clock.advance(5.0)
    check("Breaker wird nach Reset-Timeout HALF_OPEN", breaker.state == HALF_OPEN, breaker.state)
    probe2 = Flaky(failures=0)
    recovered = breaker.call(probe2, RetryPolicy(attempts=1), sleep=RecordingSleep())
    check("Breaker: Halb-offen-Probe kommt durch", recovered.ok and probe2.calls == 1, recovered.as_dict())
    check("Breaker: Erfolg schließt den Kreis", breaker.state == CLOSED, breaker.state)
    check("Breaker: Fehlerzähler zurückgesetzt", breaker.stats()["consecutive_failures"] == 0, breaker.stats())

    clock2 = FakeClock()
    reopening = CircuitBreaker("unit-reopen", failure_threshold=1, reset_timeout_s=2.0, clock=clock2)
    reopening.call(Flaky(99), RetryPolicy(attempts=1, jitter=0.0), sleep=RecordingSleep())
    check("Breaker: Schwelle 1 öffnet sofort", reopening.state == OPEN, reopening.state)
    clock2.advance(2.0)
    reopening.call(Flaky(99), RetryPolicy(attempts=1, jitter=0.0), sleep=RecordingSleep())
    check("Breaker: gescheiterte Probe öffnet erneut", reopening.state == OPEN, reopening.state)
    check("Breaker: Öffnungen gezählt", reopening.stats()["openings"] == 2, reopening.stats())

    clock3 = FakeClock()
    limited_probe = CircuitBreaker("unit-half-open-max", failure_threshold=1, reset_timeout_s=1.0, half_open_max=1, clock=clock3)
    limited_probe.call(Flaky(99), RetryPolicy(attempts=1, jitter=0.0), sleep=RecordingSleep())
    clock3.advance(1.0)
    first = limited_probe.allow()
    second = limited_probe.allow()
    check("Breaker: halb-offen lässt nur max 1 Probe zu", first is True and second is False, (first, second))

    manual = CircuitBreaker("unit-manual", failure_threshold=2, clock=FakeClock())
    manual.record_failure("a")
    manual.record_success()
    manual.record_failure("b")
    check("Breaker: Erfolg unterbricht die Fehlerkette", manual.state == CLOSED, manual.stats())
    manual.record_failure("c")
    check("Breaker: erneute Fehlerkette öffnet", manual.state == OPEN, manual.stats())


def timeout_tests() -> None:
    fast = call_with_timeout(lambda: {"ok": True}, 0.5, name="fast")
    check("Timeout: schneller Aufruf liefert Wert", fast.ok and fast.value == {"ok": True}, fast.as_dict())

    def slow() -> str:
        time.sleep(0.6)
        return "zu spät"

    late = call_with_timeout(slow, 0.1, name="slow")
    check("Timeout: Deadline schlägt fehl", not late.ok and "überschritten" in late.error, late.as_dict())

    def raiser() -> str:
        raise OSError("socket kaputt")

    broken = call_with_timeout(raiser, 0.5, name="raiser")
    check("Timeout: Ausnahme wird gemeldet statt geworfen", not broken.ok and "OSError" in broken.error, broken.as_dict())

    deadline = Deadline(0.05)
    check("Deadline: Restzeit positiv", 0 < deadline.remaining() <= 0.05, deadline.remaining())
    expired = Deadline(0.0001)
    time.sleep(0.002)
    check("Deadline: abgelaufen erkannt", expired.expired(), expired.remaining())
    try:
        expired.check("probe")
    except DeadlineExceeded:
        check("Deadline: check() wirft DeadlineExceeded", True)
    else:
        check("Deadline: check() wirft DeadlineExceeded", False)
    try:
        Deadline(0)
    except ValueError:
        check("Deadline: ungültiges Timeout abgelehnt", True)
    else:
        check("Deadline: ungültiges Timeout abgelehnt", False)


def registry_tests() -> None:
    REGISTRY.reset()
    one = REGISTRY.get("registry-a", failure_threshold=4, reset_timeout_s=7.0)
    two = REGISTRY.get("registry-a")
    check("Registry: gleicher Name liefert dieselbe Instanz", one is two, (one.name, two.name))
    REGISTRY.get("registry-b")
    names = [row["name"] for row in REGISTRY.snapshot(["registry-a", "registry-b"])]
    check("Registry: Snapshot sortiert und gefiltert", names == ["registry-a", "registry-b"], names)
    row = REGISTRY.snapshot(["registry-a"])[0]
    check(
        "Registry: Snapshot trägt Schwellen",
        row["failure_threshold"] == 4 and row["reset_timeout_s"] == 7.0 and row["state"] == CLOSED,
        row,
    )
    one.record_failure("x")
    one.record_failure("y")
    one.record_failure("z")
    one.record_failure("w")
    check("Registry: Breaker öffnet über Instanz", REGISTRY.snapshot(["registry-a"])[0]["state"] == OPEN, REGISTRY.snapshot(["registry-a"]))
    REGISTRY.reset("registry-a")
    check("Registry: gezieltes Reset", REGISTRY.snapshot(["registry-a"])[0]["state"] == CLOSED, REGISTRY.snapshot(["registry-a"]))
    check("Registry: AttemptRecord serialisierbar", set(AttemptRecord(ok=True).as_dict()) >= {"ok", "tries", "refused", "attempts"})


def integration_tests() -> None:
    """Verdrahtung an den echten Grenzen, ohne Hardware zu benötigen."""
    from local_audio_probe import BREAKER_NAME, alsa_cards

    probe = alsa_cards()
    resilience = probe.get("resilience")
    check("ALSA-Probe meldet Resilienz", isinstance(resilience, dict), probe.get("resilience"))
    check("ALSA-Probe benutzt resilience.py", resilience["guarded_by"] == "engines/resilience.py", resilience)
    check("ALSA-Probe hat Breaker-Namen", resilience["breaker"] == BREAKER_NAME, resilience)
    check("ALSA-Probe lief ohne Fehler", probe["ok"] is True and resilience["ok"] is True, resilience)
    check("ALSA-Probe: mindestens ein Versuch", resilience["tries"] >= 1, resilience)
    check("ALSA-Probe behält alte Felder", {"alsa_cards", "snd_nodes", "has_capture", "offline"} <= set(probe), sorted(probe))

    from audio_capture import OPEN_BREAKER_PREFIX, CaptureRouter

    router = CaptureRouter()
    info = router.open(route="internal_mic", mode="file", file_path=ROOT / "dist" / "gibt-es-nicht.wav")
    status = router.status()
    check("Capture: fehlende Datei öffnet nicht", info["opened"] is False, info)
    check("Capture: Versuch protokolliert", bool(info.get("attempts")), info.get("attempts"))
    check("Capture: Retry-Versuche gezählt", info["attempts"][0].get("tries", 0) >= 1, info["attempts"])
    breakers = {row["name"]: row for row in status["resilience"]["breakers"]}
    check(
        "Capture: Breaker für Backend angelegt",
        (OPEN_BREAKER_PREFIX + "file") in breakers,
        sorted(breakers),
    )
    check(
        "Capture: Fehler im Breaker sichtbar",
        breakers[OPEN_BREAKER_PREFIX + "file"]["failures"] >= 1,
        breakers.get(OPEN_BREAKER_PREFIX + "file"),
    )
    check("Capture: Status nennt Schicht", status["resilience"]["guarded_by"] == "engines/resilience.py", status["resilience"])
    check("Capture: zweiter Öffnungsversuch degradiert nicht", router.status()["armed"] is False, router.status())
    router.close()


def hygiene_tests() -> None:
    """Die Resilienz-Schicht selbst darf keine Netz-/Socket-Abhängigkeit haben."""
    source = (ROOT / "engines" / "resilience.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"socket", "urllib", "requests", "http", "ssl", "subprocess"}
    check("resilience.py ohne Netzwerk-Importe", not (imported & forbidden), sorted(imported & forbidden))
    check(
        "resilience.py nur lokale Standardbibliothek",
        imported <= {"__future__", "random", "threading", "time", "dataclasses", "typing"},
        sorted(imported),
    )
    check("resilience.py dokumentiert Umsetzung", "REAL-IMPLEMENTATION 2026-09-12" in source, "Marker fehlt")


def main() -> int:
    policy_tests()
    retry_tests()
    breaker_tests()
    timeout_tests()
    registry_tests()
    integration_tests()
    hygiene_tests()
    stats = {row["name"]: row["state"] for row in REGISTRY.snapshot() if row["name"].startswith(("capture:", "alsa", "action:"))}
    print(
        "resilience verified: "
        f"{CHECKS} checks // retry+backoff // circuit breaker CLOSED/OPEN/HALF_OPEN // "
        f"deadline // verdrahtet in {len(stats)} Breakern"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
