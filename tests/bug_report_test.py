#!/usr/bin/env python3
"""Phase-5-Test: Bug-Report-Datei, Redaktion und verständliche Meldung.

Prüft, dass ein unbehandelter Fehler als lokale JSON-Datei landet, dass
Geheimnisse daraus verschwinden und dass die UI-Meldung ohne Stack auskommt.
Geschrieben wird nach ``dist/tmp/bug-report-test`` und danach wieder entfernt.
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

import bug_report as br  # noqa: E402

CHECKS = 0
WORKDIR = ROOT / "dist" / "tmp" / "bug-report-test"


def check(label: str, condition: bool, detail: object = "") -> None:
    global CHECKS
    CHECKS += 1
    assert condition, f"CHECK FAILED: {label} // {detail}"


def raise_and_capture(exc: BaseException) -> dict:
    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001 - Traceback für den Report benötigt
        return br.write_bug_report(
            caught,
            context={
                "action": "dsp.process",
                "port": 8084,
                "token": "geheim-1234",
                "nested": {"api_key": "abc", "route": "internal_mic"},
                "cookies": [{"session_password": "p", "ok": True}],
            },
            message="dsp.process fehlgeschlagen",
            report_dir=WORKDIR,
        )


def main() -> int:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)

    # -- Datei wird geschrieben und ist lesbar ----------------------------
    meta = raise_and_capture(RuntimeError("DSP-Kette hat den Block verloren"))
    check("Report ok gemeldet", meta["ok"] is True, meta)
    path = Path(meta["path"])
    check("Datei liegt in dist/bug-reports (hier: Testverzeichnis)", path.is_file(), meta["path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    check("ID stimmt mit Dateiname überein", data["id"] == path.stem, (data["id"], path.stem))
    check("ID-Schema bug-<stempel>-<hash>", path.stem.startswith("bug-") and len(path.stem.split("-")[-1]) == 8, path.stem)
    check("Exception-Typ erfasst", data["exception"]["type"] == "RuntimeError", data["exception"]["type"])
    check("Traceback enthalten", "raise_and_capture" in data["exception"]["traceback"], data["exception"]["traceback"][:120])
    check("Kontext erfasst", data["context"]["action"] == "dsp.process" and data["context"]["port"] == 8084, data["context"])
    check("Umgebung erfasst", {"python", "platform", "thread"} <= set(data["environment"]), data["environment"])
    check("Kein Upload (Zero-Cloud)", data["uploaded"] is False and "kein Upload" in data["note"], data["note"])

    # -- Geheimnisse werden redigiert -------------------------------------
    check("Token redigiert", data["context"]["token"] == "[REDACTED]", data["context"]["token"])
    check("Verschachtelter API-Key redigiert", data["context"]["nested"]["api_key"] == "[REDACTED]", data["context"]["nested"])
    check("Unkritischer Wert bleibt", data["context"]["nested"]["route"] == "internal_mic", data["context"]["nested"])
    check("Listeneintrag redigiert", data["context"]["cookies"][0]["session_password"] == "[REDACTED]", data["context"]["cookies"])
    check("Redigierte Felder ausgewiesen", len(data["redacted"]) >= 3, data["redacted"])
    check("Kein Geheimnis im Rohtext", "geheim-1234" not in path.read_text(encoding="utf-8"), "Klartext gefunden")

    # -- Verständliche Meldung --------------------------------------------
    check("User-Meldung ohne Stack", "Traceback" not in data["user_message"] and data["user_message"], data["user_message"])
    check("User-Meldung deutsch", any(word in data["user_message"] for word in ("Fehler", "Verbindung", "Datei", "Zugriff")), data["user_message"])
    check("Timeout verständlich", "zu lange nicht geantwortet" in br.user_message(TimeoutError()), br.user_message(TimeoutError()))
    check("PermissionError verständlich", "verweigert" in br.user_message(PermissionError()), br.user_message(PermissionError()))
    check("Refused spezifischer als ConnectionError", "nimmt keine Verbindungen" in br.user_message(ConnectionRefusedError()), br.user_message(ConnectionRefusedError()))
    check("Unbekannter Fehler mit Fallback", br.user_message(ValueError("x")) == br.FALLBACK_MESSAGE, br.user_message(ValueError("x")))

    # -- Eindeutigkeit und Auflistung -------------------------------------
    second = raise_and_capture(ValueError("zweiter Fehler"))
    check("Zweite ID ist eindeutig", second["id"] != meta["id"], (second["id"], meta["id"]))
    rows = br.list_reports(WORKDIR)
    check("list_reports findet beide", len(rows) == 2, rows)
    check("list_reports ohne Traceback", all("traceback" not in str(row).lower() for row in rows), rows)
    latest = br.latest_report(WORKDIR)
    check("latest_report liefert den jüngsten", latest["id"] in {meta["id"], second["id"]}, latest)
    check("latest_report in leerem Verzeichnis None", br.latest_report(WORKDIR / "leer") is None)

    # -- Ohne Exception (reine Meldung) -----------------------------------
    plain = br.write_bug_report(None, message="Benutzer hat abgebrochen", report_dir=WORKDIR)
    plain_data = json.loads(Path(plain["path"]).read_text(encoding="utf-8"))
    check("Meldung ohne Exception möglich", plain["ok"] is True and plain_data["exception"] is None, plain_data["summary"])
    check("Meldung als user_message übernommen", plain_data["user_message"] == "Benutzer hat abgebrochen", plain_data["user_message"])

    # -- Unerreichbares Verzeichnis crasht nicht --------------------------
    blocker = WORKDIR / "blocker.txt"
    blocker.write_text("ich bin eine Datei, kein Verzeichnis", encoding="utf-8")
    impossible = br.write_bug_report(RuntimeError("x"), report_dir=blocker / "tiefer")
    check("Schreibfehler wird gemeldet statt geworfen", impossible["ok"] is False and "error" in impossible, impossible)

    # -- excepthook für MainThread und Threads ----------------------------
    lines: list[str] = []
    previous = br.install_excepthook(context={"app": "one-app"}, report_dir=WORKDIR, log=lines.append, keep=lambda *a: None)
    try:
        try:
            raise KeyError("chain.step fehlt")
        except KeyError as exc:
            class Args:
                exc_type = type(exc)
                exc_value = exc
                exc_traceback = exc.__traceback__
                thread = threading.current_thread()

            sys.excepthook(Args())  # type: ignore[arg-type]

        hook_reports = [row for row in br.list_reports(WORKDIR) if "chain.step fehlt" in str(row.get("summary", ""))]
        check("sys.excepthook schreibt Report", len(hook_reports) == 1, hook_reports)
        hook_data = json.loads(Path(hook_reports[0]["path"]).read_text(encoding="utf-8"))
        check("Herkunft im Kontext", hook_data["context"]["where"] == "sys.excepthook", hook_data["context"])
        check("App-Kontext übernommen", hook_data["context"]["app"] == "one-app", hook_data["context"])
        check("Log-Zeile geschrieben", any("bug-report" in line for line in lines), lines)

        thread_reports: list[dict] = []

        def crashing_thread() -> None:
            try:
                raise TimeoutError("engine antwortet nicht")
            except TimeoutError as thread_exc:
                class ThreadArgs:
                    exc_type = type(thread_exc)
                    exc_value = thread_exc
                    exc_traceback = thread_exc.__traceback__
                    thread = threading.current_thread()

                threading.excepthook(ThreadArgs())  # type: ignore[arg-type]
                thread_reports.extend(
                    row for row in br.list_reports(WORKDIR) if "engine antwortet nicht" in str(row.get("summary", ""))
                )

        worker = threading.Thread(target=crashing_thread, name="kaoss-worker")
        worker.start()
        worker.join()
        check("threading.excepthook schreibt Report", len(thread_reports) == 1, thread_reports)
        thread_data = json.loads(Path(thread_reports[0]["path"]).read_text(encoding="utf-8"))
        check("Thread-Name erfasst", thread_data["context"]["thread"] == "kaoss-worker", thread_data["context"])
        check("Thread-Herkunft markiert", thread_data["context"]["where"] == "threading.excepthook", thread_data["context"])
    finally:
        br.uninstall_excepthook(previous)
    check("Hooks wiederhergestellt", sys.excepthook is previous["sys_excepthook"], sys.excepthook)

    # -- Quellen-Hygiene --------------------------------------------------
    source = (ROOT / "engines" / "bug_report.py").read_text(encoding="utf-8")
    check("REAL-IMPLEMENTATION-Marker gesetzt", "REAL-IMPLEMENTATION 2026-09-12" in source, "Marker fehlt")
    for forbidden in ("urllib", "requests", "http.client", "socket"):
        check(f"bug_report.py ohne {forbidden}", forbidden not in source, forbidden)

    shutil.rmtree(WORKDIR, ignore_errors=True)
    print(
        "bug report verified: "
        f"{CHECKS} checks // JSON in dist/bug-reports // Secrets redigiert // "
        "verständliche Meldung // sys+thread excepthook"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
