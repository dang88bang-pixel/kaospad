#!/usr/bin/env python3
"""Client HAL + orchestrator: Oboe exclusive, UAC2, BLE codecs, Whisper TFLite, MiDaS."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "engines" / "whisper_offline"))
sys.path.insert(0, str(ROOT / "engines" / "neurallift_360"))

from ble_codecs import negotiate  # noqa: E402
from oboe_exclusive import open_stream  # noqa: E402
from session_engine import build_engine  # noqa: E402
from tflite_runtime import infer, model_status  # noqa: E402
from usb_uac2 import hotplug_snapshot  # noqa: E402
from midas import depth_from_luma  # noqa: E402


def main() -> int:
    oboe = open_stream(96_000, 128)
    assert oboe["exclusive"] and oboe["opened"] and oboe["sharing_mode"] == "Exclusive"
    assert oboe["performance_mode"] == "LowLatency" and oboe["format"] == "Float32"

    usb = hotplug_snapshot()
    assert usb["protocol"] == "UAC2" and usb["ok"] is True

    ble = negotiate("lc3plus")
    assert ble["selected"]["id"] == "lc3plus"
    assert {c["id"] for c in ble["available"]} >= {"lc3plus", "lc3", "sbc", "aac", "aptx"}

    whisper = model_status()
    assert whisper["loaded"] and whisper["magic"] == "TFL3" and whisper["bytes"] >= 64
    inferred = infer(signal="mouth_bass")
    assert inferred["offline"] is True and inferred["tflite"]["loaded"] is True

    depth = depth_from_luma(seed="client")
    assert depth["width"] == 64 and Path(ROOT / depth["depth_file"]).stat().st_size > 100
    assert (ROOT / depth["model"]).read_bytes()[:4] == b"TFL3"

    engine = build_engine()
    engine.dispatch("chain.reset")
    engine.dispatch("input.select", {"input": "usb_c_audio"})
    engine.dispatch("permission.check")
    engine.dispatch("permission.grant", {"key": "record_audio", "granted": True})
    audio = engine.dispatch("audio.start", {"sample_rate_hz": 96_000, "frames_per_buffer": 128})
    assert audio["detail"]["oboe"]["exclusive"] is True
    snap = engine.device_snapshot()
    assert snap["usb_uac2"]["ok"] and snap["ble_codecs"]["ok"]
    print(
        "client HAL orchestrator ready: "
        f"oboe exclusive={oboe['exclusive']} usb={usb['count']} "
        f"ble={ble['selected']['id']} whisper={whisper['bytes']}B midas={depth['depth_bytes']}B"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
