#!/usr/bin/env python3
"""Event-Hub: eine Quelle für Polling (``/api/events``) und SSE (``/api/events/stream``).

Der Hub hängt direkt an ``SessionEngine._record``: jedes Ketten-Event wird
append-only gespeichert *und* an alle wartenden Abonnenten gepusht. SSE-Clients
bekommen dadurch echte Push-Events (inkl. Reconnect über ``Last-Event-ID``),
während das Polling-Endpoint unverändert aus demselben Ring liest – es gibt also
keine zweite, driftende Event-Quelle.

Nur In-Prozess-Pub/Sub, kein Socket, kein Cloud-Dienst.
"""
from __future__ import annotations

import threading
from typing import Any


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

    # ------------------------------------------------------------------ #
    def publish(self, event: dict[str, Any]) -> None:
        with self._condition:
            self._history.append(dict(event))
            if len(self._history) > self.backlog:
                del self._history[: len(self._history) - self.backlog]
            self._published += 1
            self._condition.notify_all()

    def history(self, since: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return [event for event in self._history if int(event.get("seq", 0)) > int(since)][: int(limit)]

    def last_seq(self) -> int:
        with self._lock:
            return int(self._history[-1]["seq"]) if self._history else 0

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
            pending = [event for event in self._history if int(event.get("seq", 0)) > subscription.cursor]
            if not pending:
                self._condition.wait(timeout=max(0.01, float(timeout)))
                pending = [event for event in self._history if int(event.get("seq", 0)) > subscription.cursor]
            if not pending:
                return []
            batch = pending[: subscription.limit]
            subscription.cursor = int(batch[-1]["seq"])
            return [dict(event) for event in batch]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "published": self._published,
                "buffered": len(self._history),
                "subscribers": len(self._subscribers),
                "last_seq": int(self._history[-1]["seq"]) if self._history else 0,
            }


if __name__ == "__main__":  # pragma: no cover - manueller Smoke-Run
    import json

    hub = EventHub()
    sub = hub.subscribe(since=0)
    hub.publish({"seq": 1, "action": "boot"})
    print(json.dumps(sub.wait(timeout=0.2), ensure_ascii=False))
    print(json.dumps(hub.stats(), ensure_ascii=False))
