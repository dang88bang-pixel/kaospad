#!/usr/bin/env python3
"""Offline SBOM (SPDX-artig) für den Quellbaum und die Release-Artefakte.

Keine Cloud, kein Netzwerk: hashed die verfolgten Quelldateien, sammelt
Lizenz-/Herkunftsinformationen und schreibt ``dist/sbom.json``. Zusammen mit
``scripts/verify_release_artifacts.py`` dient das SBOM als CI-Gate, damit nur
echte, nachvollziehbare Artefakte publiziert werden.

Usage:
    python3 scripts/generate_sbom.py [OUT_PATH]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Verzeichnisse, die nie in das SBOM wandern (Build-/Vendor-/Secret-Ausgaben).
EXCLUDED = {
    ".git", "build", "dist", "node_modules", "__pycache__",
    ".gradle", ".idea", ".venv", "target", "out",
}
TRACKED_EXTENSIONS = {
    ".py", ".js", ".mjs", ".html", ".css", ".cpp", ".hpp", ".kt", ".kts",
    ".yml", ".yaml", ".sh", ".ps1", ".md", ".txt", ".json", ".webmanifest",
    ".toml", ".gradle", ".properties", ".xml", ".example", ".pem",
}

KNOWN_LICENSES = {
    "LICENSE": {"name": "proprietary-project-license", "concluded": "NOASSERTION", "source": ROOT / "LICENSE"},
}


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "sbom.json"
    packages: list[dict[str, object]] = []
    for path in sorted(ROOT.rglob("*")):
        if any(part in EXCLUDED for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in TRACKED_EXTENSIONS:
            continue
        rel = path.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        packages.append({
            "name": rel,
            "versionInfo": "5.0.0",
            "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
            "licenseConcluded": "NOASSERTION",
            "downloadLocation": "NOASSERTION",
        })

    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "KaossBeatboxStudio",
        "documentNamespace": "https://kaoss.local/sbom/5.0.0",
        "creationInfo": {
            "created": "2026-09-11T00:00:00Z",
            "creators": ["Tool: generate_sbom.py", "Organization: Kaoss (offline)"],
        },
        "documentDescribes": ["SPDXRef-KaossBeatboxStudio-5.0.0"],
        "packages": packages,
        "relationships": [],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(sbom, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"sbom written: {out_path} ({len(packages)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
