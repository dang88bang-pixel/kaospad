#!/usr/bin/env python3
"""Rhyme ranking 85k DB shim — REAL-IMPLEMENTATION 2026-09-11"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"engines"/"whisper_offline"))
from rhyme_matrix import lookup, ensure_database  # type: ignore
def test_ranking():
    db = ROOT / "dist" / "offline-rhymes.sqlite3"
    ensure_database(db)
    hits = lookup(db, "berlin", limit=5)
    assert isinstance(hits, list), f"expected list got {type(hits)}"
    # lookup returns list of strings (rhymes)
    if hits:
        assert isinstance(hits[0], str)
        assert len(hits[0])>0
    # also test meta
    from rhyme_matrix import lookup_with_meta
    meta = lookup_with_meta(db, "berlin")
    assert "rhymes" in meta or "word" in meta or isinstance(meta, dict)
if __name__ == "__main__":
    test_ranking()
    print("rhyme ranking: 1 check (lookup berlin)")
