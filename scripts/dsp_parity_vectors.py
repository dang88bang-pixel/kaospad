#!/usr/bin/env python3
"""Paritäts-Vektoren + Python-Referenz für den 3-Wege-DSP-Check.

Erzeugt ``dist/parity/vectors.bin`` (dasselbe Binärformat lesen der native
Harness ``tests/dsp_parity_harness.cpp`` und der WASM-Lauf in
``tests/dsp_wasm_parity_test.mjs``) und berechnet mit ``engines/dsp_chain.py``
die Python-Referenz ``dist/parity/python.json``.

Binärformat (little endian)::

    "KVEC" | uint32 version | uint32 cases
    pro Case: uint32 name_len | name | double rate | uint32 frames |
              float32[frames] pcm | float32[8] xy | uint32 s808_frames | double s808_ms
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

from dsp_chain import (  # noqa: E402
    LIMITER_THRESHOLD_DBFS,
    KaossQuadChain,
    block_checksum,
    brickwall_soft_knee_buffer,
    brickwall_soft_knee_sample,
    detect_mouth_transient,
    peak_dbfs,
    synthesize_808,
    test_signal,
)

MAGIC = b"KVEC"
VERSION = 1

# Modul 1 (VINYL) bleibt auf 0/0: Die Python-Spiegel hat dort eine zusätzliche
# Wow/Flutter-Schicht, der C++-Kern nicht. Der Paritäts-Check vergleicht den
# gemeinsamen Kern (Drive/Filter/Ambience + Limiter), nicht die Python-Extras.
XY = (0.38, 0.0, 0.62, 0.5, 0.5, 0.0, 0.38, 0.28)  # x0..x3, y0..y3

CASES = (
    {"name": "mouth_bass_128", "signal": "mouth_bass", "frames": 128, "rate": 96_000.0, "amplitude": 0.6},
    {"name": "hot_mouth_bass_128", "signal": "mouth_bass", "frames": 128, "rate": 96_000.0, "amplitude": 1.0},
    {"name": "snare_128", "signal": "snare", "frames": 128, "rate": 96_000.0, "amplitude": 0.9},
    {"name": "hat_128", "signal": "hat", "frames": 128, "rate": 96_000.0, "amplitude": 0.16},
    {"name": "vocal_256", "signal": "vocal", "frames": 256, "rate": 96_000.0, "amplitude": 0.6},
    {"name": "silence_128", "signal": "silence", "frames": 128, "rate": 96_000.0, "amplitude": 0.6},
    {"name": "mouth_bass_128_48k", "signal": "mouth_bass", "frames": 128, "rate": 48_000.0, "amplitude": 0.6},
)

S808_FRAMES = 1024
S808_MS = 30.0


def build_vectors() -> list[dict[str, object]]:
    vectors = []
    for case in CASES:
        pcm = test_signal(str(case["signal"]), frames=int(case["frames"]), sample_rate_hz=float(case["rate"]))
        vectors.append(
            {
                "name": case["name"],
                "rate": float(case["rate"]),
                "frames": int(case["frames"]),
                "pcm": [float(value) for value in pcm],
                "xy": list(XY),
                "s808_frames": S808_FRAMES,
                "s808_ms": S808_MS,
            }
        )
    return vectors


def write_vectors(path: Path, vectors: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = bytearray()
    body += MAGIC
    body += struct.pack("<II", VERSION, len(vectors))
    for vector in vectors:
        name = str(vector["name"]).encode("utf-8")
        body += struct.pack("<I", len(name)) + name
        body += struct.pack("<d", float(vector["rate"]))
        body += struct.pack("<I", int(vector["frames"]))
        body += struct.pack(f"<{len(vector['pcm'])}f", *vector["pcm"])
        body += struct.pack("<8f", *vector["xy"])
        body += struct.pack("<I", int(vector["s808_frames"]))
        body += struct.pack("<d", float(vector["s808_ms"]))
    path.write_bytes(bytes(body))
    return path


def read_vectors(path: Path) -> list[dict[str, object]]:
    raw = path.read_bytes()
    if raw[:4] != MAGIC:
        raise ValueError("bad vector magic")
    version, cases = struct.unpack_from("<II", raw, 4)
    if version != VERSION:
        raise ValueError(f"unsupported vector version {version}")
    offset = 12
    vectors = []
    for _ in range(cases):
        (name_len,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        name = raw[offset : offset + name_len].decode("utf-8")
        offset += name_len
        rate = struct.unpack_from("<d", raw, offset)[0]
        offset += 8
        (frames,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        pcm = list(struct.unpack_from(f"<{frames}f", raw, offset))
        offset += frames * 4
        xy = list(struct.unpack_from("<8f", raw, offset))
        offset += 32
        s808_frames = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        s808_ms = struct.unpack_from("<d", raw, offset)[0]
        offset += 8
        vectors.append(
            {
                "name": name,
                "rate": rate,
                "frames": frames,
                "pcm": pcm,
                "xy": xy,
                "s808_frames": s808_frames,
                "s808_ms": s808_ms,
            }
        )
    return vectors


def fnv1a_float32(pcm: list[float]) -> str:
    payload = struct.pack(f"<{len(pcm)}f", *pcm)
    digest = 0xCBF29CE484222325
    for byte in payload:
        digest ^= byte
        digest = (digest * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{digest:016x}"


def python_results(vectors: list[dict[str, object]]) -> dict[str, object]:
    """Referenzlauf über ``engines/dsp_chain.py`` (identisches JSON-Layout)."""
    cases = []
    for vector in vectors:
        pcm = list(vector["pcm"])
        frames = int(vector["frames"])
        rate = float(vector["rate"])
        limited = brickwall_soft_knee_buffer(pcm, LIMITER_THRESHOLD_DBFS)
        transient = detect_mouth_transient(pcm, rate)
        synth = synthesize_808(rate, duration_ms=float(vector["s808_ms"]))[: int(vector["s808_frames"])]
        synth += [0.0] * (int(vector["s808_frames"]) - len(synth))

        chain = KaossQuadChain(sample_rate_hz=rate)
        xy = list(vector["xy"])
        for module in range(4):
            chain.set_xy(module, xy[module], xy[4 + module])
        processed = chain.process(pcm)
        state = chain.state()

        cases.append(
            {
                "name": vector["name"],
                "frames": frames,
                "sample_rate_hz": rate,
                "peak_dbfs": round(peak_dbfs(pcm), 9),
                "limited_peak_dbfs": round(peak_dbfs(limited), 9),
                "sample": round(brickwall_soft_knee_sample(1.0, LIMITER_THRESHOLD_DBFS), 9),
                "checksum": fnv1a_float32(limited),
                "block_checksum_sha256": block_checksum(limited),
                "transient": {
                    "kind_id": int(transient.kind_id),
                    "frequency_hz": float(transient.frequency_hz),
                    "detection_latency_ms": float(transient.detection_latency_ms),
                },
                "limited": [round(value, 9) for value in limited],
                "processed": [round(value, 9) for value in processed],
                "s808": [round(value, 9) for value in synth],
                "state": {
                    "xy": [float(module["x"]) for module in state["modules"]] + [float(module["y"]) for module in state["modules"]],
                    "frozen": [1 if module["frozen"] else 0 for module in state["modules"]],
                    "bpm": float(state["bpm"]),
                },
            }
        )
    return {"impl": "python", "abi": 1, "limiter_dbfs": LIMITER_THRESHOLD_DBFS, "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description="DSP parity vectors + python reference")
    parser.add_argument("--vectors", default=str(ROOT / "dist" / "parity" / "vectors.bin"))
    parser.add_argument("--out", default=str(ROOT / "dist" / "parity" / "python.json"))
    args = parser.parse_args()

    vectors = build_vectors()
    vector_path = write_vectors(Path(args.vectors), vectors)
    # Round-Trip-Check: float32-Quantisierung aside muss dieselbe Case-Liste zurückkommen.
    round_trip = read_vectors(vector_path)
    assert [item["name"] for item in round_trip] == [item["name"] for item in vectors], "vector round-trip drift"
    for written, loaded in zip(vectors, round_trip):
        assert written["frames"] == loaded["frames"] and written["rate"] == loaded["rate"]
        worst = max((abs(float(a) - float(b)) for a, b in zip(written["pcm"], loaded["pcm"])), default=0.0)
        assert worst < 1e-6, f"pcm round-trip drift {worst}"
    payload = python_results(round_trip)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload), encoding="utf-8")
    print(
        f"parity vectors: {vector_path.relative_to(ROOT)} ({vector_path.stat().st_size} B, "
        f"{len(vectors)} cases) // python reference: {out_path.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
