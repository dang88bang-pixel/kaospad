#!/usr/bin/env python3
"""Release-Artifact-Guard: verhindert, dass Platzhalter-Artefakte publiziert werden.

Prüft den vollständigen Artefakt-Satz eines Release-Jobs und schlägt fehl, wenn:

* ein erwartetes Artefakt fehlt oder zu klein ist,
* das APK ein Offline-Stub ist (kein ``lib/<abi>/libkaoss_native.so`` oder kein
  ``classes.dex``) statt eines echten Gradle-Builds,
* SHA256SUMS fehlen oder nicht zu den Dateien passen,
* das SBOM fehlt oder kein gültiges JSON ist.

Usage:
    python3 scripts/verify_release_artifacts.py [ARTIFACT_DIR]
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED = [
    ("KaossBeatboxStudio-v5.0.0-Universal-Signed.apk", "apk", 500_000),
    ("KaossBeatboxStudio-v5.0.0-Universal.aab", "aab", 500_000),
    ("KaossBeatboxStudio-v5.0.0-x86_64.AppImage", "elf", 1_000_000),
    ("KaossBeatboxStudio-v5.0.0-Universal.dmg", "dmg", 256_000),
    ("KaossBeatboxStudio-v5.0.0-Setup.msi", "msi", 256_000),
    ("KaossBeatboxStudio-WebAssembly-Offline.zip", "pwa", 5_000),
    ("SHA256SUMS", "checksums", 1),
    ("sbom.json", "sbom", 1),
]

checks = 0
failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)


def ok(message: str) -> None:
    global checks
    checks += 1
    print(f"  ok: {message}")


def find_files(directory: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in directory.rglob("*"):
        if path.is_file() and path.name in {name for name, _, _ in EXPECTED}:
            found.setdefault(path.name, path)
    return found


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_has(path: Path, predicate) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return any(predicate(name) for name in archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def validate_apk(path: Path) -> None:
    if not zip_has(path, lambda name: name == "classes.dex"):
        fail(f"{path.name}: kein classes.dex (kein ART-Build)")
        return
    has_native_so = zip_has(path, lambda name: name.startswith("lib/") and name.endswith("libkaoss_native.so"))
    if not has_native_so:
        fail(f"{path.name}: kein lib/<abi>/libkaoss_native.so — Offline-Stub, nicht publizierbar")
        return
    ok(f"{path.name}: echter Gradle-APK mit native DSP (.so + classes.dex)")


def validate_aab(path: Path) -> None:
    if not zip_has(path, lambda name: name in {"BundleConfig.pb", "bundle-config.pb"}):
        fail(f"{path.name}: kein BundleConfig.pb (kein echtes AAB)")
        return
    ok(f"{path.name}: Android App Bundle erkannt")


def validate_elf(path: Path) -> None:
    magic = path.read_bytes()[:4]
    if magic != b"\x7fELF":
        fail(f"{path.name}: kein ELF-Executable (AppImage)")
        return
    ok(f"{path.name}: ELF-Executable (AppImage)")


def validate_msi(path: Path) -> None:
    magic = path.read_bytes()[:4]
    if magic != b"\xd0\xcf\x11\xe0":
        fail(f"{path.name}: kein OLE-Compound (MSI)")
        return
    ok(f"{path.name}: OLE-Compound (MSI)")


def validate_dmg(path: Path) -> None:
    # DMG hat keinen stabilen Magic-Header; Grösse + .dmg-Endung als Schwelle.
    if path.stat().st_size < 256_000:
        fail(f"{path.name}: zu klein für ein DMG")
        return
    ok(f"{path.name}: DMG-Paket (Grösse plausibel)")


def validate_pwa(path: Path) -> None:
    if not zip_has(path, lambda name: name.endswith("index.html")):
        fail(f"{path.name}: kein index.html im PWA-Zip")
        return
    if not zip_has(path, lambda name: name.endswith("sw.js")):
        fail(f"{path.name}: kein Service-Worker im PWA-Zip")
        return
    ok(f"{path.name}: PWA-Zip mit index.html + sw.js")


def validate_checksums(path: Path, artifacts: dict[str, Path]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        name = name.lstrip("* ").strip()
        entries[name] = digest
    for artifact_name, artifact_path in artifacts.items():
        if artifact_name in {"SHA256SUMS", "sbom.json"}:
            continue
        if artifact_name not in entries:
            fail(f"SHA256SUMS: {artifact_name} fehlt")
            continue
        if entries[artifact_name] != sha256(artifact_path):
            fail(f"SHA256SUMS: Hash für {artifact_name} stimmt nicht")
    ok("SHA256SUMS vollständig und korrekt")


def validate_sbom(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        fail(f"sbom.json: kein gültiges JSON ({exc})")
        return
    if not payload.get("name") or not payload.get("packages"):
        fail("sbom.json: name/packages fehlen")
        return
    ok(f"SBOM mit {len(payload['packages'])} Einträgen")


VALIDATORS = {
    "apk": validate_apk,
    "aab": validate_aab,
    "elf": validate_elf,
    "msi": validate_msi,
    "dmg": validate_dmg,
    "pwa": validate_pwa,
}


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "release-artifacts"
    if not directory.is_dir():
        print(f"artifact dir not found: {directory}", file=sys.stderr)
        return 2
    artifacts = find_files(directory)
    print(f"verify_release_artifacts: {directory}")
    for name, kind, min_size in EXPECTED:
        path = artifacts.get(name)
        if path is None:
            fail(f"{name}: fehlt")
            continue
        size = path.stat().st_size
        size_ok = size >= min_size
        if not size_ok:
            fail(f"{name}: zu klein ({size} bytes < {min_size})")
        # Inhaltsprüfung trotzdem laufen lassen, damit mehrere Gründe sichtbar sind
        # (z. B. "zu klein" UND "kein natives .so" beim Offline-Stub).
        if kind in VALIDATORS and size > 0:
            VALIDATORS[kind](path)
        elif kind == "checksums" and size_ok:
            validate_checksums(path, artifacts)
        elif kind == "sbom" and size_ok:
            validate_sbom(path)
    if failures:
        print("\nRelease-Artefakte UNVOLLSTÄNDIG/PLATZHALTER:")
        for message in failures:
            print(f"  ✗ {message}")
        return 1
    print(f"\nrelease artifacts verified: {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
