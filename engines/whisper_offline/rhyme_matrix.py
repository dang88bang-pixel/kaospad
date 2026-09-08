#!/usr/bin/env python3
"""Offline SQLite rhyme matrix for the Kaoss cypher helper."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DEFAULT_ROWS = [
    ("beton", "eːtoːn", "beton,sektor,dämon,neon,phonon"),
    ("sektor", "ɛktoːr", "beton,sektor,vektor,detektor,projektor"),
    ("dämon", "ɛːmoːn", "beton,dämon,neon,patron,saison"),
    ("kaoss", "aʊs", "raus,haus,applaus,maus,brauchs"),
    ("berlin", "ɪn", "termin,gewinn,benzin,magazin,ramin"),
    ("cypher", "aɪfɐ", "eifer,greifer,schleifer,streifer,live-er"),
]


def ensure_database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS rhymes "
            "(word TEXT PRIMARY KEY, phonetic TEXT NOT NULL, suggestions TEXT NOT NULL)"
        )
        db.executemany(
            "INSERT OR REPLACE INTO rhymes(word, phonetic, suggestions) VALUES (?, ?, ?)",
            DEFAULT_ROWS,
        )
        db.commit()
    return path


def lookup(path: Path, word: str) -> list[str]:
    ensure_database(path)
    normalized = word.strip().lower()
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT suggestions FROM rhymes WHERE word = ?", (normalized,)).fetchone()
    if row:
        return [item.strip().upper() for item in row[0].split(",") if item.strip()]
    tail = normalized[-3:] if len(normalized) >= 3 else normalized
    return [w.upper() for w, _, _ in DEFAULT_ROWS if w.endswith(tail)][:5] or ["BETON", "SEKTOR", "DÄMON"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="dist/offline-rhymes.sqlite3")
    parser.add_argument("--lookup")
    args = parser.parse_args()
    path = ensure_database(Path(args.db))
    if args.lookup:
        print("\n".join(lookup(path, args.lookup)))
    else:
        print(path)


if __name__ == "__main__":
    main()
