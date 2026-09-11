#!/usr/bin/env python3
"""Create deterministic offline model manifests instead of downloading from cloud."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
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
    # Ensure engines/ is on path for dsp_chain etc. (Alternative Lösungswege J)
    engines_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(engines_root))
    sys.path.insert(0, str(engines_root / "whisper_offline"))
    sys.path.insert(0, str(engines_root / "neurallift_360"))
    sys.path.insert(0, str(engines_root / "mopac_dance_learner"))
    from tflite_runtime import ensure_int8_weights
    from midas import ensure_midas_weights

    ensure_int8_weights(target / "whisper-tiny-multilingual-int8.tflite")
    ensure_midas_weights()
    manifest = []
    for name, payload in MODELS.items():
        path = target / name
        if not path.exists():
            data = payload.encode("utf-8")
            path.write_bytes(data)
        data = path.read_bytes()
        manifest.append({"file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    (target / "MODELS.offline.json").write_text(json.dumps({"offline": True, "models": manifest}, indent=2), encoding="utf-8")
    print(f"prepared {len(manifest)} offline model placeholders in {target}")


if __name__ == "__main__":
    main()
