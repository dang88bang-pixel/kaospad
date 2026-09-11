#!/usr/bin/env python3
"""33-point pose stream derived from audio energy (offline MoPac stand-in).

MediaPipe is not vendored here. This module emits the same 33-landmark layout
so avatar.mode and tests can consume a real skeletal buffer without cloud ML.
"""
from __future__ import annotations

import math

LANDMARKS = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner", "right_eye",
    "right_eye_outer", "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "left_pinky", "right_pinky", "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
    "left_heel", "right_heel", "left_foot_index", "right_foot_index",
]


def skeleton_frame(t_ms: float, energy: float = 0.4, mode: str = "CYPHER_CIRCLE") -> dict[str, object]:
    phase = (t_ms / 1000.0) * (2.0 * math.pi) * (1.2 if mode == "PARTY_8" else 0.6)
    bounce = 0.04 * energy * math.sin(phase)
    bones = []
    for i, name in enumerate(LANDMARKS):
        side = -1.0 if "left" in name else 1.0 if "right" in name else 0.0
        y = 0.9 - (i / 32.0) * 1.6 + bounce
        x = side * (0.12 + 0.08 * math.sin(phase + i * 0.1))
        z = 0.02 * math.cos(phase + i * 0.05)
        bones.append({"index": i, "name": name, "x": round(x, 5), "y": round(y, 5), "z": round(z, 5)})
    return {
        "fps": 60,
        "bones": 33,
        "landmarks": bones,
        "energy": round(energy, 4),
        "mode": mode,
        "offline": True,
        "source": "mopac-audio-energy",
    }
