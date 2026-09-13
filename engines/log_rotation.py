#!/usr/bin/env python3
"""Rotierende Log-Dateien: begrenzte Größe, keine Lecks, JSON-Zeilen.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 5)

Vorher: Logs liefen ausschließlich über ``print`` auf stdout. In einem
Dauerlauf (One-App als Service, Android-Foreground-Service) wächst stdout
entweder ins Unendliche oder geht verloren – das Audit hat
``grep -ri "log.?rotat"`` → 0 Treffer gemeldet.

Dieses Modul schreibt jede Zeile als JSON-Objekt in ``<pfad>`` und rotiert bei
``max_bytes``: ``app.log`` → ``app.log.1`` → ``app.log.2`` … Die älteste Datei
wird gelöscht, damit der belegte Platz durch ``max_bytes * (backups + 1)``
nach oben begrenzt bleibt. Schreiben ist thread-sicher; ein Fehler beim
Schreiben wird gezählt, aber nie an die Aufruferin weitergereicht (Logging darf
die Audio-Kette nicht reißen).

Kein Netzwerk: Es wird ausschließlich in das übergebene lokale Verzeichnis
geschrieben.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_BACKUPS = 3

__all__ = ["DEFAULT_BACKUPS", "DEFAULT_MAX_BYTES", "RotatingLog", "rotation_status"]


class RotatingLog:
    """Größenbegrenzte JSON-Zeilen-Log-Datei mit festen Backup-Stufen."""

    def __init__(
        self,
        path: Path | str,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backups: int = DEFAULT_BACKUPS,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes muss > 0 sein")
        if backups < 0:
            raise ValueError("backups darf nicht negativ sein")
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.backups = int(backups)
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._writes = 0
        self._rotations = 0
        self._dropped = 0
        self._errors: list[str] = []
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Ein unmöglicher Pfad darf die Konstruktion nicht reißen: Die
            # Schreibversuche melden den Fehler dann einzeln (Logging ist
            # nie der Grund für einen Absturz).
            self._errors.append(f"mkdir: {type(exc).__name__}: {exc}")

    # -- Schreiben ---------------------------------------------------------
    def write(self, level: str, message: str, **fields: Any) -> bool:
        """Eine JSON-Zeile anhängen; rotiert automatisch bei Größenüberschreitung."""
        payload = {
            "ts": round(float(self._clock()), 3),
            "level": str(level).upper(),
            "message": str(message),
            **{key: value for key, value in fields.items() if value is not None},
        }
        try:
            line = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")) + "\n"
        except (TypeError, ValueError) as exc:
            line = json.dumps({"ts": payload["ts"], "level": payload["level"], "message": str(message),
                               "unserializable": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                # Vorausschauend rotieren (wie ``logging.RotatingFileHandler``):
                # Die aktive Datei enthält damit immer mindestens die letzte
                # Zeile und ist direkt nach einer Rotation nicht leer.
                if self._size(self.path) + len(line.encode("utf-8")) > self.max_bytes:
                    self.rotate()
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                self._writes += 1
            except OSError as exc:
                self._errors.append(f"write: {type(exc).__name__}: {exc}")
                return False
            return True

    def info(self, message: str, **fields: Any) -> bool:
        return self.write("info", message, **fields)

    def warning(self, message: str, **fields: Any) -> bool:
        return self.write("warning", message, **fields)

    def error(self, message: str, **fields: Any) -> bool:
        return self.write("error", message, **fields)

    # -- Rotation ----------------------------------------------------------
    def rotate(self) -> dict[str, Any]:
        """Schiebt ``app.log`` → ``.1`` → ``.2`` … und verwirft die älteste Datei."""
        with self._lock:
            oldest = self.backup_path(self.backups)
            if oldest.exists():
                try:
                    oldest.unlink()
                    self._dropped += 1
                except OSError as exc:
                    self._errors.append(f"drop: {type(exc).__name__}: {exc}")
            for index in range(self.backups, 0, -1):
                source = self.backup_path(index - 1) if index > 1 else self.path
                target = self.backup_path(index)
                if not source.exists():
                    continue
                try:
                    if target.exists():
                        target.unlink()
                    os.replace(source, target)
                except OSError as exc:
                    self._errors.append(f"rotate: {type(exc).__name__}: {exc}")
            # Die aktive Datei soll auch direkt nach einer Rotation existieren,
            # damit /api/logs und tail() nie ins Leere greifen.
            try:
                if not self.path.exists():
                    self.path.touch()
            except OSError as exc:
                self._errors.append(f"touch: {type(exc).__name__}: {exc}")
            self._rotations += 1
            return {
                "rotations": self._rotations,
                "dropped": self._dropped,
                "files": self.files(),
                "bytes": self.total_bytes(),
            }

    def backup_path(self, index: int) -> Path:
        if index <= 0:
            return self.path
        return self.path.with_name(self.path.name + f".{index}")

    # -- Zustand -----------------------------------------------------------
    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def files(self) -> list[dict[str, Any]]:
        rows = []
        for index in range(0, self.backups + 1):
            candidate = self.backup_path(index)
            if candidate.exists():
                rows.append({"name": candidate.name, "bytes": candidate.stat().st_size})
        return rows

    def total_bytes(self) -> int:
        return sum(int(row["bytes"]) for row in self.files())

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "path": str(self.path),
                "max_bytes": self.max_bytes,
                "backups": self.backups,
                "writes": self._writes,
                "rotations": self._rotations,
                "dropped": self._dropped,
                "bytes": self.total_bytes(),
                "files": self.files(),
                "errors": list(self._errors[-5:]),
                "bounded_by_bytes": self.max_bytes * (self.backups + 1),
            }

    def tail(self, lines: int = 20) -> list[dict[str, Any]]:
        """Letzte ``lines`` Einträge der aktiven Datei (für ``/api/logs``)."""
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in raw[-max(1, int(lines)):]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"message": line[:400]})
        return out


def rotation_status(*logs: RotatingLog) -> list[dict[str, Any]]:
    """Kompakte Übersicht mehrerer rotierender Logs."""
    return [log.status() for log in logs]
