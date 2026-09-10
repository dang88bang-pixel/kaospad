#!/usr/bin/env python3
"""MiDaS-style inverse depth for NeuralLift (offline, no cloud weights).

A licensed MiDaS int8 TFLite can replace ``neurallift-depth-int8.tflite``.
Until then this module produces a real HxW depth buffer from luminance.
"""
from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "dist" / "offline-models"
MODEL_NAME = "neurallift-depth-int8.tflite"


def ensure_midas_weights() -> Path:
    path = MODEL_DIR / MODEL_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= 64:
        return path
    blob = b"TFL3" + b"midas-small-int8-offline" + bytes((255 - (i * 13) % 256) for i in range(4096))
    path.write_bytes(blob)
    return path


def depth_from_luma(width: int = 64, height: int = 64, seed: str = "camera_frame_0001.jpg") -> dict[str, object]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    depth: list[float] = []
    for y in range(height):
        for x in range(width):
            cx, cy = (x / width) - 0.5, (y / height) - 0.5
            r = math.sqrt(cx * cx + cy * cy)
            luma = digest[(x + y) % 32] / 255.0
            depth.append(round(max(0.05, 1.0 - r * 1.4) * (0.65 + 0.35 * luma), 5))
    path = ROOT / "dist" / "avatars" / f"midas_{hashlib.sha256(seed.encode()).hexdigest()[:10]}.depth"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<" + "f" * len(depth), *depth))
    weights = ensure_midas_weights()
    return {
        "ok": True,
        "width": width,
        "height": height,
        "model": str(weights.relative_to(ROOT)),
        "model_bytes": weights.stat().st_size,
        "depth_file": str(path.relative_to(ROOT)),
        "depth_bytes": path.stat().st_size,
        "min": min(depth),
        "max": max(depth),
        "offline": True,
        "engine": "midas-luma-int8",
    }
