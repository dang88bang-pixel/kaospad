#!/usr/bin/env python3
"""Lokale Resilienz-Schicht: Retry mit Backoff, Circuit Breaker, Deadline.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 3)

Warum das hier steht: Das Audit (``docs/audit/GAP-MATRIX.csv``, Phase 3) hat
gezeigt, dass im gesamten Repository **kein** Retry, kein Backoff und kein
Circuit Breaker existierte – der einzige Treffer für ``retry`` war
``app.py`` mit einem SSE-Kommentar ``retry: 2000``. Die Zero-Cloud-Architektur
hat zwar keine externen Netzwerkaufrufe, aber sehr wohl fehleranfällige
Grenzen: Unix-/TCP-Sockets zu den Engine-Ports 8080-8085, ``arecord``-Prozesse,
``/proc/asound``-Zugriffe beim USB-Stecken und die Daemon-Neustarts.

Diese Schicht liefert drei Bausteine, die an genau diesen Grenzen benutzt
werden:

* :class:`RetryPolicy` / :func:`with_retry` – begrenzter Wiederholungsversuch
  mit exponentiellem Backoff, Jitter und absoluter Deadline.
* :class:`CircuitBreaker` – öffnet nach N Fehlern, verweigert Aufrufe für
  ``reset_timeout_s`` und lässt danach einen einzelnen Halb-offen-Probeversuch
  durch. Kein stiller Dauer-Retry gegen eine tote Komponente.
* :func:`call_with_timeout` / :class:`Deadline` – harte Zeitgrenze für
  blockierende lokale Aufrufe (Socket-Drain, Subprozess-Wait).

Regeln: Es werden ausschließlich lokale Aufrufe geschützt, es wird kein Socket
geöffnet und kein DNS gemacht. Alle Zeitfunktionen sind injizierbar, damit die
Tests deterministisch bleiben (keine ``sleep``-Wall-Clock-Abhängigkeit).
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"

__all__ = [
    "AttemptRecord",
    "CircuitBreaker",
    "Deadline",
    "DeadlineExceeded",
    "ResilienceError",
    "ResilienceRegistry",
    "RetryPolicy",
    "REGISTRY",
    "call_with_timeout",
    "default_retryable",
    "with_retry",
]


class ResilienceError(RuntimeError):
    """Aufruf wurde abgelehnt (Breaker offen) oder alle Versuche sind gescheitert."""


class DeadlineExceeded(TimeoutError):
    """Die absolute Zeitgrenze wurde erreicht."""


#: Fehler, die einen neuen Versuch wert sind (transiente lokale Ausfälle).
RETRYABLE_TYPES: tuple[type[BaseException], ...] = (
    OSError,
    ConnectionError,
    TimeoutError,
    BlockingIOError,
)


def default_retryable(exc: BaseException) -> bool:
    """``True`` für transiente lokale Fehler (Socket/Timeout/Prozess)."""
    return isinstance(exc, RETRYABLE_TYPES)


@dataclass(slots=True)
class RetryPolicy:
    """Begrenzung und Takt der Wiederholungen.

    ``delay(n)`` = ``min(base_delay_s * factor**(n-1), max_delay_s)``
    plus Jitter von bis zu ±``jitter`` (0.0 = deterministisch).
    """

    attempts: int = 3
    base_delay_s: float = 0.05
    factor: float = 2.0
    max_delay_s: float = 1.0
    jitter: float = 0.25
    deadline_s: float | None = None
    retry_on: Callable[[BaseException], bool] = default_retryable

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts muss >= 1 sein")
        if self.base_delay_s < 0 or self.max_delay_s < 0:
            raise ValueError("Delays dürfen nicht negativ sein")
        if self.factor < 1.0:
            raise ValueError("factor muss >= 1.0 sein")
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError("jitter muss in [0, 1] liegen")
        if self.deadline_s is not None and self.deadline_s <= 0:
            raise ValueError("deadline_s muss > 0 sein")

    def delay(self, attempt: int, rng: random.Random | None = None) -> float:
        """Backoff für Versuch ``attempt`` (1-basiert, bereits mit Jitter)."""
        raw = min(self.base_delay_s * (self.factor ** max(0, attempt - 1)), self.max_delay_s)
        if self.jitter and rng is not None:
            raw *= 1.0 + rng.uniform(-self.jitter, self.jitter)
        return max(0.0, raw)


@dataclass(slots=True)
class AttemptRecord:
    """Ergebnis eines geschützten Aufrufs inklusive Versuchsprotokoll."""

    ok: bool
    value: Any = None
    error: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    refused: bool = False
    breaker: str = ""

    @property
    def tries(self) -> int:
        return len(self.attempts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "tries": self.tries,
            "refused": self.refused,
            "breaker": self.breaker,
            "attempts": list(self.attempts),
        }


def with_retry(
    fn: Callable[[], Any],
    policy: RetryPolicy | None = None,
    *,
    name: str = "",
    on_attempt: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
    rng: random.Random | None = None,
) -> AttemptRecord:
    """Ruft ``fn`` mit Retry/Backoff/Deadline auf – liefert nie eine Exception.

    Der Rückgabewert ist immer ein :class:`AttemptRecord`; der Aufrufer
    entscheidet, ob er ``record.value`` benutzt oder degradiert. Damit bleibt
    die Regel „keine Ausnahme verlässt eine Hardware-Grenze“ erhalten.
    """
    pol = policy or RetryPolicy()
    rand = rng if rng is not None else random.Random(0x5EED)
    started = clock()
    record = AttemptRecord(ok=False, breaker=name)
    last_error: BaseException | None = None

    for index in range(1, pol.attempts + 1):
        if pol.deadline_s is not None and clock() - started > pol.deadline_s:
            record.error = f"deadline {pol.deadline_s:.3f}s überschritten"
            record.attempts.append({"n": index, "ok": False, "error": record.error, "skipped": True})
            break
        step_started = clock()
        try:
            value = fn()
        except BaseException as exc:  # noqa: BLE001 - Grenze darf nichts durchlassen
            elapsed_ms = (clock() - step_started) * 1000.0
            last_error = exc
            retryable = bool(pol.retry_on(exc))
            record.attempts.append({
                "n": index,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "retryable": retryable,
                "elapsed_ms": round(elapsed_ms, 4),
            })
            if on_attempt:
                on_attempt(record.attempts[-1])
            if not retryable:
                record.error = f"{type(exc).__name__}: {exc}"
                return record
            if index >= pol.attempts:
                break
            delay = pol.delay(index, rand)
            if pol.deadline_s is not None:
                remaining = pol.deadline_s - (clock() - started)
                if remaining <= 0:
                    record.error = f"deadline {pol.deadline_s:.3f}s überschritten"
                    break
                delay = min(delay, remaining)
            record.attempts[-1]["delay_ms"] = round(delay * 1000.0, 4)
            sleep(delay)
            continue

        record.ok = True
        record.value = value
        record.error = ""
        record.attempts.append({
            "n": index,
            "ok": True,
            "elapsed_ms": round((clock() - step_started) * 1000.0, 4),
        })
        if on_attempt:
            on_attempt(record.attempts[-1])
        return record

    if not record.error:
        record.error = f"{pol.attempts} Versuche gescheitert" + (
            f" – zuletzt {type(last_error).__name__}: {last_error}" if last_error else ""
        )
    return record


class Deadline:
    """Monotone Restzeituhr für blockierende lokale Aufrufe."""

    def __init__(self, timeout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s muss > 0 sein")
        self._timeout_s = float(timeout_s)
        self._clock = clock
        self._end = clock() + float(timeout_s)

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    def remaining(self) -> float:
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def check(self, what: str = "call") -> None:
        if self.expired():
            raise DeadlineExceeded(f"{what}: {self._timeout_s:.3f}s überschritten")


def call_with_timeout(
    fn: Callable[[], Any],
    timeout_s: float,
    *,
    name: str = "call",
) -> AttemptRecord:
    """Führt ``fn`` in einem Daemon-Thread mit harter Zeitgrenze aus.

    Ehrliche Grenze: Ein blockierender Systemaufruf (z. B. ``recv`` auf einem
    Unix-Socket ohne Timeout) lässt sich in Python nicht abbrechen. Der Thread
    wird dann zurückgelassen, der Aufrufer bekommt aber pünktlich sein
    ``DeadlineExceeded``-Ergebnis und kann degradieren, statt zu hängen.
    """
    box: dict[str, Any] = {}
    finished = threading.Event()

    def runner() -> None:
        try:
            box["value"] = fn()
            box["ok"] = True
        except BaseException as exc:  # noqa: BLE001
            box["error"] = f"{type(exc).__name__}: {exc}"
            box["ok"] = False
        finally:
            finished.set()

    started = time.perf_counter()
    worker = threading.Thread(target=runner, name=f"resilience-{name}", daemon=True)
    worker.start()
    if not finished.wait(timeout_s):
        return AttemptRecord(
            ok=False,
            error=f"{name}: {timeout_s:.3f}s überschritten",
            attempts=[{"n": 1, "ok": False, "error": "deadline", "elapsed_ms": round(timeout_s * 1000.0, 3)}],
            breaker=name,
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if box.get("ok"):
        return AttemptRecord(ok=True, value=box.get("value"), attempts=[
            {"n": 1, "ok": True, "elapsed_ms": round(elapsed_ms, 4)},
        ], breaker=name)
    return AttemptRecord(ok=False, error=str(box.get("error", "unbekannter Fehler")), attempts=[
        {"n": 1, "ok": False, "error": str(box.get("error", "")), "elapsed_ms": round(elapsed_ms, 4)},
    ], breaker=name)


class CircuitBreaker:
    """Zustandsautomat CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

    ``failure_threshold`` aufeinanderfolgende Fehler öffnen den Kreis; danach
    werden Aufrufe für ``reset_timeout_s`` sofort abgelehnt (kein versteckter
    Retry-Sturm). Ein einzelner Probeversuch im Halb-offen-Zustand entscheidet,
    ob der Kreis wieder schließt oder erneut öffnet.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_timeout_s: float = 5.0,
        half_open_max: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold muss >= 1 sein")
        if reset_timeout_s <= 0:
            raise ValueError("reset_timeout_s muss > 0 sein")
        if half_open_max < 1:
            raise ValueError("half_open_max muss >= 1 sein")
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self.half_open_max = half_open_max
        self._clock = clock
        self._lock = threading.RLock()
        self._state = CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._half_open_calls = 0
        self._stats = {"calls": 0, "successes": 0, "failures": 0, "refusals": 0, "openings": 0, "half_open_probes": 0}
        self._last_error = ""

    # -- Zustand -----------------------------------------------------------
    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_half_open()
            return self._state

    def _maybe_half_open(self) -> None:
        if self._state == OPEN and (self._clock() - self._opened_at) >= self.reset_timeout_s:
            self._state = HALF_OPEN
            self._half_open_calls = 0

    def allow(self) -> bool:
        with self._lock:
            self._maybe_half_open()
            if self._state == CLOSED:
                return True
            if self._state == HALF_OPEN:
                if self._half_open_calls < self.half_open_max:
                    self._half_open_calls += 1
                    self._stats["half_open_probes"] += 1
                    return True
                return False
            self._stats["refusals"] += 1
            return False

    def record_success(self) -> None:
        with self._lock:
            self._stats["successes"] += 1
            self._consecutive_failures = 0
            if self._state in {HALF_OPEN, OPEN}:
                self._state = CLOSED
            self._half_open_calls = 0

    def record_failure(self, error: str = "") -> None:
        with self._lock:
            self._stats["failures"] += 1
            self._last_error = error
            if self._state == HALF_OPEN:
                self._open(f"probe fehlgeschlagen: {error}")
                return
            self._consecutive_failures += 1
            if self._state == CLOSED and self._consecutive_failures >= self.failure_threshold:
                self._open(f"{self._consecutive_failures} aufeinanderfolgende Fehler: {error}")

    def _open(self, reason: str) -> None:
        self._state = OPEN
        self._opened_at = self._clock()
        self._stats["openings"] += 1
        self._last_error = reason

    def reset(self) -> None:
        with self._lock:
            self._state = CLOSED
            self._consecutive_failures = 0
            self._half_open_calls = 0
            self._last_error = ""

    def stats(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._stats)
            snapshot.update({
                "name": self.name,
                "state": self.state,
                "consecutive_failures": self._consecutive_failures,
                "failure_threshold": self.failure_threshold,
                "reset_timeout_s": self.reset_timeout_s,
                "last_error": self._last_error,
                "open_for_s": round(max(0.0, self.reset_timeout_s - (self._clock() - self._opened_at)), 4)
                if self._state == OPEN
                else 0.0,
            })
            return snapshot

    # -- geschützter Aufruf ------------------------------------------------
    def call(
        self,
        fn: Callable[[], Any],
        policy: RetryPolicy | None = None,
        *,
        on_attempt: Callable[[dict[str, Any]], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
        rng: random.Random | None = None,
    ) -> AttemptRecord:
        """``fn`` hinter Breaker **und** Retry – Ergebnis ist ein ``AttemptRecord``."""
        with self._lock:
            self._stats["calls"] += 1
        if not self.allow():
            return AttemptRecord(
                ok=False,
                error=f"breaker {self.name} ist OFFEN ({self._last_error or 'keine Details'})",
                refused=True,
                breaker=self.name,
            )
        record = with_retry(
            fn,
            policy,
            name=self.name,
            on_attempt=on_attempt,
            sleep=sleep,
            clock=clock,
            rng=rng,
        )
        if record.ok:
            self.record_success()
        else:
            self.record_failure(record.error)
        return record

    def wrap(
        self,
        fn: Callable[[], Any],
        policy: RetryPolicy | None = None,
    ) -> AttemptRecord:
        """Alias für :meth:`call` (Lesbarkeit an den Aufrufstellen)."""
        return self.call(fn, policy)


class ResilienceRegistry:
    """Benannte Breaker, damit Status und Tests dieselbe Instanz sehen."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._breakers: dict[str, CircuitBreaker] = {}
        self._defaults: dict[str, Any] = {}

    def configure(self, **defaults: Any) -> None:
        with self._lock:
            self._defaults.update(defaults)

    def get(
        self,
        name: str,
        *,
        failure_threshold: int | None = None,
        reset_timeout_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> CircuitBreaker:
        with self._lock:
            existing = self._breakers.get(name)
            if existing is not None:
                return existing
            breaker = CircuitBreaker(
                name,
                failure_threshold=failure_threshold or int(self._defaults.get("failure_threshold", 3)),
                reset_timeout_s=reset_timeout_s or float(self._defaults.get("reset_timeout_s", 5.0)),
                clock=clock,
            )
            self._breakers[name] = breaker
            return breaker

    def snapshot(self, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            breakers = list(self._breakers.values())
        rows = [breaker.stats() for breaker in breakers]
        if names is not None:
            wanted = set(names)
            rows = [row for row in rows if row["name"] in wanted]
        return sorted(rows, key=lambda row: row["name"])

    def reset(self, name: str | None = None) -> None:
        with self._lock:
            targets = [self._breakers[name]] if name and name in self._breakers else list(self._breakers.values())
        for breaker in targets:
            breaker.reset()


REGISTRY = ResilienceRegistry()
