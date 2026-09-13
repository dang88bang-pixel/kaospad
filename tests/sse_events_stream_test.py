#!/usr/bin/env python3
"""SSE ``/api/events/stream``: echte Push-Events zusätzlich zum Polling.

Geprüft wird gegen einen live laufenden One-App-Server:

* ``text/event-stream`` + ``hello``-Handshake mit Hub-Statistik,
* Ketten-Events kommen *ohne* Polling an (Latenzmessung gegen den POST),
* ``id:``-Zeilen -> Reconnect über ``Last-Event-ID`` setzt lückenlos fort,
* Heartbeat-Kommentare halten die Verbindung offen,
* ``max=N`` beendet den Stream sauber mit ``event: done``,
* ``/api/events`` liefert dieselben Seqs (eine Event-Quelle, kein Drift),
* SSE-Verbindung bleibt Loopback (Zero-Cloud).
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    assert condition, f"FAIL {label}: {detail}"
    CHECKS.append(label)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SseClient:
    """Minimaler EventSource-Ersatz über einem rohen Loopback-Socket."""

    def __init__(self, port: int, query: str = "", last_event_id: str | None = None) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=8)
        headers = f"GET /api/events/stream{query} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: text/event-stream\r\n"
        if last_event_id:
            headers += f"Last-Event-ID: {last_event_id}\r\n"
        self.sock.sendall((headers + "\r\n").encode())
        self.buffer = b""
        self.raw_seen = b""
        self.headers = self._read_headers()

    def _read_headers(self) -> dict[str, str]:
        while b"\r\n\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise AssertionError("SSE stream closed before headers")
            self.buffer += chunk
            self.raw_seen += chunk
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        lines = head.decode("utf-8", "replace").splitlines()
        return {
            **{"status": lines[0]},
            **{
                key.strip().lower(): value.strip()
                for key, _, value in (line.partition(":") for line in lines[1:])
            },
        }

    def read_events(self, count: int = 1, timeout: float = 8.0) -> list[dict[str, object]]:
        """Liest komplette SSE-Events (event/data/id) bis ``count`` erreicht ist."""
        deadline = time.time() + timeout
        events: list[dict[str, object]] = []
        while len(events) < count and time.time() < deadline:
            while b"\n\n" in self.buffer:
                raw, self.buffer = self.buffer.split(b"\n\n", 1)
                parsed = self._parse(raw.decode("utf-8", "replace"))
                if parsed:
                    events.append(parsed)
                    if len(events) >= count:
                        break
            if len(events) >= count:
                break
            self.sock.settimeout(max(0.1, deadline - time.time()))
            try:
                chunk = self.sock.recv(8192)
            except socket.timeout:
                continue
            if not chunk:
                break
            self.buffer += chunk
            self.raw_seen += chunk
        return events

    def read_heartbeat(self, timeout: float = 6.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if b": heartbeat" in self.buffer:
                return True
            self.sock.settimeout(max(0.1, deadline - time.time()))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return b": heartbeat" in self.raw_seen
            self.buffer += chunk
            self.raw_seen += chunk
        return b": heartbeat" in self.raw_seen

    @staticmethod
    def _parse(raw: str) -> dict[str, object] | None:
        event: dict[str, object] = {"event": "message", "id": None, "raw": raw}
        data_lines = []
        for line in raw.splitlines():
            if line.startswith(":"):
                event["comment"] = line[1:].strip()
            elif line.startswith("event:"):
                event["event"] = line.split(":", 1)[1].strip()
            elif line.startswith("id:"):
                event["id"] = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
            elif line.startswith("retry:"):
                event["retry"] = line.split(":", 1)[1].strip()
        if data_lines:
            event["data"] = json.loads("\n".join(data_lines))
        if not data_lines and "comment" not in event:
            return None
        return event

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def post_action(port: int, action: str, **params) -> float:
    payload = json.dumps({"action": action, **params}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/action",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310 local only
        response.read()
    return (time.perf_counter() - started) * 1000.0


def main() -> int:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py"), "--host", "127.0.0.1", "--port", str(port), "--no-restore"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 12
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.0) as response:  # noqa: S310
                    if json.loads(response.read().decode()).get("ok"):
                        break
            except Exception:  # noqa: BLE001 - Server startet noch
                time.sleep(0.1)
        else:
            raise AssertionError("one-app server not ready")

        last_seq = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5).read().decode()  # noqa: S310
        )["chain"]["last_seq"] or 0

        client = SseClient(port, f"?since={last_seq}&heartbeat=2")
        check("sse content type", client.headers.get("content-type", "").startswith("text/event-stream"), client.headers)
        check("sse no store", client.headers.get("cache-control") == "no-store", client.headers)
        check("sse zero cloud header", client.headers.get("x-kaoss-zero-cloud") == "true", client.headers)

        hello = client.read_events(1)[0]
        check("sse hello event", hello["event"] == "hello" and hello["data"]["transport"] == "sse", hello)
        check("sse hello retry", b"retry: 2000" in client.raw_seen, client.raw_seen[:120])
        check("sse hello hub", hello["data"]["stream"]["subscribers"] >= 1, hello["data"])

        # Live-Push: Aktion auslösen und das Event ohne Polling erhalten.
        latencies: list[float] = []

        def trigger() -> None:
            time.sleep(0.4)
            for action, params in (
                ("input.select", {"input": "internal_mic"}),
                ("permission.check", {}),
                ("permission.grant", {"key": "record_audio", "granted": True}),
            ):
                latencies.append(post_action(port, action, **params))
                time.sleep(0.15)

        thread = threading.Thread(target=trigger, daemon=True)
        started = time.perf_counter()
        thread.start()
        events = client.read_events(3, timeout=8)
        push_ms = (time.perf_counter() - started) * 1000.0
        check("sse pushed 3 events", len(events) == 3, [item.get("data", {}).get("action") for item in events])
        actions = [item["data"]["action"] for item in events]
        check("sse push order", actions == ["input.select", "permission.check", "permission.grant"], actions)
        check("sse ids ascending", [int(item["id"]) for item in events] == sorted(int(item["id"]) for item in events), [item["id"] for item in events])
        check("sse ids continue", int(events[0]["id"]) == last_seq + 1, (events[0]["id"], last_seq))
        check("sse detail summary", "detail_summary" in events[0]["data"], events[0]["data"])
        check("sse no full detail leak", "detail" not in events[0]["data"], sorted(events[0]["data"]))
        check("sse push fast", push_ms < 6000, {"push_ms": round(push_ms, 1), "post_ms": [round(v, 1) for v in latencies]})
        client.close()

        # Reconnect mit Last-Event-ID: lückenlos weiter, kein Doppel-Event.
        resume_id = events[-1]["id"]
        resumed = SseClient(port, "?heartbeat=2", last_event_id=resume_id)
        post_action(port, "audio.start", sample_rate_hz=96_000, frames_per_buffer=128)
        chain_events = [item for item in resumed.read_events(2, timeout=8) if item["event"] == "chain"]
        check("sse resume chain event", bool(chain_events), resumed.raw_seen[:300])
        next_event = chain_events[0]
        check("sse resume continues", int(next_event["id"]) == int(resume_id) + 1, (next_event["id"], resume_id))
        check("sse resume action", next_event["data"]["action"] == "audio.start", next_event["data"])
        resumed.close()

        # Heartbeat hält die Verbindung offen, auch ohne Aktionen.
        idle = SseClient(port, "?heartbeat=1&since=999999")
        idle.read_events(1, timeout=3)  # hello
        check("sse heartbeat", idle.read_heartbeat(timeout=6) is True, idle.raw_seen[:200])
        idle.close()

        # max=N beendet den Stream mit done.
        bounded = SseClient(port, f"?since={last_seq}&max=2&heartbeat=1")
        bounded_events = bounded.read_events(6, timeout=10)
        names = [item["event"] for item in bounded_events]
        check("sse bounded done", "done" in names, names)
        bounded.close()

        # Polling bleibt dieselbe Quelle.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events?since=0", timeout=5) as response:  # noqa: S310
            poll = json.loads(response.read().decode())
        seqs = [event["seq"] for event in poll["events"]]
        check("poll same source", seqs == sorted(seqs) and len(seqs) == len(set(seqs)), seqs)
        check("poll full detail", "detail" in poll["events"][-1], sorted(poll["events"][-1]))
        check("poll params recorded", "params" in poll["events"][-1], sorted(poll["events"][-1]))
        check("poll includes sse actions", {"input.select", "audio.start"} <= set(poll["chain"]["actions"]), poll["chain"]["actions"])

        # Getrennte Clients werden asynchron abgeräumt (Disconnect-Poll <= 0.5 s).
        time.sleep(1.2)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as response:  # noqa: S310
            state = json.loads(response.read().decode())
        check("hub stats published", state["stream"]["published"] >= 4, state["stream"])
        check("hub no leaked subscribers", state["stream"]["subscribers"] == 0, state["stream"])

        print(
            f"sse events stream ok: {len(CHECKS)} checks // pushed={len(events)} "
            f"push_latency={round(push_ms, 1)}ms published={state['stream']['published']}"
        )
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
