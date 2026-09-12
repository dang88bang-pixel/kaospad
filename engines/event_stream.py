#!/usr/bin/env python3
"""Event-Hub: eine Quelle für Polling (``/api/events``) und SSE (``/api/events/stream``).

Der Hub hängt direkt an ``SessionEngine._record``: jedes Ketten-Event wird
append-only gespeichert *und* an alle wartenden Abonnenten gepusht. SSE-Clients
bekommen dadurch echte Push-Events (inkl. Reconnect über ``Last-Event-ID``),
während das Polling-Endpoint unverändert aus demselben Ring liest – es gibt also
keine zweite, driftende Event-Quelle.

Nur In-Prozess-Pub/Sub, kein Socket, kein Cloud-Dienst.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 3)
Vorher hatte dieses Modul keinen einzigen ``except``-Block: ein einziges
kaputtes Event (z. B. ``seq`` als String) hätte ``publish()`` und damit
``SessionEngine._record`` – also die laufende Aktionskette – abgebrochen. Jetzt
werden Seq-Zugriffe robust gelesen, fehlerhafte Events gezählt und verworfen,
und ``stats()`` meldet ``errors``/``last_error`` statt sie zu verschlucken.
"""
from __future__ import annotations

import threading
from typing import Any


def _seq_of(event: Any) -> int:
    """Seq robust auslesen – ein kaputtes Event darf den Hub nicht stoppen."""
    try:
        return int(event.get("seq", 0))  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError):
        return 0


class EventSubscription:
    """Cursor-basierter Abonnent: liefert alles mit ``seq > cursor``."""

    def __init__(self, hub: "EventHub", since: int = 0, limit: int = 200) -> None:
        self.hub = hub
        self.cursor = int(since)
        self.limit = max(1, int(limit))
        self.closed = False
        self.delivered = 0

    def wait(self, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Blockiert bis neue Events vorliegen oder ``timeout`` verstreicht."""
        if self.closed:
            return []
        events = self.hub._wait_for(self, timeout)
        self.delivered += len(events)
        return events

    def close(self) -> None:
        self.closed = True
        self.hub._wake_all()

    @property
    def seq(self) -> int:
        return self.cursor


class EventHub:
    """Append-only Event-Ring + Condition-Variable für Push-Abonnenten."""

    def __init__(self, backlog: int = 4096) -> None:
        self.backlog = int(backlog)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._history: list[dict[str, Any]] = []
        self._published = 0
        self._subscribers: set[int] = set()
        # -- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 3): sichtbare Fehler.
        self._errors = 0
        self._last_error = ""

    # ------------------------------------------------------------------ #
    def publish(self, event: dict[str, Any]) -> None:
        try:
            payload = dict(event)
        except (TypeError, ValueError) as exc:
            self._record_error(f"publish: Event nicht kopierbar ({type(event).__name__}): {exc}")
            return
        raw_seq = payload.get("seq")
        if raw_seq is not None:
            try:
                int(raw_seq)
            except (TypeError, ValueError):
                # Ein Event ohne gültige Seq kann keinen Cursor weiterschreiben –
                # es wird verworfen statt still als seq=0 im Ring zu landen.
                self._record_error(f"publish: seq={raw_seq!r} ist keine ganze Zahl – Event verworfen")
                return
        with self._condition:
            self._history.append(payload)
            if len(self._history) > self.backlog:
                del self._history[: len(self._history) - self.backlog]
            self._published += 1
            self._condition.notify_all()

    def _record_error(self, message: str) -> None:
        with self._lock:
            self._errors += 1
            self._last_error = message

    def history(self, since: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return [event for event in self._history if _seq_of(event) > int(since)][: int(limit)]

    def last_seq(self) -> int:
        with self._lock:
            return _seq_of(self._history[-1]) if self._history else 0

    # ------------------------------------------------------------------ #
    def subscribe(self, since: int = 0, limit: int = 200) -> EventSubscription:
        subscription = EventSubscription(self, since=since, limit=limit)
        with self._lock:
            self._subscribers.add(id(subscription))
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        with self._lock:
            self._subscribers.discard(id(subscription))

    def _wake_all(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def _wait_for(self, subscription: EventSubscription, timeout: float) -> list[dict[str, Any]]:
        with self._condition:
            pending = [event for event in self._history if _seq_of(event) > subscription.cursor]
            if not pending:
                self._condition.wait(timeout=max(0.01, float(timeout)))
                pending = [event for event in self._history if _seq_of(event) > subscription.cursor]
            if not pending:
                return []
            batch = pending[: subscription.limit]
            try:
                payload = [dict(event) for event in batch]
                subscription.cursor = _seq_of(batch[-1])
            except (TypeError, ValueError) as exc:
                self._record_error(f"wait: Batch nicht lesbar: {exc}")
                return []
            return payload

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "published": self._published,
                "buffered": len(self._history),
                "subscribers": len(self._subscribers),
                "last_seq": _seq_of(self._history[-1]) if self._history else 0,
                # -- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 3)
                "errors": self._errors,
                "last_error": self._last_error,
            }


if __name__ == "__main__":  # pragma: no cover - manueller Smoke-Run
    import json

    hub = EventHub()
    sub = hub.subscribe(since=0)
    hub.publish({"seq": 1, "action": "boot"})
    print(json.dumps(sub.wait(timeout=0.2), ensure_ascii=False))
    print(json.dumps(hub.stats(), ensure_ascii=False))
