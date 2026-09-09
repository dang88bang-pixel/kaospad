#!/usr/bin/env python3
"""Minimal binary GLB writer (glTF 2.0) for offline NeuralLift fallback meshes.

Produces a valid .glb with a 24-vertex capsule so the avatar path ships a real
file instead of a filename stub. No cloud, no ML weights.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path


def _align4(data: bytes) -> bytes:
    pad = (4 - (len(data) % 4)) % 4
    return data + (b" " * pad if pad else b"")


def build_capsule_glb(seed: str = "kaoss") -> bytes:
    verts: list[float] = []
    norms: list[float] = []
    idx: list[int] = []
    rings, segs = 6, 8
    for r in range(rings + 1):
        v = r / rings
        y = (v - 0.5) * 1.8
        radius = 0.22 + 0.18 * math.sin(v * math.pi)
        for s in range(segs):
            a = (2.0 * math.pi * s) / segs
            x, z = radius * math.cos(a), radius * math.sin(a)
            verts.extend([x, y, z])
            length = math.sqrt(x * x + y * y + z * z) or 1.0
            norms.extend([x / length, y / length, z / length])
    for r in range(rings):
        for s in range(segs):
            a = r * segs + s
            b = r * segs + (s + 1) % segs
            c = (r + 1) * segs + s
            d = (r + 1) * segs + (s + 1) % segs
            idx.extend([a, c, b, b, c, d])
    vbytes = struct.pack("<" + "f" * len(verts), *verts)
    nbytes = struct.pack("<" + "f" * len(norms), *norms)
    ibytes = struct.pack("<" + "H" * len(idx), *idx)
    blob = vbytes + nbytes + ibytes
    n_verts = len(verts) // 3
    accessor_pos = {"bufferView": 0, "componentType": 5126, "count": n_verts, "type": "VEC3", "min": [-0.5, -1.0, -0.5], "max": [0.5, 1.0, 0.5]}
    accessor_nrm = {"bufferView": 1, "componentType": 5126, "count": n_verts, "type": "VEC3"}
    accessor_idx = {"bufferView": 2, "componentType": 5123, "count": len(idx), "type": "SCALAR"}
    gltf = {
        "asset": {"version": "2.0", "generator": f"kaoss-neurallift-offline:{seed}"},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vbytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(vbytes), "byteLength": len(nbytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(vbytes) + len(nbytes), "byteLength": len(ibytes), "target": 34963},
        ],
        "accessors": [accessor_pos, accessor_nrm, accessor_idx],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "mode": 4}]}],
        "nodes": [{"mesh": 0, "name": "NeuralLiftCapsule"}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_chunk = _align4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"))
    bin_chunk = blob + (b"\x00" * ((4 - (len(blob) % 4)) % 4))
    json_header = struct.pack("<I", len(json_chunk)) + b"JSON"
    bin_header = struct.pack("<I", len(bin_chunk)) + b"BIN\x00"
    body = json_header + json_chunk + bin_header + bin_chunk
    total = 12 + len(body)
    header = b"glTF" + struct.pack("<II", 2, total)
    return header + body


def write_glb(path: Path, seed: str = "kaoss") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_capsule_glb(seed))
    return path
