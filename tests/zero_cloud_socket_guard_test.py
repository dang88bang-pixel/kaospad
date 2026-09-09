#!/usr/bin/env python3
"""Zero-Cloud-Gate: vollständige Aktionskette unter Socket-Monkeypatch.

Der One-App-Server wird *im Testprozess* gestartet, während ``socket`` so
instrumentiert wird, dass jede Verbindung und jede Namensauflösung zu einem
Nicht-Loopback-Ziel protokolliert und blockiert wird. Danach wird die komplette
Aktions- und Interaktionskette ausgeführt.

Beweist: die Kette läuft ausschließlich über 127.0.0.1 – kein DNS, kein Cloud-
Modell, keine Telemetrie (TODO 10.2 "Zero external network enforcement with
socket monkeypatch" und TODO 12 "Bind nur 127.0.0.1 validieren").
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))

import app as one_app  # noqa: E402

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0", ""}
resolved: list[str] = []       # erlaubte Loopback-Ziele
connected: list[str] = []      # tatsächlich verbundene Loopback-Ziele
blocked_attempts: list[str] = []  # abgefangene Nicht-Loopback-Ziele

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_getaddrinfo = socket.getaddrinfo
_original_gethostbyname = socket.gethostbyname


def _is_local(host: object) -> bool:
    name = host if isinstance(host, str) else str(host)
    return name in LOCAL_HOSTS or name.startswith("127.")


def _audit(host: object, kind: str = "resolve") -> None:
    """Protokolliert ein Ziel und verweigert alles außerhalb von Loopback."""
    name = host if isinstance(host, str) else str(host)
    if _is_local(name):
        resolved.append(name)
        if kind == "connect":
            connected.append(name)
        return
    blocked_attempts.append(name)
    raise OSError(f"zero-cloud {kind} blocked: {name}")


def guarded_connect(self, address):  # noqa: ANN001, ANN201
    if isinstance(address, tuple) and address:
        _audit(address[0], "connect")
    return _original_connect(self, address)


def guarded_connect_ex(self, address):  # noqa: ANN001, ANN201
    if isinstance(address, tuple) and address:
        _audit(address[0], "connect_ex")
    return _original_connect_ex(self, address)


def guarded_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001, ANN202
    _audit(host, "dns")
    return _original_getaddrinfo(host, *args, **kwargs)


def guarded_gethostbyname(host):  # noqa: ANN001, ANN202
    _audit(host, "dns")
    return _original_gethostbyname(host)


def install_guard() -> None:
    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    socket.gethostbyname = guarded_gethostbyname  # type: ignore[assignment]


def restore_guard() -> None:
    socket.socket.connect = _original_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _original_connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = _original_getaddrinfo  # type: ignore[assignment]
    socket.gethostbyname = _original_gethostbyname  # type: ignore[method-assign]


def post_json(base: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:  # noqa: S310 local only
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    install_guard()
    # Server-Logs würden das Gate-Protokoll überfluten.
    one_app.OneAppHandler.log_message = lambda self, fmt, *args: None  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", 0), one_app.OneAppHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        run = post_json(base, "/api/chain/run", {"strict": True})
        assert run["ok"] is True, run["chain_run"]["blocked"]

        # Explizite externe Ziele müssen blockiert werden (Negativkontrolle).
        for host, port_number in (("example.com", 443), ("8.8.8.8", 53)):
            try:
                with socket.create_connection((host, port_number), timeout=0.3):
                    raise AssertionError(f"external socket was NOT blocked: {host}")
            except OSError as exc:
                assert "zero-cloud" in str(exc), exc
        assert blocked_attempts == ["example.com", "8.8.8.8"], blocked_attempts

        state = json.loads(urllib.request.urlopen(base + "/api/state", timeout=5.0).read().decode("utf-8"))  # noqa: S310
        export = post_json(base, "/api/session/export", {})
        session = export["detail"]["session"]

        assert state["zero_cloud"] is True and state["offline"] is True
        assert state["chain"]["length"] >= 23, state["chain"]
        assert state["chain"]["blocked"] == 0, state["chain"]
        assert session["created_offline"] is True and session["zero_cloud"] is True
        assert session["chain_length"] >= 23, session["chain_length"]
        assert state["dsp"]["max_peak_dbfs"] <= -3.2 + 1e-6, state["dsp"]

        external = [host for host in resolved if not _is_local(host)]
        assert not external, f"external target reached: {external}"
        assert connected and all(_is_local(host) for host in connected), connected
        assert server.server_address[0] == "127.0.0.1", server.server_address

        print(
            f"zero-cloud socket guard passed: {state['chain']['length']} chain steps, "
            f"{len(connected)} loopback connections, {len(set(resolved))} resolved hosts, "
            f"{len(blocked_attempts)} external attempts blocked"
        )
        return 0
    finally:
        server.shutdown()
        server.server_close()
        restore_guard()


if __name__ == "__main__":
    raise SystemExit(main())
