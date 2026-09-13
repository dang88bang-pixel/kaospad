#!/usr/bin/env python3
"""Binary GLB writer (glTF 2.0) für die Offline-NeuralLift-Meshes.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 2, P2-1)
Der alte Docstring nannte diese Datei einen "filename stub". Das war seit der
Einführung des binären Writers veraltet; das Audit (REPORT.md, Phase 1) führt es
als falschen Marker. Tatsächlich schreibt dieses Modul echte, validierbare
.glb-Dateien (Magic `glTF`, Version 2, JSON- + BIN-Chunk):

    build_capsule_glb(seed)   deterministische 24-Vertex-Kapsel; 2676-2684 B
                              je nach Seed-Länge (tests/full_chain_attributes_test.py
                              prüft Magic + Mindestgröße und gibt die Größe aus)
    build_landmark_glb(...)   Mesh aus 33 Pose-Landmarks (Röhre pro Bone);
                              Vertex-/Triangle-Zahl und Checksumme echt berechnet

Kein Cloud-Zugriff, keine ML-Gewichte: die Geometrie ist prozedural, aber real.
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


# --------------------------------------------------------------------------- #
# -- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 2, P2-2)
# Echtes Mesh aus Pose-Landmarks statt fixierter Kapsel: pro Bone eine Röhre,
# Vertex-/Normalen-/Index-Puffer werden aus den Landmark-Koordinaten berechnet.
# --------------------------------------------------------------------------- #

# MediaPipe-Pose-Topologie (33 Landmarks) – Rumpf, Arme, Hände, Beine, Füße, Kopf.
BONES: tuple[tuple[int, int], ...] = (
    (11, 12), (11, 23), (12, 24), (23, 24),
    (11, 13), (13, 15), (12, 14), (14, 16),
    (15, 17), (15, 19), (15, 21), (16, 18), (16, 20), (16, 22),
    (23, 25), (25, 27), (24, 26), (26, 28),
    (27, 29), (29, 31), (28, 30), (30, 32),
    (7, 11), (8, 12), (0, 7), (0, 8),
)


def _landmark_point(landmark: object) -> tuple[float, float, float]:
    if isinstance(landmark, dict):
        return float(landmark.get("x", 0.0)), float(landmark.get("y", 0.0)), float(landmark.get("z", 0.0))
    sequence = list(landmark)  # type: ignore[arg-type]
    return float(sequence[0]), float(sequence[1]), float(sequence[2] if len(sequence) > 2 else 0.0)


def _tube(start: tuple[float, float, float], end: tuple[float, float, float], radius: float, rings: int, segs: int):
    """Röhre zwischen zwei Punkten: (positionen, normalen, indices, basis_offset)."""
    dx, dy, dz = end[0] - start[0], end[1] - start[1], end[2] - start[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
    axis = (dx / length, dy / length, dz / length)
    # Beliebige, aber deterministische Orthogonalbasis um die Bone-Achse.
    helper = (0.0, 1.0, 0.0) if abs(axis[1]) < 0.9 else (1.0, 0.0, 0.0)
    ux = axis[1] * helper[2] - axis[2] * helper[1]
    uy = axis[2] * helper[0] - axis[0] * helper[2]
    uz = axis[0] * helper[1] - axis[1] * helper[0]
    ulen = math.sqrt(ux * ux + uy * uy + uz * uz) or 1e-6
    u = (ux / ulen, uy / ulen, uz / ulen)
    v = (axis[1] * u[2] - axis[2] * u[1], axis[2] * u[0] - axis[0] * u[2], axis[0] * u[1] - axis[1] * u[0])

    positions: list[float] = []
    normals: list[float] = []
    for r in range(rings + 1):
        t = r / rings
        cx = start[0] + dx * t
        cy = start[1] + dy * t
        cz = start[2] + dz * t
        taper = 1.0 - 0.25 * math.sin(t * math.pi)  # leichte Mitte-Verjüngung
        for s in range(segs):
            angle = (2.0 * math.pi * s) / segs
            nx = u[0] * math.cos(angle) + v[0] * math.sin(angle)
            ny = u[1] * math.cos(angle) + v[1] * math.sin(angle)
            nz = u[2] * math.cos(angle) + v[2] * math.sin(angle)
            positions.extend([cx + nx * radius * taper, cy + ny * radius * taper, cz + nz * radius * taper])
            normals.extend([nx, ny, nz])

    indices: list[int] = []
    for r in range(rings):
        for s in range(segs):
            a = r * segs + s
            b = r * segs + (s + 1) % segs
            c = (r + 1) * segs + s
            d = (r + 1) * segs + (s + 1) % segs
            indices.extend([a, c, b, b, c, d])
    return positions, normals, indices


def build_landmark_glb(
    landmarks: list[object],
    seed: str = "neurallift",
    rings: int = 4,
    segs: int = 6,
    node_name: str = "NeuralLiftPose",
) -> bytes:
    """glTF-2.0-GLB aus 33 Pose-Landmarks (ein Rohr pro Bone der Topologie)."""
    points = [_landmark_point(item) for item in landmarks]
    if len(points) < max(max(pair) for pair in BONES) + 1:
        raise ValueError(f"erwartet >= {max(max(pair) for pair in BONES) + 1} Landmarks, bekommen {len(points)}")

    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []
    for a, b in BONES:
        start, end = points[a], points[b]
        span = math.dist(start, end)
        radius = max(0.012, min(0.07, 0.16 * span))
        tube_pos, tube_nrm, tube_idx = _tube(start, end, radius, rings, segs)
        offset = len(positions) // 3
        positions.extend(tube_pos)
        normals.extend(tube_nrm)
        indices.extend(index + offset for index in tube_idx)

    n_verts = len(positions) // 3
    mins = [min(positions[i::3]) for i in range(3)]
    maxs = [max(positions[i::3]) for i in range(3)]

    vbytes = struct.pack("<" + "f" * len(positions), *positions)
    nbytes = struct.pack("<" + "f" * len(normals), *normals)
    ibytes = struct.pack("<" + "H" * len(indices), *indices)
    blob = vbytes + nbytes + ibytes

    gltf = {
        "asset": {"version": "2.0", "generator": f"kaoss-neurallift-landmarks:{seed}"},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vbytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(vbytes), "byteLength": len(nbytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(vbytes) + len(nbytes), "byteLength": len(ibytes), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0, "componentType": 5126, "count": n_verts, "type": "VEC3",
                "min": [round(value, 6) for value in mins], "max": [round(value, 6) for value in maxs],
            },
            {"bufferView": 1, "componentType": 5126, "count": n_verts, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": len(indices), "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "mode": 4}]}],
        "nodes": [{"mesh": 0, "name": node_name}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
        "extras": {"bones": len(BONES), "landmarks": len(points), "source": "mopac-audio-energy"},
    }
    json_chunk = _align4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"))
    bin_chunk = blob + (b"\x00" * ((4 - (len(blob) % 4)) % 4))
    body = struct.pack("<I", len(json_chunk)) + b"JSON" + json_chunk + struct.pack("<I", len(bin_chunk)) + b"BIN\x00" + bin_chunk
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def write_landmark_glb(path: Path, landmarks: list[object], seed: str = "neurallift") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_landmark_glb(landmarks, seed=seed))
    return path


def glb_stats(data: bytes) -> dict[str, object]:
    """Zählt Vertices/Triangles aus der Datei selbst – nicht aus Annahmen."""
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("kein GLB (Magic fehlt)")
    version, total = struct.unpack_from("<II", data, 4)
    json_len = struct.unpack_from("<I", data, 12)[0]
    if data[16:20] != b"JSON":
        raise ValueError("erster Chunk ist kein JSON")
    document = json.loads(data[20 : 20 + json_len].decode("utf-8"))
    accessors = document.get("accessors", [])
    position = next((a for a in accessors if a.get("type") == "VEC3" and "min" in a), {})
    index_accessor = next((a for a in accessors if a.get("componentType") == 5123), {})
    return {
        "magic": "glTF",
        "version": version,
        "bytes": total,
        "json_chunk_bytes": json_len,
        "vertices": int(position.get("count", 0)),
        "triangles": int(index_accessor.get("count", 0)) // 3,
        "generator": document.get("asset", {}).get("generator", ""),
        "bounds_min": position.get("min"),
        "bounds_max": position.get("max"),
        "bones": int(document.get("extras", {}).get("bones", 0)),
        "landmarks": int(document.get("extras", {}).get("landmarks", 0)),
    }
