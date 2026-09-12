#!/usr/bin/env python3
"""Release-Guard: Platzhalter-Artefakte dürfen nie publiziert werden.

Negativ-Fixture ist das vorhandene Offline-Stub-APK in ``releases/`` (hat
``classes.dex``, aber kein ``lib/*/libkaoss_native.so``). Der Guard muss dieses
Artefakt ablehnen und einen echten Gradle-APK (Fixtures mit ``.so``) akzeptieren.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_release_artifacts.py"
SBOM = ROOT / "scripts" / "generate_sbom.py"
STUB_APK = ROOT / "releases" / "KaossBeatboxStudio-v5.0.0-Universal-Signed.apk"
WORKFLOW = ROOT / ".github" / "workflows" / "multiplatform-ci-cd.yml"

checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    if not condition:
        raise SystemExit(f"FAIL: {label}" + (f" // {detail}" if detail else ""))
    checks += 1


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)


def make_fixture_dir(tmp: Path) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp


def make_real_apk(path: Path) -> None:
    import os

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AndroidManifest.xml", b"<manifest/>")
        archive.writestr("classes.dex", b"dex\n035\x00" + b"\x00" * 64)
        archive.writestr("lib/arm64-v8a/libkaoss_native.so", b"\x7fELF" + b"\x00" * 4096)
        archive.writestr("lib/armeabi-v7a/libkaoss_native.so", b"\x7fELF" + b"\x00" * 4096)
        # Grösse über der Guard-Schwelle halten (echte Gradle-APKs sind > 1 MB).
        archive.writestr("assets/pad.bin", os.urandom(700_000))


def make_real_aab(path: Path) -> None:
    import os

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BundleConfig.pb", b"\x0a\x00")
        archive.writestr("base/manifest/AndroidManifest.xml", b"<manifest/>")
        archive.writestr("base/dex/classes.dex", b"dex\n035\x00" + b"\x00" * 64)
        archive.writestr("base/lib/arm64-v8a/libkaoss_native.so", b"\x7fELF" + b"\x00" * 4096)
        archive.writestr("base/assets/pad.bin", os.urandom(700_000))


def make_real_pwa(path: Path) -> None:
    import os

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "<html></html>")
        archive.writestr("sw.js", "// service worker")
        archive.writestr("pad.txt", os.urandom(10_000))


def main() -> int:
    import tempfile

    # ------------------------------------------------------------------ #
    # 1. Stub-APK ist kein gültiges Release-Artefakt
    # ------------------------------------------------------------------ #
    check("stub apk exists", STUB_APK.is_file())
    with zipfile.ZipFile(STUB_APK) as archive:
        names = archive.namelist()
    check("stub apk has classes.dex", "classes.dex" in names)
    check("stub apk lacks native .so", not any(name.startswith("lib/") and name.endswith("libkaoss_native.so") for name in names))

    # ------------------------------------------------------------------ #
    # 2. Guard akzeptiert einen echten APK-Fixture
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        make_real_apk(base / "KaossBeatboxStudio-v5.0.0-Universal-Signed.apk")
        make_real_aab(base / "KaossBeatboxStudio-v5.0.0-Universal.aab")
        (base / "KaossBeatboxStudio-v5.0.0-x86_64.AppImage").write_bytes(b"\x7fELF" + b"\x00" * 1_200_000)
        (base / "KaossBeatboxStudio-v5.0.0-Universal.dmg").write_bytes(b"\x00" * 300_000)
        (base / "KaossBeatboxStudio-v5.0.0-Setup.msi").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 300_000)
        make_real_pwa(base / "KaossBeatboxStudio-WebAssembly-Offline.zip")
        (base / "sbom.json").write_text(json.dumps({"name": "KaossBeatboxStudio", "packages": [{"name": "x"}]}), encoding="utf-8")
        # SHA256SUMS für die Fixtures schreiben.
        import hashlib

        lines = []
        for path in sorted(base.iterdir()):
            if path.name in {"SHA256SUMS", "sbom.json"}:
                continue
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
        (base / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = run([sys.executable, str(VERIFY), str(base)], ROOT)
        check("guard accepts real apk fixture", result.returncode == 0, result.stdout[-500:] + result.stderr[-500:])

    # ------------------------------------------------------------------ #
    # 3. Guard lehnt das Stub-APK ab (Negativ-Fixture)
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        # Das Stub-APK als "Universal-Signed" ausgeben lassen.
        (base / "KaossBeatboxStudio-v5.0.0-Universal-Signed.apk").write_bytes(STUB_APK.read_bytes())
        make_real_aab(base / "KaossBeatboxStudio-v5.0.0-Universal.aab")
        (base / "KaossBeatboxStudio-v5.0.0-x86_64.AppImage").write_bytes(b"\x7fELF" + b"\x00" * 1_200_000)
        (base / "KaossBeatboxStudio-v5.0.0-Universal.dmg").write_bytes(b"\x00" * 300_000)
        (base / "KaossBeatboxStudio-v5.0.0-Setup.msi").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 300_000)
        make_real_pwa(base / "KaossBeatboxStudio-WebAssembly-Offline.zip")
        (base / "sbom.json").write_text(json.dumps({"name": "KaossBeatboxStudio", "packages": []}), encoding="utf-8")
        (base / "SHA256SUMS").write_text("", encoding="utf-8")
        result = run([sys.executable, str(VERIFY), str(base)], ROOT)
        check("guard rejects stub apk", result.returncode != 0, result.stdout[-500:])
        check("guard names native .so", "libkaoss_native.so" in result.stdout, result.stdout[-500:])

    # ------------------------------------------------------------------ #
    # 4. Release-Workflow verdrahtet Guard, SBOM und Checksummen
    # ------------------------------------------------------------------ #
    workflow = WORKFLOW.read_text(encoding="utf-8")
    check("workflow runs verify guard", "verify_release_artifacts.py" in workflow)
    check("workflow generates sbom", "generate_sbom.py" in workflow)
    check("workflow emits sha256sums", "sha256sum" in workflow)
    check("workflow builds android via gradle", "assembleRelease" in workflow)

    # ------------------------------------------------------------------ #
    # 5. SBOM-Generator liefert gültiges JSON mit Paketen
    # ------------------------------------------------------------------ #
    result = run([sys.executable, str(SBOM)], ROOT)
    check("sbom generator runs", result.returncode == 0, result.stderr[-300:])
    sbom = json.loads((ROOT / "dist" / "sbom.json").read_text(encoding="utf-8"))
    check("sbom has packages", len(sbom["packages"]) > 20, str(len(sbom["packages"])))
    check("sbom has checksums", all("checksums" in pkg for pkg in sbom["packages"]))

    print(f"release artifact guard verified: {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
