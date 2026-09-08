#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def assert_localhost(host: str) -> None:
    ip = socket.gethostbyname(host)
    assert ip.startswith("127."), f"external socket rejected: {host} -> {ip}"


def http_json(path: str) -> dict:
    with urlopen(path, timeout=1.0) as res:  # noqa: S310 local only
        return json.loads(res.read().decode("utf-8"))


def wait_ready() -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            if http_json("http://127.0.0.1:8080/health").get("ok"):
                return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("localhost IPC suite did not become ready")


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "engines/localhost_ipc_suite.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert_localhost("127.0.0.1")
        wait_ready()

        ports = http_json("http://127.0.0.1:8080/native-bridge/ports")
        assert ports["ok"] is True
        assert [item["port"] for item in ports["ports"]] == [8080, 8081, 8082, 8083, 8084, 8085]
        assert all(item["bind"] == "127.0.0.1" for item in ports["ports"])

        mesh = http_json("http://127.0.0.1:8082/mesh/default")
        assert mesh["rig_bones"] == 24 and mesh["lod0_tris"] == 45000

        rhymes = http_json("http://127.0.0.1:8085/rhymes?word=beton")
        assert "SEKTOR" in rhymes["rhymes"]

        devices = http_json("http://127.0.0.1:8080/devices/status?selected=usb_c_audio")
        assert devices["plug_and_play"] is True
        assert devices["selected"] == "usb_c_audio"
        assert {item["id"] for item in devices["devices"]} == {"usb_c_audio", "internal_mic", "bluetooth_client"}
        assert {item["key"] for item in devices["permissions"]} >= {"record_audio", "bluetooth_connect", "usb_host"}

        selected = http_json("http://127.0.0.1:8080/devices/select?input=bluetooth_client")
        assert selected["selected"] == "bluetooth_client"

        with socket.create_connection(("127.0.0.1", 8081), timeout=1.0) as sock:
            sock.sendall(b"PING")
            assert b"PCM_FLOAT32_READY" in sock.recv(128)

        with socket.create_connection(("127.0.0.1", 8083), timeout=1.0) as sock:
            avatar = json.loads(sock.recv(512).decode("utf-8"))
            assert avatar["fps"] == 60 and avatar["avatars"] == 8

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.settimeout(1.0)
            udp.sendto(b"TRANSIENT", ("127.0.0.1", 8084))
            dsp = json.loads(udp.recvfrom(512)[0].decode("utf-8"))
            assert dsp["bpm"] == 92.4 and dsp["kick808"] is True
        finally:
            udp.close()

        print("zero-cloud localhost IPC gate passed for ports 8080-8085")
        return 0
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=2)
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
