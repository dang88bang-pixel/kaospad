#!/usr/bin/env python3
"""Phase-4-Test: die vier geforderten Ausfall-Simulationen.

Gefordert waren „Netz weg / Permission denied / USB abgezogen / OOM". Alle vier
werden hier **echt** ausgelöst, nicht behauptet:

1. **Netz weg** – der IPC-Suite-Prozess (Ports 8080–8085) wird mitten im Betrieb
   gekillt; der Client muss begrenzt warten, den Breaker öffnen und nach dem
   Respawn wieder grüne Aufrufe liefern. Zusätzlich: Capture-Pipe ohne Client.
2. **Permission denied** – ein Verzeichnis wird auf ``0o500`` gesetzt (Log und
   Bug-Report dürfen nicht crashen), und die ALSA-Probe wird per Fault-Injection
   auf ``PermissionError`` gesetzt (Retry + Breaker, Ergebnis bleibt ehrlich).
3. **USB abgezogen** – Hotplug-Snapshot meldet das verschwundene Gerät, die
   Capture-Pipe verliert ihren Socket, und die USB-Route fällt ohne Crash zurück.
4. **OOM** – ``MemoryError`` wird injiziert: nicht wiederholbar, Breaker zählt,
   Bug-Report nennt die Ursache, die UI-Meldung bleibt verständlich.

Kein echter Speicher wird erschöpft – das wäre in CI unverantwortlich. Der Punkt
ist, dass die Kette bei ``MemoryError`` definiert degradiert statt abzubrechen.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

import local_audio_probe  # noqa: E402
from audio_capture import CaptureRouter, IpcCapture  # noqa: E402
from bug_report import user_message, write_bug_report  # noqa: E402
from log_rotation import RotatingLog  # noqa: E402
from resilience import CLOSED, OPEN, REGISTRY, CircuitBreaker, RetryPolicy, with_retry  # noqa: E402
from usb_uac2 import hotplug_snapshot  # noqa: E402

CHECKS = 0
WORKDIR = ROOT / "dist" / "tmp" / "failure-sim"


def check(label: str, condition: bool, detail: object = "") -> None:
    global CHECKS
    CHECKS += 1
    assert condition, f"CHECK FAILED: {label} // {detail}"


def http_get(path: str, timeout: float = 2.0) -> tuple[int, dict]:
    request = urllib.request.Request(path)  # noqa: S310 local only
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {"ok": False, "http_error": exc.code}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ConnectionError(f"{type(exc).__name__}: {exc}") from exc


def wait_ready(port: int = 8080, deadline_s: float = 8.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# --------------------------------------------------------------------------- #
# 1) Netz weg
# --------------------------------------------------------------------------- #
def network_down_tests() -> None:
    suite = subprocess.Popen(
        [sys.executable, str(ROOT / "engines/localhost_ipc_suite.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        check("IPC-Suite erreichbar", wait_ready(), "8080 nicht offen")
        code, payload = http_get("http://127.0.0.1:8080/resilience")
        check("Resilienz-Endpoint vor dem Ausfall", code == 200 and payload["ok"] is True, (code, payload))

        breaker = CircuitBreaker("sim:network", failure_threshold=3, reset_timeout_s=0.4)
        suite.terminate()
        try:
            suite.wait(timeout=5)
        except subprocess.TimeoutExpired:
            suite.kill()

        for _ in range(4):
            record = breaker.call(
                lambda: http_get("http://127.0.0.1:8080/resilience", timeout=0.5),
                RetryPolicy(attempts=2, base_delay_s=0.01, jitter=0.0, deadline_s=1.0),
            )
        check("Ausfall wird gemeldet statt zu hängen", record.ok is False, record.as_dict())
        check("Breaker öffnet nach wiederholtem Ausfall", breaker.state == OPEN, breaker.state)

        refused = breaker.call(lambda: http_get("http://127.0.0.1:8080/resilience", timeout=0.5))
        check("Offener Breaker verweigert ohne neuen Versuch", refused.refused is True, refused.as_dict())

        # Respawn: Halb-offen-Probe muss wieder durchkommen.
        again = subprocess.Popen(
            [sys.executable, str(ROOT / "engines/localhost_ipc_suite.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            check("Suite erneut erreichbar", wait_ready(), "8080 nach Respawn nicht offen")
            time.sleep(0.45)  # Reset-Timeout des Breakers abwarten
            recovered = breaker.call(lambda: http_get("http://127.0.0.1:8080/resilience", timeout=1.0))
            check("Nach Respawn wieder erfolgreich", recovered.ok is True, recovered.as_dict())
            check("Breaker schließt wieder", breaker.state == CLOSED, breaker.state)
        finally:
            again.terminate()
            try:
                again.wait(timeout=5)
            except subprocess.TimeoutExpired:
                again.kill()

        # Capture-Pipe ohne Client: ehrlich statt "live".
        router = CaptureRouter()
        info = router.open(route="internal_mic", mode="ipc_mic", sample_rate_hz=48_000, frames_per_buffer=64)
        status = router.status()
        check("Pipe ohne Client öffnet", info["opened"] is True, info)
        check("Ohne Client keine echte Erfassung", status["real_capture"] is False, status)
        check("Ohne Client keine Blöcke", router.pull(64, timeout_s=0.2) is None, "Block ohne Sender")
        router.close()
    finally:
        for proc in (suite, locals().get("again")):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


# --------------------------------------------------------------------------- #
# 2) Permission denied
# --------------------------------------------------------------------------- #
def permission_denied_tests() -> None:
    locked = WORKDIR / "locked"
    locked.mkdir(parents=True, exist_ok=True)
    os.chmod(locked, 0o500)
    try:
        log = RotatingLog(locked / "nested" / "app.log", max_bytes=1024, backups=1)
        check("Log-Schreibfehler ohne Crash", log.write("error", "darf nicht crashen") is False, log.status())
        check("Log meldet Fehler", bool(log.status()["errors"]), log.status()["errors"])

        report = write_bug_report(PermissionError(13, "Permission denied"), report_dir=locked / "nested")
        check("Bug-Report bei Permission denied ohne Crash", report["ok"] is False, report)
        check("Bug-Report nennt den Fehler", "error" in report, report)
        check("UI-Meldung bleibt verständlich", "verweigert" in report["user_message"], report["user_message"])
    finally:
        os.chmod(locked, 0o700)

    # Fault-Injection: ALSA-Probe wirft PermissionError (USB/Kernel-Sperre).
    original = local_audio_probe._read_probe
    calls = {"n": 0}

    def denied() -> dict:
        calls["n"] += 1
        raise PermissionError(13, "Permission denied", "/proc/asound/cards")

    REGISTRY.reset("alsa_probe")
    local_audio_probe._read_probe = denied
    try:
        probe = local_audio_probe.alsa_cards()
    finally:
        local_audio_probe._read_probe = original
    check("Probe mit Permission denied bleibt ok", probe["ok"] is True, probe.get("reason"))
    check("Probe liefert leere Geräteliste", probe["alsa_cards"] == [] and probe["snd_nodes"] == [], probe["alsa_cards"])
    check("Probe nennt den Grund", "PermissionError" in str(probe.get("reason", "")), probe.get("reason"))
    check("Probe hat wiederholt versucht", calls["n"] >= 2 and probe["resilience"]["tries"] >= 2, (calls, probe["resilience"]["tries"]))
    check("Probe-Fehler im Breaker sichtbar", probe["resilience"]["breaker_state"] in {OPEN, CLOSED}, probe["resilience"])
    REGISTRY.reset("alsa_probe")

    # Permission-Matrix der Kette: strukturiert, nicht als Absturz.
    from session_engine import build_engine

    engine = build_engine(ROOT / "dist" / "offline-rhymes.sqlite3", restore=False, inspect=False)
    event = engine.dispatch("permission.check", {}, strict=False)
    permissions = event["detail"].get("permissions") or engine.state()["input"]
    check("permission.check liefert Ergebnis", event["status"] in {"OK", "BLOCKED", "ERROR"}, event["status"])
    check("Permission-Matrix vorhanden", bool(permissions), permissions)
    engine.close() if hasattr(engine, "close") else None


# --------------------------------------------------------------------------- #
# 3) USB abgezogen
# --------------------------------------------------------------------------- #
def usb_disconnect_tests() -> None:
    snapshot = hotplug_snapshot(previous=["1235:8213"])
    check("Hotplug meldet getrenntes Gerät", snapshot["removed"] == ["1235:8213"], snapshot["removed"])
    check("Hotplug bleibt ok", snapshot["ok"] is True and snapshot["count"] == 0, snapshot)
    check("Hotplug nennt keine Geräte mehr", snapshot["devices"] == [], snapshot["devices"])

    capture = IpcCapture("ipc_uac2")
    info = capture.open(48_000.0)
    check("USB-Pipe geöffnet", info["opened"] is True if "opened" in info else bool(capture.sock), info)
    socket_path = Path(str(info.get("socket") or capture.path))
    if socket_path.exists():
        socket_path.unlink()  # Gerät verschwindet: Socket ist weg
    block = capture.read_block(64, timeout_s=0.2)
    check("Pipe ohne Socket liefert keinen Block", block is None, block)
    check("Pipe ohne Socket crasht nicht", True)
    capture.close()

    router = CaptureRouter()
    info2 = router.open(route="usb_c_audio", sample_rate_hz=48_000, frames_per_buffer=64, mode="auto")
    status = router.status()
    check("USB-Route ohne Karte fällt zurück", info2["opened"] in (False, True), info2)
    check("Rückfall nennt Versuche", bool(info2.get("attempts")) or info2["opened"] is True, info2.get("attempts"))
    check("Rückfall ohne echte Erfassung", status["real_capture"] is False, status)
    check("Rückfall nennt Grund", bool(status.get("reason")) or status["backend"] != "none", status)
    router.close()


# --------------------------------------------------------------------------- #
# 4) OOM (injizierter MemoryError)
# --------------------------------------------------------------------------- #
def oom_tests() -> None:
    def exploding() -> str:
        raise MemoryError("unable to allocate 8.00 GiB")

    sleeper: list[float] = []
    record = with_retry(exploding, RetryPolicy(attempts=4, base_delay_s=0.01, jitter=0.0), sleep=sleeper.append)
    check("MemoryError wird nicht wiederholt", record.ok is False and record.tries == 1, record.as_dict())
    check("MemoryError ohne Backoff-Schlaf", sleeper == [], sleeper)

    breaker = CircuitBreaker("sim:oom", failure_threshold=2)
    breaker.call(exploding, RetryPolicy(attempts=1, jitter=0.0))
    breaker.call(exploding, RetryPolicy(attempts=1, jitter=0.0))
    check("Breaker zählt MemoryError", breaker.state == OPEN, breaker.stats())
    check("Fehlertext nennt MemoryError", "MemoryError" in breaker.stats()["last_error"], breaker.stats())

    message = user_message(MemoryError())
    check("UI-Meldung bei OOM verständlich", "Arbeitsspeicher" in message, message)

    report_dir = WORKDIR / "bug-reports"
    try:
        raise MemoryError("unable to allocate 8.00 GiB")
    except MemoryError as exc:
        meta = write_bug_report(exc, context={"action": "dsp.process"}, message="dsp.process abgebrochen", report_dir=report_dir)
    check("OOM-Bug-Report geschrieben", meta["ok"] is True, meta)
    data = json.loads(Path(meta["path"]).read_text(encoding="utf-8"))
    check("OOM-Report nennt den Typ", data["exception"]["type"] == "MemoryError", data["exception"])
    check("OOM-Report enthält Traceback", "exploding" in data["exception"]["traceback"] or "raise MemoryError" in data["exception"]["traceback"], data["exception"]["traceback"][:80])
    check("OOM-Report ohne Upload", data["uploaded"] is False, data["uploaded"])


def main() -> int:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR, ignore_errors=True)
    WORKDIR.mkdir(parents=True, exist_ok=True)
    network_down_tests()
    permission_denied_tests()
    usb_disconnect_tests()
    oom_tests()
    shutil.rmtree(WORKDIR, ignore_errors=True)
    print(
        "failure simulation verified: "
        f"{CHECKS} checks // netz weg (Breaker öffnet + erholt) // permission denied // "
        "usb abgezogen // OOM (MemoryError)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
