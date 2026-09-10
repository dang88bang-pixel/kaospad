#!/usr/bin/env python3
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APK = ROOT / "releases" / "KaossBeatboxStudio-v5.0.0-Universal-Signed.apk"


def main() -> int:
    assert APK.exists(), APK
    data = APK.read_bytes()
    assert data[:2] == b"PK"
    assert b"APK Sig Block 42" in data
    with zipfile.ZipFile(APK) as zf:
        names = set(zf.namelist())
        for required in (
            "AndroidManifest.xml",
            "classes.dex",
            "META-INF/MANIFEST.MF",
            "META-INF/KAOSS.SF",
            "META-INF/KAOSS.RSA",
            "assets/www/index.html",
        ):
            assert required in names, required
        assert zf.read("classes.dex")[:4] == b"dex\n"
        assert zf.read("AndroidManifest.xml")[:2] == b"\x03\x00"
    sha = Path(str(APK) + ".sha256").read_text().split()[0]
    import hashlib

    assert hashlib.sha256(data).hexdigest() == sha
    print(f"signed apk verified: {APK.name} {APK.stat().st_size} bytes v1+v2 sha256={sha[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
