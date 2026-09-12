#!/usr/bin/env python3
"""Echte Audio-Capture-Blöcke (Mic / USB-UAC2 / BLE) in ``dsp.process``.

Beweist vier Dinge:

1. Ein *externer* Capture-Client (eigener Prozess) kann PCM über die Loopback-Pipe
   einschieben, und die Session-Engine füttert damit ``dsp.process`` – die
   Provenienz steht im Event (``ble_lc3_ipc`` / ``usb_uac2_ipc``, ``real=True``).
2. Capture-Blöcke sind keine Fixtures: zwei aufeinanderfolgende Blöcke
   unterscheiden sich, und der DSP-Checksum unterscheidet sich vom Fixture-Lauf.
3. Ohne Hardware/Client lügt das System nicht: ``real_capture`` bleibt ``false``,
   der Fallback-Block ist ausdrücklich als Fixture gekennzeichnet.
4. Datei-Capture (WAV) streamt blockweise und bleibt als ``real=false`` markiert,
   der Limiter-Vertrag (-3.2 dBFS) gilt für alle Wege.
"""
from __future__ import annotations

import json
import math
import socket
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))
sys.path.insert(0, str(ROOT / "engines" / "neurallift_360"))
sys.path.insert(0, str(ROOT / "engines" / "mopac_dance_learner"))

from audio_capture import (  # noqa: E402
    SOCKET_DIR,
    CaptureRouter,
    encode_ipc_control,
    encode_ipc_frame,
)
from dsp_chain import LIMITER_THRESHOLD_DBFS, test_signal  # noqa: E402
from session_engine import build_engine  # noqa: E402

CHECKS: list[str] = []

PRODUCER = r'''
import math, socket, sys, time
sys.path.insert(0, "engines")
from audio_capture import encode_ipc_control, encode_ipc_frame

path, blocks, frames, rate = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
for _ in range(400):
    try:
        sock.connect(path)
        break
    except OSError:
        time.sleep(0.025)
else:
    raise SystemExit("capture pipe nicht erreichbar")
sock.send(encode_ipc_control({"client": "ble-headset-sim", "codec": "lc3plus", "device": "ble://client/test"}))
for index in range(blocks):
    # Zeitvariante, nicht-deterministische Quelle: simuliert den laufenden
    # Mikrofonstrom eines echten Clients (hier prozess-lokal erzeugt).
    drift = math.sin(time.perf_counter() * 2.7 + index)
    pcm = [
        0.42 * math.sin(2 * math.pi * (180.0 + 55.0 * drift) * (i / rate))
        + 0.03 * math.sin(2 * math.pi * 1700.0 * (i / rate) + index)
        for i in range(frames)
    ]
    sock.send(encode_ipc_frame(pcm, rate))
    time.sleep((frames / rate) * 0.2)
print("produced", blocks)
'''


def check(label: str, condition: bool, detail: object = "") -> None:
    assert condition, f"FAIL {label}: {detail}"
    CHECKS.append(label)


def start_chain(engine, route: str) -> None:
    engine.dispatch("chain.reset")
    engine.dispatch("input.select", {"input": route})
    engine.dispatch("permission.check")
    engine.dispatch("permission.grant", {"key": "record_audio", "granted": True})
    engine.dispatch("audio.start", {"sample_rate_hz": 48_000, "frames_per_buffer": 128, "capture": "none"})
    engine.dispatch("mic.arm", {"device_id": "capture-test"})


def write_capture_wav(path: Path, frames: int = 4096, rate: int = 48_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        samples = [int(12_000 * math.sin(2 * math.pi * 220.0 * (i / rate))) for i in range(frames)]
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def main() -> int:  # noqa: C901 - linearer Capture-Test
    engine = build_engine(restore=False)
    probe = engine.capture_router.probe()
    check("probe zero-cloud", probe["zero_cloud"] is True and probe["offline"] is True)
    check("probe routes", set(probe["routes"]) == {"internal_mic", "usb_c_audio", "bluetooth_client"}, probe["routes"])
    alsa = probe["backends"]["alsa"]
    if not alsa["available"]:
        check("alsa probe honest", alsa["reason"] != "", alsa)

    # ------------------------------------------------------------------ #
    # 1. BLE-Client schiebt echte Blöcke in die Loopback-Pipe
    # ------------------------------------------------------------------ #
    start_chain(engine, "bluetooth_client")
    info = engine.open_capture(mode="ipc_ble", sample_rate_hz=48_000, frames_per_buffer=128)
    check("ble pipe opened", info["opened"] is True and info["backend"] == "ipc_ble", info)
    socket_path = Path(info["socket"])
    check("ble pipe is unix socket", socket_path.is_socket() or socket_path.exists(), socket_path)
    check("ble pipe not yet live", engine.capture["real_capture"] is False, engine.capture)

    producer = subprocess.Popen(
        [sys.executable, "-c", PRODUCER, str(socket_path), "12", "128", "48000"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        blocks = []
        deadline = time.time() + 12
        while len(blocks) < 3 and time.time() < deadline:
            block = engine.capture_router.pull(128, timeout_s=1.0)
            if block is not None:
                blocks.append(block)
        check("ble blocks captured", len(blocks) >= 3, f"got {len(blocks)}")
        check("ble blocks real", all(block.real for block in blocks), blocks[0].provenance())
        check("ble block source", blocks[0].source == "ble_lc3_ipc", blocks[0].provenance())
        check("ble block frames", all(block.frames == 128 for block in blocks), [b.frames for b in blocks])
        check("ble client meta", blocks[0].device in {"ble://client/test", "ble-headset-sim"}, blocks[0].device)
        check("ble blocks differ", blocks[0].pcm != blocks[1].pcm, "identische Blöcke = Fixture-Verdacht")
        check("ble status live", engine.capture_router.status()["real_capture"] is True, engine.capture_router.status())
        check("ble frames counted", engine.capture_router.status()["frames"] >= 384, engine.capture_router.status())

        # ------------------------------------------------------------------ #
        # 2. dsp.process ohne `signal` rechnet die echten Blöcke
        # ------------------------------------------------------------------ #
        live = engine.dispatch("dsp.process", {"frames": 128, "sample_rate_hz": 48_000})
        check("dsp live ok", live["ok"] is True, live.get("detail"))
        check("dsp live source", live["detail"]["source"] == "ble_lc3_ipc", live["detail"]["capture"])
        check("dsp live real", live["detail"]["real_capture"] is True, live["detail"])
        check("dsp live frames", live["detail"]["report"]["frames"] == 128, live["detail"]["report"])
        check(
            "dsp live limiter",
            float(live["detail"]["report"]["output_peak_dbfs"]) <= LIMITER_THRESHOLD_DBFS + 1e-6,
            live["detail"]["report"]["output_peak_dbfs"],
        )
        fixture = engine.dispatch("dsp.process", {"signal": "mouth_bass", "frames": 128, "sample_rate_hz": 48_000})
        check("dsp fixture still deterministic", fixture["detail"]["source"] == "fixture", fixture["detail"]["capture"])
        check(
            "dsp live != fixture checksum",
            live["detail"]["report"]["checksum"] != fixture["detail"]["report"]["checksum"],
            (live["detail"]["report"]["checksum"], fixture["detail"]["report"]["checksum"]),
        )
        check(
            "dsp live != fixture signal",
            live["detail"]["report"]["input_peak_dbfs"] != fixture["detail"]["report"]["input_peak_dbfs"],
            live["detail"]["report"]["input_peak_dbfs"],
        )
        # Fixture bleibt reproduzierbar (CI-Vertrag)
        again = engine.dispatch("dsp.process", {"signal": "mouth_bass", "frames": 128, "sample_rate_hz": 48_000})
        check(
            "fixture deterministic",
            again["detail"]["report"]["checksum"] == fixture["detail"]["report"]["checksum"],
            (again["detail"]["report"]["checksum"], fixture["detail"]["report"]["checksum"]),
        )
        check("capture stats", engine.capture_stats["real_blocks"] >= 1, engine.capture_stats)

        # source=capture erzwingt echte Blöcke
        forced = engine.dispatch("dsp.process", {"frames": 128, "sample_rate_hz": 48_000, "source": "capture"})
        check("forced capture ok", forced["ok"] is True and forced["detail"]["real_capture"] is True, forced["detail"])
    finally:
        producer.wait(timeout=15)
        engine.capture_router.close()

    # ------------------------------------------------------------------ #
    # 3. USB-UAC2-Route über dieselbe Pipe (Android UsbUac2Client-Pfad)
    # ------------------------------------------------------------------ #
    start_chain(engine, "usb_c_audio")
    info = engine.open_capture(mode="ipc_uac2", sample_rate_hz=48_000, frames_per_buffer=128)
    check("uac2 pipe opened", info["opened"] is True, info)
    producer = subprocess.Popen(
        [sys.executable, "-c", PRODUCER, str(Path(info["socket"])), "6", "128", "48000"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 12
        block = None
        while block is None and time.time() < deadline:
            block = engine.capture_router.pull(128, timeout_s=1.0)
        check("uac2 block captured", block is not None and block.real, block)
        check("uac2 source label", block.source == "usb_uac2_ipc", block.provenance())
        result = engine.dispatch("dsp.process", {"frames": 128, "sample_rate_hz": 48_000})
        check("uac2 dsp source", result["detail"]["source"] == "usb_uac2_ipc", result["detail"]["capture"])
    finally:
        producer.wait(timeout=15)
        engine.capture_router.close()

    # ------------------------------------------------------------------ #
    # 4. Ohne Client/ Hardware: ehrlicher Fixture-Fallback
    # ------------------------------------------------------------------ #
    start_chain(engine, "internal_mic")
    engine.open_capture(mode="ipc_mic", sample_rate_hz=48_000, frames_per_buffer=128)
    idle = engine.dispatch("dsp.process", {"frames": 128, "sample_rate_hz": 48_000})
    check("idle fallback fixture", idle["detail"]["source"] == "fixture", idle["detail"]["capture"])
    check("idle fallback marked", idle["detail"]["capture"]["real_capture"] is False, idle["detail"]["capture"])
    check("idle fallback note", "kein" in idle["detail"]["capture"]["note"] or "Capture" in idle["detail"]["capture"]["note"], idle["detail"]["capture"])
    check("idle fixture equals test_signal", idle["detail"]["report"]["input_peak_dbfs"] == round(
        __import__("dsp_chain").peak_dbfs(test_signal("mouth_bass", frames=128, sample_rate_hz=48_000)), 3
    ), idle["detail"]["report"]["input_peak_dbfs"])
    engine.capture_router.close()

    # ------------------------------------------------------------------ #
    # 5. Datei-Capture (WAV) streamt blockweise, bleibt als nicht-live markiert
    # ------------------------------------------------------------------ #
    wav_path = write_capture_wav(ROOT / "dist" / "captures" / "capture-test.wav")
    router = CaptureRouter()
    file_info = router.open("internal_mic", 48_000, 128, "file", device=str(wav_path))
    check("file backend opened", file_info["opened"] is True and file_info["backend"] == "file", file_info)
    first = router.pull(128)
    second = router.pull(128)
    check("file blocks stream", first is not None and second is not None and first.pcm != second.pcm)
    check("file block not live", first.real is False, first.provenance())
    check("file block source", first.source == "file", first.provenance())
    router.close()

    # ------------------------------------------------------------------ #
    # 6. Explizites PCM im Request bleibt als Client-PCM gekennzeichnet
    # ------------------------------------------------------------------ #
    start_chain(engine, "internal_mic")
    payload = [0.5 * math.sin(2 * math.pi * 52.0 * (i / 48_000)) for i in range(128)]
    inline = engine.dispatch("dsp.process", {"pcm": payload, "frames": 128, "sample_rate_hz": 48_000})
    check("inline pcm source", inline["detail"]["source"] == "client_pcm", inline["detail"]["capture"])
    check("inline pcm real", inline["detail"]["real_capture"] is True, inline["detail"]["capture"])
    check("inline pcm frames", inline["detail"]["report"]["frames"] == 128, inline["detail"]["report"])

    print(
        "live capture dsp ok: "
        f"{len(CHECKS)} checks // real blocks={engine.capture_stats['real_blocks']} "
        f"fixture blocks={engine.capture_stats['fixture_blocks']} sockets={SOCKET_DIR.name}"
    )
    print(json.dumps({"capture_stats": engine.capture_stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
