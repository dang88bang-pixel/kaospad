#!/usr/bin/env python3
"""Error-resistance + stress: malformed payloads, origin guard, concurrent DSP, chain integrity."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[str] = []


def check(label: str, cond: bool, detail: object = "") -> None:
    assert cond, f"FAIL {label}: {detail}"
    CHECKS.append(label)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class App:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"

    def raw(self, method: str, path: str, data: bytes | None, headers: dict | None = None, timeout: float = 8.0):
        req = urllib.request.Request(self.base + path, data=data, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"raw": raw}

    def post(self, path: str, payload: dict, headers: dict | None = None):
        return self.raw("POST", path, json.dumps(payload).encode(), {"Content-Type": "application/json", **(headers or {})})

    def get(self, path: str):
        return self.raw("GET", path, None)

    def act(self, action: str, **params):
        code, body = self.post("/api/action", {"action": action, **params})
        return code, body


def wait(app: App, proc: subprocess.Popen) -> None:
    for _ in range(80):
        if proc.poll() is not None:
            raise AssertionError("app died")
        try:
            code, body = app.get("/health")
            if code == 200 and body.get("ok"):
                return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("not ready")


def prime(app: App) -> None:
    app.act("chain.reset")
    app.act("input.select", input="usb_c_audio")
    app.act("permission.check")
    app.act("permission.grant", key="record_audio", granted=True)
    app.act("audio.start", sample_rate_hz=96000, frames_per_buffer=128)
    app.act("mic.arm", device_id="stress")


def main() -> int:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py"), "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    app = App(port)
    try:
        wait(app, proc)

        code, body = app.post("/api/action", {"action": "not.real"})
        check("unknown action 400", code == 400 and body.get("ok") is False)

        code, body = app.post("/api/action", {"action": "boot"}, {"Origin": "http://evil.example"})
        check("evil origin 403", code == 403)

        code, body = app.raw("POST", "/api/action", b"{not-json", {"Content-Type": "application/json"})
        check("malformed json not 500", code in {200, 400})

        code, body = app.act("dsp.process", signal="mouth_bass")
        check("dsp blocked before arm", body.get("status") == "BLOCKED")

        prime(app)

        huge = [0.2] * 50_000
        code, body = app.act("dsp.process", pcm=huge, frames=128)
        check("huge pcm accepted truncated", code == 200 and body.get("status") == "OK")
        check("huge pcm limiter", body["detail"]["report"]["output_peak_dbfs"] <= -3.2 + 1e-6)

        code, body = app.act("input.select", input="")
        check("empty input error", body.get("status") == "ERROR")

        code, body = app.act("preset.apply", preset=None)
        check("null preset error", body.get("status") == "ERROR")

        results: list[tuple[int, dict]] = []
        errors: list[BaseException] = []

        def worker(n: int) -> None:
            last: BaseException | None = None
            for _attempt in range(6):
                try:
                    results.append(app.act("dsp.process", signal=["mouth_bass", "snare", "hat"][n % 3], frames=128))
                    return
                except BaseException as exc:  # noqa: BLE001
                    last = exc
                    time.sleep(0.08)
            if last is not None:
                errors.append(last)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        check("no worker exceptions", errors == [], errors)
        check("8 concurrent dsp", len(results) == 8, len(results))
        check("concurrent all 200", all(code == 200 for code, _ in results), results[:2])
        check("concurrent none crash", all(body.get("status") in {"OK", "BLOCKED", "ERROR"} for _, body in results))

        for _ in range(24):
            code, body = app.act("dsp.process", signal="mouth_bass", frames=128)
            check("soak limiter", body["detail"]["report"]["output_peak_dbfs"] <= -3.2 + 1e-6)

        code, run = app.post("/api/chain/run", {"strict": True})
        # chain already progressed; reset then run
        app.act("chain.reset")
        code, run = app.post("/api/chain/run", {"strict": True})
        check("post-stress full chain", code == 200 and run.get("ok") is True, run.get("chain_run", {}).get("blocked"))
        check("post-stress 23 steps", run["chain_run"]["steps"] == 23)
        check("post-stress no blocked", run["chain_run"]["blocked"] == [])
        peak = run["chain_run"]["final_state"]["dsp"]["max_peak_dbfs"]
        check("post-stress limiter", peak <= -3.2 + 1e-6, peak)

        print(f"stress/error-resilience: {len(CHECKS)} checks")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
