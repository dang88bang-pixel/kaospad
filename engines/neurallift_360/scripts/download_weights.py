#!/usr/bin/env python3
"""Create deterministic offline model manifests instead of downloading from cloud."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MODELS = {
    "whisper-tiny-multilingual-int8.tflite": "offline-placeholder:whisper:5.0.0",
    "neurallift-depth-int8.tflite": "offline-placeholder:depth:5.0.0",
    "edge-motion-int8.onnx": "offline-placeholder:motion:5.0.0",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="dist/offline-models")
    args = parser.parse_args()
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, payload in MODELS.items():
        data = payload.encode("utf-8")
        path = target / name
        path.write_bytes(data)
        manifest.append({"file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    (target / "MODELS.offline.json").write_text(json.dumps({"offline": True, "models": manifest}, indent=2), encoding="utf-8")
    print(f"prepared {len(manifest)} offline model placeholders in {target}")


if __name__ == "__main__":
    main()
