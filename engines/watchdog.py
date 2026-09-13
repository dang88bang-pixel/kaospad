#!/usr/bin/env python3
"""Watchdog: hängt eine überwachte Einheit, wird sie nach 5 Sekunden neu gestartet.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 5)

Vorher gab es im gesamten Repository keinen Watchdog (``grep -ri watchdog`` →
0 Treffer). Hängende Engine-Daemons blieben hängen; der manuelle Ausweg war
``POST /api/daemons/restart``.

Dieses Modul liefert die automatische Variante:

* Jede überwachte Einheit (``register``) meldet sich per :meth:`Watchdog.beat`.
* Bleibt ein Heartbeat mindestens ``timeout_s`` (Default **5 s**) aus, gilt die
  Einheit als hung und die registrierte ``restart``-Funktion wird genau einmal
  aufgerufen. Danach läuft die Frist neu.
* ``max_restarts`` begrenzt die Rettungsversuche; danach wird die Einheit als
  ``degraded`` gemeldet, statt endlos neu zu starten (kein Restart-Sturm).
* Ein Fehler in der Restart-Funktion wird protokolliert, nie weitergeworfen.

Kein Netzwerk, keine Subprozess-Magie: ``restart`` ist ein Callback, den der
Aufrufer liefert (logischer Rollen-Neustart in der One-App, echtes
``Popen``-Respawn im Multi-Daemon-Modus). Zeitquelle und Sweep-Intervall sind
injizierbar, damit die Tests deterministisch bleiben.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_SWEEP_S = 0.25

__all__ = ["DEFAULT_TIMEOUT_S", "RestartRecord", "Supervised", "Watchdog"]


@dataclass(slots=True)
class RestartRecord:
    """Ein Neustart (oder ein gescheiterter) – für Logs, UI und Tests."""

    unit: str
    ok: bool
    reason: str
    silent_for_s: float
    restarts: int
    error: str = ""
    at_monotonic_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "ok": self.ok,
            "reason": self.reason,
            "silent_for_s": round(self.silent_for_s, 4),
            "restarts": self.restarts,
            "error": self.error,
        }


@dataclass(slots=True)
class Supervised:
    """Zustand einer überwachten Einheit."""

    name: str
    restart: Callable[[str], Any] | None
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_restarts: int = 3
    last_beat_s: float = 0.0
    restarts: int = 0
    state: str = "healthy"
    last_error: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, now_s: float) -> dict[str, Any]:
        return {
            "unit": self.name,
            "state": self.state,
            "timeout_s": self.timeout_s,
            "max_restarts": self.max_restarts,
            "restarts": self.restarts,
            "silent_for_s": round(max(0.0, now_s - self.last_beat_s), 4),
            "last_error": self.last_error,
            "detail": dict(self.detail),
        }


class Watchdog:
    """Überwacht Heartbeats und startet hängende Einheiten neu."""

    def __init__(
        self,
        name: str = "kaoss-watchdog",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        sweep_s: float = DEFAULT_SWEEP_S,
        clock: Callable[[], float] = time.monotonic,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s muss > 0 sein")
        if sweep_s <= 0:
            raise ValueError("sweep_s muss > 0 sein")
        self.name = name
        self.timeout_s = float(timeout_s)
        self.sweep_s = float(sweep_s)
        self._clock = clock
        self._logger = logger
        self._lock = threading.RLock()
        self._units: dict[str, Supervised] = {}
        self._restarts: list[RestartRecord] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- Registrierung -----------------------------------------------------
    def register(
        self,
        name: str,
        restart: Callable[[str], Any] | None = None,
        *,
        timeout_s: float | None = None,
        max_restarts: int = 3,
        detail: dict[str, Any] | None = None,
    ) -> Supervised:
        with self._lock:
            unit = Supervised(
                name=name,
                restart=restart,
                timeout_s=float(timeout_s or self.timeout_s),
                max_restarts=int(max_restarts),
                last_beat_s=self._clock(),
                detail=dict(detail or {}),
            )
            self._units[name] = unit
            return unit

    def unregister(self, name: str) -> None:
        with self._lock:
            self._units.pop(name, None)

    def beat(self, name: str, **detail: Any) -> None:
        """Lebenszeichen – setzt die 5-Sekunden-Frist zurück."""
        with self._lock:
            unit = self._units.get(name)
            if unit is None:
                return
            unit.last_beat_s = self._clock()
            if unit.state == "hung":
                unit.state = "healthy"
            if detail:
                unit.detail.update(detail)

    # -- Sweep -------------------------------------------------------------
    def sweep(self) -> list[RestartRecord]:
        """Prüft alle Einheiten einmal; gibt die ausgelösten Neustarts zurück."""
        now = self._clock()
        with self._lock:
            due = [
                unit
                for unit in self._units.values()
                if unit.state != "degraded" and (now - unit.last_beat_s) >= unit.timeout_s
            ]
        records: list[RestartRecord] = []
        for unit in due:
            records.append(self._restart_unit(unit, now))
        return records

    def _restart_unit(self, unit: Supervised, now: float) -> RestartRecord:
        silent_for = now - unit.last_beat_s
        with self._lock:
            # Erst prüfen, dann zählen: eine verweigerte Rettung ist kein Neustart.
            if unit.restarts >= unit.max_restarts:
                unit.state = "degraded"
                record = RestartRecord(
                    unit=unit.name,
                    ok=False,
                    reason="max_restarts erreicht – Einheit als degraded markiert",
                    silent_for_s=silent_for,
                    restarts=unit.restarts,
                    error=unit.last_error,
                    at_monotonic_s=now,
                )
                self._restarts.append(record)
                self._log(record)
                return record
            unit.state = "restarting"

        error = ""
        ok = True
        try:
            if unit.restart is not None:
                result = unit.restart(unit.name)
                if isinstance(result, dict) and result.get("ok") is False:
                    ok = False
                    error = str(result.get("error", "restart abgelehnt"))
        except Exception as exc:  # noqa: BLE001 - Watchdog darf selbst nie crashen
            ok = False
            error = f"{type(exc).__name__}: {exc}"

        with self._lock:
            unit.restarts += 1
            unit.last_beat_s = self._clock()
            unit.state = "healthy" if ok else "hung"
            unit.last_error = error
            record = RestartRecord(
                unit=unit.name,
                ok=ok,
                reason=f"kein Heartbeat seit {silent_for:.3f}s (>= {unit.timeout_s:.1f}s)",
                silent_for_s=silent_for,
                restarts=unit.restarts,
                error=error,
                at_monotonic_s=now,
            )
            self._restarts.append(record)
        self._log(record)
        return record

    def _log(self, record: RestartRecord) -> None:
        if self._logger is None:
            return
        status = "neugestartet" if record.ok else "Restart fehlgeschlagen"
        self._logger(f"[watchdog] {record.unit}: {status} // {record.reason} // {record.error}".rstrip())

    # -- Hintergrundschleife ----------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
            self._thread.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout_s)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 - Schleife muss überleben
                pass
            self._stop.wait(self.sweep_s)

    # -- Sichtbarkeit ------------------------------------------------------
    @property
    def restart_count(self) -> int:
        with self._lock:
            return sum(unit.restarts for unit in self._units.values())

    def status(self, units: Iterable[str] | None = None) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            rows = [unit.as_dict(now) for unit in self._units.values()]
            history = [record.as_dict() for record in self._restarts]
        if units is not None:
            wanted = set(units)
            rows = [row for row in rows if row["unit"] in wanted]
        return {
            "ok": True,
            "watchdog": self.name,
            "timeout_s": self.timeout_s,
            "running": bool(self._thread is not None and self._thread.is_alive()),
            "units": sorted(rows, key=lambda row: row["unit"]),
            "restarts": self.restart_count,
            "history": history[-20:],
        }
