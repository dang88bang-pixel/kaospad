#!/usr/bin/env python3
"""Test: NeuralLift-360 Daemon erzeugt echte Meshes (Audit Phase 2, P2-2).

Geprüft wird nicht die Behauptung, sondern die Datei: GLB-Magic/Version,
Vertex-/Triangle-Zahl aus den Bytes zurückgelesen, Determinismus,
Pose-Empfindlichkeit, HTTP-Vertrag und Zero-Cloud-Bindung.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "engines", ROOT / "engines" / "neurallift_360"):
    sys.path.insert(0, str(entry))

import engine_service  # noqa: E402
import glb  # noqa: E402
from mopac_dance_learner.pose import skeleton_frame  # noqa: E402

checks = 0


def check(label: str, condition: bool, info: object = "") -> None:
    global checks
    checks += 1
    if not condition:
        raise SystemExit(f"CHECK FAILED: {label} // {info}")


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> int:
    global checks
    # 1) Mesh-Payload: echte Zahlen aus der Datei
    payload = engine_service.mesh_payload(t_ms=1200.0, energy=0.6, mode="CYPHER_CIRCLE")
    check("payload ok", payload["ok"] is True, payload)
    check("inference ehrlich als False markiert", payload["inference"] is False)
    check("vertices > 0", int(payload["vertices"]) > 0, payload["vertices"])
    check("triangles > 0", int(payload["triangles"]) > 0, payload["triangles"])
    check("lod0_tris == triangles (API-Kompatibilität)", payload["lod0_tris"] == payload["triangles"])
    check("rig_bones == Topologie-Bones", payload["rig_bones"] == len(glb.BONES))
    check("33 Landmarks verarbeitet", payload["landmarks"] == 33, payload["landmarks"])

    path = Path(str(payload["glb_path"]))
    check("GLB auf Platte geschrieben", path.is_file(), path)
    data = path.read_bytes()
    check("GLB-Magic", data[:4] == b"glTF", data[:4])
    stats = glb.glb_stats(data)
    check("Version 2", stats["version"] == 2, stats)
    check("Dateigröße == gemeldete Bytes", stats["bytes"] == len(data) == payload["glb_bytes"])
    check("Vertices aus Datei == gemeldet", stats["vertices"] == payload["vertices"])
    check("Checksumme stabil", len(str(payload["sha256"])) == 64)

    # 2) Determinismus + Pose-Empfindlichkeit
    again = engine_service.mesh_payload(t_ms=1200.0, energy=0.6, mode="CYPHER_CIRCLE", write=False)
    check("deterministisch bei gleicher Pose", again["sha256"] == payload["sha256"])
    other = engine_service.mesh_payload(t_ms=2600.0, energy=0.95, mode="PARTY_8", write=False)
    check("andere Pose -> anderes Mesh", other["sha256"] != payload["sha256"])
    check("Bounds sind echte Zahlen", all(isinstance(v, (int, float)) for v in payload["bounds"]["min"]))

    # 3) Eigene Landmarks werden akzeptiert
    frame = skeleton_frame(400.0, energy=0.3)
    custom = engine_service.mesh_payload(landmarks=frame["landmarks"], write=False)
    check("eigene Landmarks verarbeitet", custom["vertices"] > 0 and custom["ok"], custom)
    try:
        engine_service.mesh_payload(landmarks=frame["landmarks"][:5], write=False)
        raise SystemExit("CHECK FAILED: zu wenige Landmarks hätten abgelehnt werden müssen")
    except ValueError:
        checks += 1

    # 4) HTTP-Vertrag gegen echten Daemon (Thread, Loopback)
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), engine_service.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        time.sleep(0.15)
        health = json.loads(urllib.request.urlopen(base + "/health", timeout=5).read())
        check("/health ok", health["ok"] is True and health["offline"] is True, health)
        check("/health nennt Mesh-Art", health["mesh"] == "landmark-tubes", health)

        default = json.loads(urllib.request.urlopen(base + "/mesh/default", timeout=10).read())
        check("/mesh/default ok", default["ok"] is True, default)
        check("/mesh/default liefert lod0_tris (alte API)", int(default["lod0_tris"]) > 0, default)
        check("/mesh/default liefert rig_bones (alte API)", int(default["rig_bones"]) > 0, default)
        check("/mesh/default liefert sha256", len(str(default["sha256"])) == 64)

        request = urllib.request.Request(
            base + "/mesh",
            data=json.dumps({"t_ms": 900.0, "energy": 0.7, "mode": "PARTY_8"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        posted = json.loads(urllib.request.urlopen(request, timeout=10).read())
        check("POST /mesh ok", posted["ok"] is True, posted)
        check("POST /mesh schreibt Datei", Path(str(posted["glb_path"])).is_file())

        try:
            bad = urllib.request.Request(base + "/mesh", data=b"{kein json", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(bad, timeout=5)
            raise SystemExit("CHECK FAILED: kaputtes JSON hätte 400 geben müssen")
        except urllib.error.HTTPError as error:
            check("kaputtes JSON -> 400", error.code == 400, error.code)
            checks += 1

        try:
            wrong = urllib.request.Request(
                base + "/mesh",
                data=json.dumps({"landmarks": "keine liste"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(wrong, timeout=5)
            raise SystemExit("CHECK FAILED: landmarks als String hätte 400 geben müssen")
        except urllib.error.HTTPError as error:
            check("landmarks nicht Liste -> 400", error.code == 400, error.code)
            checks += 1

        try:
            urllib.request.urlopen(base + "/gibt/es/nicht", timeout=5)
            raise SystemExit("CHECK FAILED: unbekannte Route hätte 404 geben müssen")
        except urllib.error.HTTPError as error:
            check("unbekannte Route -> 404", error.code == 404, error.code)
            checks += 1
    finally:
        server.shutdown()
        server.server_close()

    # 5) Zero-Cloud: nicht-lokale Bindung wird verweigert
    result = subprocess.run(
        [sys.executable, str(ROOT / "engines/neurallift_360/engine_service.py"), "--host", "0.0.0.0"],
        capture_output=True, text=True, timeout=20,
    )
    check("nicht-lokale Bindung verweigert", result.returncode != 0 and "Zero-cloud" in (result.stderr + result.stdout),
          (result.returncode, result.stderr[-200:]))

    print(json.dumps({"checks": checks, "vertices": payload["vertices"], "triangles": payload["triangles"],
                      "glb_bytes": payload["glb_bytes"], "sha256": str(payload["sha256"])[:12]}))
    print(f"neurallift engine service verified: {checks} checks // mesh {payload['vertices']}v/{payload['triangles']}t "
          f"// {payload['glb_bytes']} B // inference=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
