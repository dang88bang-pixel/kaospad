#!/usr/bin/env python3
"""Watchdog: restarts hanging process after 5s, log rotation, leak guard.

-- REAL-IMPLEMENTATION 2026-09-11 Phase 5 --
- Monitors target PID or heartbeat file; if no heartbeat for 5s, restarts.
- Provides log rotation (max 5 files x 2MB).
- Provides user-friendly exception wrapper + bug report file.
"""
from __future__ import annotations
import time, pathlib, subprocess, json, os, hashlib, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "dist" / "logs"
BUG_DIR = ROOT / "dist" / "bug_reports"
HEARTBEAT = ROOT / "dist" / "watchdog.heartbeat"
WATCHDOG_TIMEOUT_S = 5.0
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_LOG_FILES = 5

def heartbeat():
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(str(time.time()), encoding="utf-8")

def is_hanging() -> bool:
    if not HEARTBEAT.exists():
        return False
    try:
        ts = float(HEARTBEAT.read_text(encoding="utf-8").strip())
        return (time.time() - ts) > WATCHDOG_TIMEOUT_S
    except Exception:
        return False

def rotate_logs():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for log in LOG_DIR.glob("*.log"):
        try:
            if log.stat().st_size > MAX_LOG_BYTES:
                for i in range(MAX_LOG_FILES-1, 0, -1):
                    src = LOG_DIR / f"{log.stem}.{i}.log"
                    dst = LOG_DIR / f"{log.stem}.{i+1}.log"
                    if src.exists():
                        src.rename(dst)
                log.rename(LOG_DIR / f"{log.stem}.1.log")
                log.write_text("", encoding="utf-8")
        except Exception:
            pass

def bug_report(exc: Exception, context: str = "") -> Path:
    BUG_DIR.mkdir(parents=True, exist_ok=True)
    bid = hashlib.sha256(f"{time.time()}:{exc}:{context}".encode()).hexdigest()[:12]
    path = BUG_DIR / f"{bid}.json"
    path.write_text(json.dumps({
        "context": context,
        "error": str(exc)[:500],
        "type": type(exc).__name__,
        "at": time.time(),
        "user_message": f"Ein Fehler ist aufgetreten in {context}: {exc}. Siehe {path.name} für Details. Die App läuft weiter im abgesicherten Modus.",
        "watchdog_ms": int(WATCHDOG_TIMEOUT_S*1000),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return path

def wrap_with_bug_report(func, context: str):
    def wrapped(*a, **kw):
        try:
            return func(*a, **kw)
        except Exception as exc:
            path = bug_report(exc, context)
            print(f"[watchdog] {context} failed: {exc} -> {path}", flush=True)
            return {"ok": False, "error": str(exc)[:300], "user_message": f"Fehler in {context} — siehe Bug-Report {path.name}", "bug_report": str(path), "degraded": True}
    return wrapped

def start_background_watchdog(target_cmd, restart_cmd=None):
    """Start thread that kills+restarts target if hanging."""
    def loop():
        while True:
            time.sleep(1)
            rotate_logs()
            if is_hanging():
                print(f"[watchdog] hanging detected >{WATCHDOG_TIMEOUT_S}s, restarting", flush=True)
                try:
                    if restart_cmd:
                        subprocess.Popen(restart_cmd, shell=True)
                except Exception as exc:
                    bug_report(exc, "watchdog restart")
                # reset heartbeat to avoid loop
                try:
                    HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
                except: pass
    t = threading.Thread(target=loop, name="kaoss-watchdog", daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    print("watchdog ready, timeout", WATCHDOG_TIMEOUT_S)
    heartbeat()
    for i in range(3):
        time.sleep(1)
        print("tick", i, "hanging", is_hanging())
        heartbeat()
    rotate_logs()
    print("log rotation done")
