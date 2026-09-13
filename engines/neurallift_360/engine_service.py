#!/usr/bin/env python3
"""Offline NeuralLift-360 Daemon – echte Mesh-Erzeugung aus Pose-Landmarks.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 2, P2-2)
Vorher: Stub, der feste Werte lieferte
(`{"glb": "procedural_default_avatar.glb", "lod0_tris": 45000, "rig_bones": 24}`
– Dateiname als String, Triangle-Zahl hartcodiert, Datei existierte nicht).

Jetzt: Der Daemon erzeugt pro Anfrage ein reales glTF-2.0-GLB aus 33
Pose-Landmarks (`mopac_dance_learner.pose.skeleton_frame` -> Röhrenmesh über die
MediaPipe-Bone-Topologie, `neurallift_360.glb.build_landmark_glb`), schreibt es
nach `dist/avatars/` und meldet Vertices/Triangles/Bytes/SHA-256 **aus der
geschriebenen Datei zurückgelesen** (`glb.glb_stats`), nicht aus Annahmen.

API-Kompatibilität: `GET /health` und `GET /mesh/default` behalten ihre
bisherigen Felder (`glb`, `lod0_tris`, `rig_bones`) und liefern zusätzliche.
Neu: `POST /mesh` für eine konkrete Pose (t_ms/energy/mode oder Landmarks).

Ehrliche Grenze: keine ML-Inferenz. Es gibt keine vendorten MiDaS/MediaPipe-
Gewichte (⛔ lizenzpflichtig); die Pose kommt aus der Audio-Energie-Synthese und
die Geometrie ist prozedural. Bindet ausschließlich 127.0.0.1 (Zero-Cloud).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "engines", ROOT / "engines" / "neurallift_360"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import glb  # noqa: E402
from mopac_dance_learner.pose import LANDMARKS, skeleton_frame  # noqa: E402

AVATAR_DIR = ROOT / "dist" / "avatars"
# Erzeugung darf nie hängen: Hartes Zeitbudget pro Mesh (Phase-3-Vorgabe).
MESH_BUDGET_S = 5.0


def avatar_dir() -> Path:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    return AVATAR_DIR


def frame_for(t_ms: float, energy: float, mode: str) -> dict[str, object]:
    return skeleton_frame(float(t_ms), energy=float(energy), mode=str(mode))


def mesh_payload(
    t_ms: float = 0.0,
    energy: float = 0.5,
    mode: str = "CYPHER_CIRCLE",
    landmarks: list[object] | None = None,
    write: bool = True,
    seed: str | None = None,
) -> dict[str, object]:
    """Erzeugt ein Landmark-Mesh und liest die Kennzahlen aus der Datei zurück."""
    started = time.perf_counter()
    frame = frame_for(t_ms, energy, mode)
    points = list(landmarks) if landmarks else frame["landmarks"]
    digest_seed = seed or hashlib.sha256(
        json.dumps([[round(float(item["x"]), 5), round(float(item["y"]), 5), round(float(item["z"]), 5)]
                    for item in points], separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]

    data = glb.build_landmark_glb(points, seed=digest_seed)
    stats = glb.glb_stats(data)  # zählt aus den Bytes, nicht aus Variablen
    checksum = hashlib.sha256(data).hexdigest()

    path: Path | None = None
    if write:
        path = avatar_dir() / f"neurallift-{checksum[:16]}.glb"
        path.write_bytes(data)
        # Rücklese-Check: die gemeldeten Zahlen müssen zur Datei auf Platte passen.
        on_disk = glb.glb_stats(path.read_bytes())
        if on_disk["vertices"] != stats["vertices"] or on_disk["bytes"] != path.stat().st_size:
            raise RuntimeError("GLB-Rückleseprüfung fehlgeschlagen")

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "ok": True,
        # --- bisherige API (kompatibel) ---
        "glb": path.name if path else f"neurallift-{checksum[:16]}.glb",
        "lod0_tris": stats["triangles"],
        "rig_bones": stats["bones"],
        # --- echte Kennzahlen ---
        "glb_path": str(path) if path else "",
        "glb_bytes": stats["bytes"],
        "vertices": stats["vertices"],
        "triangles": stats["triangles"],
        "sha256": checksum,
        "magic": stats["magic"],
        "generator": stats["generator"],
        "bounds": {"min": stats["bounds_min"], "max": stats["bounds_max"]},
        "landmarks": len(points),
        "landmark_names": LANDMARKS,
        "pose": {"t_ms": float(t_ms), "energy": float(energy), "mode": str(mode), "source": frame["source"]},
        "generated_ms": round(elapsed_ms, 3),
        "inference": False,
        "note": "prozedurale Geometrie aus Audio-Energie-Pose; keine ML-Gewichte (offline, Zero-Cloud)",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "NeuralLift360Offline/5.1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json({
                "ok": True,
                "engine": "neurallift-360",
                "offline": True,
                "inference": False,
                "mesh": "landmark-tubes",
                "bones": len(glb.BONES),
                "landmarks": len(LANDMARKS),
            })
            return
        if self.path in {"/mesh/default", "/api/neurallift/default"}:
            self._guarded(lambda: mesh_payload(t_ms=0.0, energy=0.5, mode="CYPHER_CIRCLE"))
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/mesh", "/api/neurallift/mesh"}:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            params = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"ok": False, "error": f"payload unreadable: {error}"}, code=400)
            return
        landmarks = params.get("landmarks")
        if landmarks is not None and not isinstance(landmarks, list):
            self._json({"ok": False, "error": "landmarks must be a list"}, code=400)
            return
        self._guarded(
            lambda: mesh_payload(
                t_ms=float(params.get("t_ms", 0.0)),
                energy=float(params.get("energy", 0.5)),
                mode=str(params.get("mode", "CYPHER_CIRCLE")),
                landmarks=landmarks,
                write=bool(params.get("write", True)),
            )
        )

    # ------------------------------------------------------------------ #
    def _guarded(self, produce) -> None:
        """Fehler abfangen + Zeitbudget – der Daemon darf nie hängen/crashen."""
        started = time.perf_counter()
        try:
            payload = produce()
        except Exception as error:  # noqa: BLE001 – Daemon muss antworten
            self._json({"ok": False, "error": f"{type(error).__name__}: {error}"}, code=500)
            return
        if time.perf_counter() - started > MESH_BUDGET_S:
            payload = {**payload, "ok": False, "error": f"mesh budget exceeded ({MESH_BUDGET_S}s)"}
        self._json(payload)

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:  # bewusst still
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Zero-cloud policy violation: daemon must bind localhost only")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
