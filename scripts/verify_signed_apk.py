#!/usr/bin/env python3
"""Guard fuer echte, signierte Release-APKs (Struktur + Signatur-Schemata).

Der Guard trennt zwei Dinge hart:

* **Echter Gradle/AGP-Build** - hat ``classes.dex``, ``resources.arsc``,
  ``lib/<abi>/libkaoss_native.so`` (Native-DSP), die synchronisierte PWA unter
  ``assets/www/`` und eine von ``apksigner`` verifizierbare Signatur.
* **Offline-Stub** (``releases/KaossBeatboxStudio-v5.0.0-Universal-Signed.apk``)
  - handgebaut, ohne ``lib/*.so``. Er darf niemals als Release-APK publiziert
  werden und dient hier als Negativ-Fixture.

Usage:
    python3 scripts/verify_signed_apk.py dist-release/App.apk \
        --apksigner-report dist-release/apksigner-report.txt --require-v1
    python3 scripts/verify_signed_apk.py --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB_APK = ROOT / "releases" / "KaossBeatboxStudio-v5.0.0-Universal-Signed.apk"
APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
DEFAULT_ABIS = ("armeabi-v7a", "arm64-v8a", "x86_64")
DEFAULT_MIN_SIZE = 500_000
NATIVE_LIB = "libkaoss_native.so"

_checks = 0
_failures: list[str] = []


def ok(message: str) -> None:
    global _checks
    _checks += 1
    print(f"  ok: {message}")


def fail(message: str) -> None:
    _failures.append(message)
    print(f"FAIL: {message}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_apksigner_report(text: str) -> dict[str, object]:
    """Liest ``apksigner verify --verbose --print-certs`` aus."""
    def scheme(pattern: str) -> bool | None:
        match = re.search(pattern + r":\s*(true|false)", text)
        return None if match is None else match.group(1) == "true"

    signers = re.search(r"Number of signers:\s*(\d+)", text)
    digest = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-fA-F]{64})", text)
    dn = re.search(r"Signer #1 certificate DN:\s*(.+)", text)
    return {
        "verifies": text.strip().splitlines()[0].strip() == "Verifies" if text.strip() else False,
        "v1": scheme(r"Verified using v1 scheme \(JAR signing\)"),
        "v2": scheme(r"Verified using v2 scheme \(APK Signature Scheme v2\)"),
        "v3": scheme(r"Verified using v3 scheme \(APK Signature Scheme v3\)"),
        "v4": scheme(r"Verified using v4 scheme \(APK Signature Scheme v4\)"),
        "signers": int(signers.group(1)) if signers else None,
        "cert_sha256": digest.group(1) if digest else None,
        "cert_dn": dn.group(1).strip() if dn else None,
    }


def verify_apk(
    apk: Path,
    abis: tuple[str, ...] = DEFAULT_ABIS,
    min_size: int = DEFAULT_MIN_SIZE,
    report_path: Path | None = None,
    require_v1: bool = False,
    require_pwa_assets: bool = True,
) -> dict[str, object]:
    print(f"verify: {apk}")
    result: dict[str, object] = {"apk": str(apk), "checks": 0, "failures": []}

    if not apk.is_file():
        fail(f"{apk}: Datei fehlt")
        return _finish(result)

    size = apk.stat().st_size
    result["size_bytes"] = size
    if size < min_size:
        fail(f"{apk.name}: {size} bytes < {min_size} - Platzhalter/Stub, kein Gradle-Build")
    else:
        ok(f"{apk.name}: {size} bytes (>= {min_size})")

    raw_head = apk.read_bytes()
    if raw_head[:2] != b"PK":
        fail(f"{apk.name}: kein ZIP/APK (Magic {raw_head[:2]!r})")
        return _finish(result)

    try:
        with zipfile.ZipFile(apk) as archive:
            names = archive.namelist()
            manifest = archive.read("AndroidManifest.xml")[:2] if "AndroidManifest.xml" in names else b""
    except (zipfile.BadZipFile, OSError) as exc:
        fail(f"{apk.name}: ZIP nicht lesbar ({exc})")
        return _finish(result)

    nameset = set(names)

    if "AndroidManifest.xml" not in nameset:
        fail(f"{apk.name}: AndroidManifest.xml fehlt")
    elif manifest != b"\x03\x00":
        fail(f"{apk.name}: AndroidManifest.xml ist kein binaeres AXML (Magic {manifest!r})")
    else:
        ok("AndroidManifest.xml: binaeres AXML")

    if not any(n == "classes.dex" or re.fullmatch(r"classes\d*\.dex", n) for n in nameset):
        fail(f"{apk.name}: kein classes.dex - kein ART-Build (Stub?)")
    else:
        ok("classes.dex vorhanden (ART)")

    if "resources.arsc" not in nameset:
        fail(f"{apk.name}: resources.arsc fehlt")
    else:
        ok("resources.arsc vorhanden")

    present_abis = sorted({n.split("/")[1] for n in names if n.startswith("lib/") and n.count("/") >= 2})
    missing_native = [abi for abi in abis if f"lib/{abi}/{NATIVE_LIB}" not in nameset]
    if not present_abis:
        fail(f"{apk.name}: kein lib/<abi>/ - Offline-Stub ohne Native-DSP, nicht publizierbar")
    elif missing_native:
        fail(f"{apk.name}: {NATIVE_LIB} fehlt fuer ABI(s): {', '.join(missing_native)} (gefunden: {', '.join(present_abis)})")
    else:
        ok(f"Native-DSP {NATIVE_LIB} fuer {', '.join(abis)}")
    result["abis"] = present_abis

    stl = [n for n in names if n.startswith("lib/") and n.endswith("libc++_shared.so")]
    if abis and not stl:
        fail(f"{apk.name}: libc++_shared.so fehlt (ANDROID_STL=c++_shared erwartet)")
    elif stl:
        ok(f"libc++_shared.so in {len(stl)} ABI(s)")

    if require_pwa_assets:
        if "assets/www/index.html" not in nameset:
            fail(f"{apk.name}: assets/www/index.html fehlt - PWA nicht synchronisiert")
        else:
            ok("assets/www/index.html (PWA) im APK")

    # Signatur-Schemata: v1 = JAR-Files, v2/v3 = APK Signing Block.
    v1_files = [n for n in names if n.startswith("META-INF/") and n.upper().endswith((".RSA", ".DSA", ".EC"))]
    has_v1_files = bool(v1_files) and "META-INF/MANIFEST.MF" in nameset
    has_sig_block = APK_SIG_BLOCK_MAGIC in raw_head
    result["v1_jar_files"] = has_v1_files
    result["apk_signing_block_magic"] = has_sig_block
    if has_v1_files:
        ok(f"v1 JAR-Signatur-Files: {', '.join(sorted(v1_files))}")
    if has_sig_block:
        ok("APK Signing Block (v2/v3) Magic gefunden")

    report: dict[str, object] = {}
    if report_path is not None:
        if not report_path.is_file():
            fail(f"apksigner-Report fehlt: {report_path}")
        else:
            report = parse_apksigner_report(report_path.read_text(encoding="utf-8", errors="replace"))
            result["apksigner"] = report
            if not report.get("verifies"):
                fail("apksigner meldet NICHT 'Verifies' - Signatur ungueltig")
            else:
                ok("apksigner: Verifies")
            if report.get("v2") is not True:
                fail(f"APK Signature Scheme v2 nicht verifiziert (v2={report.get('v2')})")
            else:
                ok("APK Signature Scheme v2 verifiziert")
            if require_v1 and report.get("v1") is not True:
                fail(f"v1 JAR-Signatur gefordert, aber v1={report.get('v1')}")
            elif report.get("v1") is True:
                ok("v1 JAR-Signatur verifiziert")
            if report.get("v3") is True:
                ok("APK Signature Scheme v3 verifiziert")
            signers = report.get("signers")
            if signers != 1:
                fail(f"erwartet genau 1 Signer, gefunden: {signers}")
            else:
                ok(f"1 Signer: {report.get('cert_dn')}")
            if report.get("cert_sha256"):
                ok(f"Zertifikat-SHA-256: {report['cert_sha256']}")
                result["cert_sha256"] = report["cert_sha256"]
    elif not has_sig_block:
        fail("weder apksigner-Report noch APK Signing Block - Signatur nicht nachweisbar")

    result["sha256"] = sha256_of(apk)
    ok(f"SHA-256: {result['sha256']}")
    return _finish(result)


def _finish(result: dict[str, object]) -> dict[str, object]:
    result["checks"] = _checks
    result["failures"] = list(_failures)
    result["valid"] = not _failures
    return result


# --------------------------------------------------------------------------- #
# Selftest (laeuft ohne Android SDK: Fixtures statt echtem Gradle-Build)
# --------------------------------------------------------------------------- #
def _fixture_real_apk(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AndroidManifest.xml", b"\x03\x00" + b"\x00" * 3200)
        archive.writestr("classes.dex", b"dex\n035\x00" + os.urandom(64_000))
        archive.writestr("resources.arsc", b"\x02\x00\x0c\x00" + os.urandom(4_000))
        for abi in DEFAULT_ABIS:
            archive.writestr(f"lib/{abi}/{NATIVE_LIB}", b"\x7fELF" + os.urandom(120_000))
            archive.writestr(f"lib/{abi}/libc++_shared.so", b"\x7fELF" + os.urandom(60_000))
        archive.writestr("assets/www/index.html", "<html></html>")
        archive.writestr("assets/www/src/app.js", "// app")
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
        archive.writestr("META-INF/KAOSS.SF", "Signature-Version: 1.0\r\n")
        archive.writestr("META-INF/KAOSS.RSA", os.urandom(1_200))
        # APK Signing Block Magic als rohes ZIP-Member (Heuristik, apksigner ist autoritativ)
        archive.writestr("META-INF/apk-sig-block.bin", APK_SIG_BLOCK_MAGIC, compress_type=zipfile.ZIP_STORED)


def _fixture_report(path: Path, v1: bool = True, v2: bool = True, v3: bool = True) -> None:
    path.write_text(
        "\n".join(
            [
                "Verifies",
                "",
                f"Verified using v1 scheme (JAR signing): {str(v1).lower()}",
                f"Verified using v2 scheme (APK Signature Scheme v2): {str(v2).lower()}",
                f"Verified using v3 scheme (APK Signature Scheme v3): {str(v3).lower()}",
                "Verified using v4 scheme (APK Signature Scheme v4): false",
                "Number of signers: 1",
                "Signer #1 certificate DN: CN=Kaoss Beatbox Studio, OU=CI Release, O=Kaoss, L=Berlin, C=DE",
                "Signer #1 certificate SHA-256 digest: " + "ab" * 32,
                "Signer #1 certificate SHA-1 digest: " + "cd" * 20,
                "Signer #1 certificate MD5 digest: " + "ef" * 16,
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _reset() -> None:
    global _checks, _failures
    _checks = 0
    _failures = []


def selftest() -> int:
    import tempfile

    expectations = 0

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        good = base / "KaossBeatboxStudio-v5.0.0-50000-universal-signed.apk"
        report = base / "apksigner-report.txt"
        _fixture_real_apk(good)
        _fixture_report(report)

        _reset()
        result = verify_apk(good, report_path=report, require_v1=True)
        expectations += 1
        if not result.get("valid"):
            print(f"FAIL: selftest positives Fixture abgelehnt: {result['failures']}")
            return 1

        # Negativ 1: Offline-Stub aus releases/ (hat classes.dex, aber kein lib/*.so)
        if STUB_APK.is_file():
            _reset()
            stub_result = verify_apk(STUB_APK, report_path=None, require_pwa_assets=False)
            expectations += 1
            if stub_result.get("valid"):
                print("FAIL: selftest - Offline-Stub wurde akzeptiert")
                return 1
            joined = " ".join(map(str, stub_result["failures"]))
            if "lib/" not in joined:
                print(f"FAIL: selftest - Stub-Ablehnung nennt fehlendes lib/ nicht: {stub_result['failures']}")
                return 1
        else:
            print(f"  warn: Negativ-Fixture fehlt ({STUB_APK})")

        # Negativ 2: kaputte Signatur (v2 false) muss abgelehnt werden
        bad_report = base / "bad-report.txt"
        _fixture_report(bad_report, v1=True, v2=False, v3=False)
        _reset()
        bad = verify_apk(good, report_path=bad_report, require_v1=True)
        expectations += 1
        if bad.get("valid"):
            print("FAIL: selftest - APK ohne v2-Signatur wurde akzeptiert")
            return 1

        # Negativ 3: zu kleine Datei (Platzhalter)
        tiny = base / "tiny.apk"
        tiny.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
        _reset()
        if verify_apk(tiny, report_path=None).get("valid"):
            print("FAIL: selftest - Platzhalter-APK wurde akzeptiert")
            return 1
        expectations += 1

    print(f"verify_signed_apk selftest passed: {expectations} Szenarien")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifiziert echte, signierte Release-APKs.")
    parser.add_argument("apks", nargs="*", help="APK-Pfad(e)")
    parser.add_argument("--abis", default=",".join(DEFAULT_ABIS), help="Kommagetrennte ABI-Liste")
    parser.add_argument("--min-size", type=int, default=DEFAULT_MIN_SIZE)
    parser.add_argument("--apksigner-report", type=Path, default=None)
    parser.add_argument("--require-v1", action="store_true", help="v1 JAR-Signatur zwingend verlangen")
    parser.add_argument("--no-pwa-assets", action="store_true", help="assets/www nicht verlangen")
    parser.add_argument("--json", type=Path, default=None, help="Ergebnis zusaetzlich als JSON schreiben")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if not args.apks:
        parser.error("keine APK angegeben (oder --selftest nutzen)")

    abis = tuple(a.strip() for a in args.abis.split(",") if a.strip())
    results = []
    all_failures: list[str] = []
    total_checks = 0
    for raw in args.apks:
        _reset()
        result = verify_apk(
            Path(raw),
            abis=abis,
            min_size=args.min_size,
            report_path=args.apksigner_report,
            require_v1=args.require_v1,
            require_pwa_assets=not args.no_pwa_assets,
        )
        results.append(result)
        all_failures.extend(str(item) for item in result.get("failures") or [])
        total_checks += int(result.get("checks") or 0)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"json report: {args.json}")

    if all_failures:
        print(f"signed apk guard FAILED: {len(all_failures)} Fehler in {len(results)} APK(s)")
        return 1
    print(f"signed apk guard verified: {total_checks} checks, {len(results)} APK(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
