#!/usr/bin/env python3
"""Bug-Reports: jeder unbehandelte Fehler landet als lokale JSON-Datei.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 5)

Vorher: Ausnahmen aus dem HTTP-Handler oder aus Engine-Threads landeten als
Traceback auf stderr (oder gingen im Daemon-Modus ganz verloren). Das Audit
meldete ``grep -ri "bug.?report"`` → 0 Treffer.

Jetzt schreibt :func:`write_bug_report` nach ``dist/bug-reports/``:

``bug-<JJJJMMTT-HHMMSS>-<sha8>.json``
    ``id``, ``created_at``, ``user_message`` (verständlicher deutscher Satz
    ohne Stack), ``exception`` (Typ, Meldung, Traceback), ``context``,
    ``environment`` (Python, Plattform, App-Version, Git-Revision),
    ``redacted`` (welche Felder entschärft wurden).

Regeln: **kein** Netzwerk (die Datei bleibt lokal, nichts wird hochgeladen),
**keine** Geheimnisse (Werte zu Schlüsseln wie ``token``, ``api_key``,
``password``, ``secret`` werden zu ``[REDACTED]`` ersetzt und in ``redacted``
gezählt), und die Report-Erzeugung wirft selbst nie – ein Fehler beim Schreiben
wird als Rückgabewert gemeldet, damit der eigentliche Fehler nicht verschluckt
wird.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "dist" / "bug-reports"

#: Schlüssel, deren Werte niemals in einen Report dürfen.
SENSITIVE_KEYS = {
    "token", "tokens", "access_token", "refresh_token", "gh_token", "api_key", "apikey",
    "secret", "client_secret", "password", "passwd", "credential", "credentials",
    "private_key", "keystore", "keystore_password", "session_cookie", "authorization",
}
SENSITIVE_MARKERS = ("token", "api_key", "apikey", "secret", "password", "passwd", "credential", "private_key")

USER_MESSAGES: tuple[tuple[str, str], ...] = (
    ("TimeoutError", "Eine lokale Verbindung hat zu lange nicht geantwortet. Der Vorgang wurde abgebrochen, die App läuft weiter."),
    ("ConnectionRefusedError", "Ein lokaler Dienst nimmt keine Verbindungen an. Bitte den Daemon neu starten."),
    ("ConnectionError", "Ein lokaler Dienst war nicht erreichbar. Bitte den Daemon neu starten (Neustart im Daemon-Panel)."),
    ("FileNotFoundError", "Eine erwartete Datei fehlt (z. B. ein Avatar oder eine Session). Der Vorgang wurde abgebrochen."),
    ("PermissionError", "Der Zugriff auf ein Gerät oder eine Datei wurde verweigert (Mikrofon-/USB-Berechtigung prüfen)."),
    ("MemoryError", "Zu wenig Arbeitsspeicher. Bitte die Session exportieren und die App neu starten."),
    ("json", "Eine Anfrage oder eine gespeicherte Datei war kein gültiges JSON."),
    ("KeyError", "Ein erwarteter Zustand fehlte. Der Vorgang wurde abgebrochen, die App läuft weiter."),
)
FALLBACK_MESSAGE = "Ein unerwarteter Fehler wurde abgebrochen und protokolliert. Die App läuft weiter; die Details stehen im Bug-Report."

__all__ = [
    "DEFAULT_DIR",
    "SENSITIVE_KEYS",
    "install_excepthook",
    "latest_report",
    "list_reports",
    "redact",
    "user_message",
    "write_bug_report",
]


def _git_revision(root: Path) -> str:
    try:
        out = subprocess.run(  # noqa: S603 - lokale git-Abfrage, keine Netzwerkaktion
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        return out.stdout.strip()[:12] if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def redact(value: Any, *, path: str = "", hits: list[str] | None = None) -> Any:
    """Ersetzt Werte sensibler Schlüssel durch ``[REDACTED]`` (rekursiv)."""
    found = hits if hits is not None else []
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in SENSITIVE_KEYS or any(marker in key_lower for marker in SENSITIVE_MARKERS):
                out[key] = "[REDACTED]"
                found.append(f"{path}{key}")
                continue
            out[key] = redact(item, path=f"{path}{key}.", hits=found)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item, path=f"{path}[{index}].", hits=found) for index, item in enumerate(value)]
    return value


def user_message(exc: BaseException | None = None, *, message: str = "") -> str:
    """Verständlicher deutscher Satz für die UI – ohne Stack, ohne Interna."""
    if exc is None:
        return message or FALLBACK_MESSAGE
    names = " ".join(cls.__name__ for cls in type(exc).__mro__)
    for needle, text in USER_MESSAGES:
        if needle in names:
            return text
    return FALLBACK_MESSAGE


def _environment() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
        "app_version": os.environ.get("KAOSS_APP_VERSION", ""),
        "git": _git_revision(root),
        "thread": threading.current_thread().name,
    }


def write_bug_report(
    exc: BaseException | None = None,
    *,
    context: dict[str, Any] | None = None,
    message: str = "",
    report_dir: Path | str | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Schreibt einen Bug-Report und liefert seine Metadaten (wirft nie)."""
    target_dir = Path(report_dir or DEFAULT_DIR)
    now = time.time()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc is not None else ""
    raw_context = dict(context or {})
    redacted_hits: list[str] = []
    safe_context = redact(raw_context, hits=redacted_hits)
    digest_source = f"{stamp}|{type(exc).__name__ if exc else 'message'}|{message}|{tb}|{now}"
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:8]
    report_id = f"bug-{stamp}-{digest}"
    payload = {
        "id": report_id,
        "created_at": round(now, 3),
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
        "user_message": user_message(exc, message=message),
        "summary": message or (f"{type(exc).__name__}: {exc}" if exc is not None else "unbekannter Fehler"),
        "exception": {
            "type": type(exc).__name__ if exc is not None else "",
            "message": str(exc) if exc is not None else "",
            "traceback": tb[-8000:],
        } if exc is not None or tb else None,
        "context": safe_context,
        "redacted": sorted(set(redacted_hits)),
        "environment": _environment(),
        "uploaded": False,
        "note": "Lokale Datei, kein Upload (Zero-Cloud). Löschen jederzeit möglich.",
    }
    result: dict[str, Any] = {
        "ok": False,
        "id": report_id,
        "user_message": payload["user_message"],
        "path": str(target_dir / f"{report_id}.json"),
        "redacted": payload["redacted"],
    }
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / f"{report_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        result["ok"] = True
    except OSError as write_error:
        result["error"] = f"{type(write_error).__name__}: {write_error}"
    if log is not None:
        log(f"[bug-report] {result['id']} ok={result['ok']} // {payload['user_message']}")
    return result


def list_reports(report_dir: Path | str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Neueste Reports (Metadaten, ohne Tracebacks) – für ``/api/bug-reports``."""
    target_dir = Path(report_dir or DEFAULT_DIR)
    if not target_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for candidate in sorted(target_dir.glob("bug-*.json"), reverse=True)[: max(1, int(limit))]:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            rows.append({"id": candidate.stem, "path": str(candidate), "unreadable": True})
            continue
        rows.append({
            "id": data.get("id", candidate.stem),
            "path": str(candidate),
            "created_at": data.get("created_at"),
            "summary": data.get("summary", ""),
            "user_message": data.get("user_message", ""),
            "bytes": candidate.stat().st_size,
        })
    return rows


def latest_report(report_dir: Path | str | None = None) -> dict[str, Any] | None:
    rows = list_reports(report_dir, limit=1)
    return rows[0] if rows else None


def install_excepthook(
    *,
    context: dict[str, Any] | None = None,
    report_dir: Path | str | None = None,
    log: Callable[[str], None] | None = None,
    keep: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fängt unbehandelte Ausnahmen (MainThread **und** Threads) ab.

    Liefert die zuvor installierten Hooks, damit Tests sie wiederherstellen
    können. Der ursprüngliche Hook wird zusätzlich aufgerufen, damit die
    gewohnte stderr-Ausgabe erhalten bleibt.
    """
    previous_sys = sys.excepthook
    previous_threading = getattr(threading, "excepthook", None)

    def hook(args: Any) -> None:
        exc = getattr(args, "exc_value", None)
        info = {
            "where": "sys.excepthook",
            **(context or {}),
        }
        thread = getattr(args, "thread", None)
        if thread is not None:
            info["thread"] = getattr(thread, "name", "")
        write_bug_report(exc, context=info, report_dir=report_dir, log=log)
        previous = keep if keep is not None else previous_sys
        if callable(previous):
            try:
                previous(args.exc_type, args.exc_value, args.exc_traceback)
            except Exception:  # noqa: BLE001 - Hook darf nichts verschlucken
                pass

    def thread_hook(args: Any) -> None:
        exc = getattr(args, "exc_value", None)
        info = {
            "where": "threading.excepthook",
            "thread": getattr(getattr(args, "thread", None), "name", ""),
            **(context or {}),
        }
        write_bug_report(exc, context=info, report_dir=report_dir, log=log)
        if callable(previous_threading):
            try:
                previous_threading(args)
            except Exception:  # noqa: BLE001
                pass

    sys.excepthook = hook
    threading.excepthook = thread_hook
    return {"sys_excepthook": previous_sys, "threading_excepthook": previous_threading}


def uninstall_excepthook(previous: dict[str, Any]) -> None:
    """Setzt die von :func:`install_excepthook` gemerkten Hooks zurück."""
    if previous.get("sys_excepthook") is not None:
        sys.excepthook = previous["sys_excepthook"]
    if previous.get("threading_excepthook") is not None:
        threading.excepthook = previous["threading_excepthook"]
