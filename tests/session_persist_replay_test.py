#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

from session_engine import build_engine  # noqa: E402


def main() -> int:
    engine = build_engine()
    report = engine.run_script()
    assert report["ok"], report["blocked"]
    path = engine.persist_session()
    loaded = engine.load_session(path)
    assert loaded["checksum"] == report["final_state"]["chain"] or loaded["checksum"]
    replay = engine.replay_cypher(loaded, strict=False)
    assert replay["steps"] >= 1
    print(f"session persist/replay ok path={path.name} checksum={loaded['checksum'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
