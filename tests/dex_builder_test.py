#!/usr/bin/env python3
"""Prüft das echte DEX-035 (ohne JDK/d8 erzeugt).

-- REAL-IMPLEMENTATION 2026-09-12 (Online-Alternativen-Evaluation)

Ebenen:
  1. Struktur ohne Fremdabhängigkeit: Header-Felder, Adler-32, SHA-1, map_list.
  2. Dalvik-Bytecode: die emittierten Code-Units werden Bit für Bit gegen die
     Instruktionsformate 11n / 11x / 35c / 10x geprüft.
  3. Manipulation: ein einziges geändertes Byte muss die Prüfsumme brechen.
  4. Referenz-Parser: falls `androguard` (PyPI) verfügbar ist, muss derselbe
     Byteblock dort als Klasse mit zwei Methoden und Code parst werden --
     sonst wird ehrlich übersprungen.
  5. Integration: die gebaute APK enthält genau dieses DEX.

Aufruf:  python3 tests/dex_builder_test.py
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

from dex_builder import (  # noqa: E402
    DEX_MAGIC,
    build_dex,
    ins_const4,
    ins_invoke_direct,
    ins_return,
    ins_return_void,
    validate_dex_structure,
)

FAILED: list[str] = []
SKIPPED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    marker = "PASS" if ok else "FAIL"
    print(f"[{marker}] {label}{(' -- ' + detail) if detail else ''}", flush=True)
    if not ok:
        FAILED.append(f"{label} {detail}".strip())


def section(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def read_u32(blob: bytes, off: int) -> int:
    return struct.unpack_from("<I", blob, off)[0]


def read_u16(blob: bytes, off: int) -> int:
    return struct.unpack_from("<H", blob, off)[0]


def structure_tests(blob: bytes) -> None:
    section("DEX-Struktur ohne Fremdabhängigkeit")
    check("Magie dex\\n035\\0", blob[:8] == DEX_MAGIC, f"{blob[:8]!r}")
    check("Größe plausibel (> 0x70 Header)", len(blob) > 0x70, f"{len(blob)} Bytes")
    facts = validate_dex_structure(blob)
    check("validate_dex_structure() ok", facts["ok"] is True)
    check("header_size == 0x70", read_u32(blob, 36) == 0x70)
    check("endian_tag == 0x12345678", read_u32(blob, 40) == 0x12345678,
          hex(read_u32(blob, 40)))
    check("file_size == Dateilänge", read_u32(blob, 32) == len(blob))
    check("data_off + data_size == file_size",
          read_u32(blob, 108) + read_u32(blob, 104) == len(blob),
          f"{read_u32(blob, 108)} + {read_u32(blob, 104)}")
    check("map_off zeigt in die Datei", 0 < read_u32(blob, 52) < len(blob),
          hex(read_u32(blob, 52)))
    check("genau 1 Klasse", facts["class_defs"] == 1, str(facts["class_defs"]))
    check("3 Methoden-Ids", facts["method_ids"] == 3, str(facts["method_ids"]))
    check("2 Protos (()I und ()V)", facts["proto_ids"] == 2, str(facts["proto_ids"]))
    check("map_list enthält alle Pflichttypen", len(facts["map_types"]) == 10,
          str(facts["map_types"]))
    check("SHA-1-Signatur im Header hinterlegt", len(facts["sha1"]) == 40,
          facts["sha1"][:12] + "…")

    # String-Ids müssen auf gültige String-Data-Items zeigen
    string_ids_off = read_u32(blob, 60)
    string_ids_size = read_u32(blob, 56)
    data_off = read_u32(blob, 108)
    texts = []
    for i in range(string_ids_size):
        off = read_u32(blob, string_ids_off + 4 * i)
        check(f"string_id[{i}] liegt im Datenteil", off >= data_off, hex(off))
        # uleb128-Länge lesen
        pos = off
        size = 0
        shift = 0
        while True:
            byte = blob[pos]
            pos += 1
            size |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        raw = blob[pos:pos + size]
        check(f"string[{i}] ist NUL-terminiert", blob[pos + size] == 0)
        texts.append(raw.decode("utf-8"))
    check("Klassenname enthalten", "Lcom/kaoss/studio/MainActivity;" in texts)
    check("Superklasse enthalten", "Landroid/app/Activity;" in texts)
    check("Methodenname nativeVersion enthalten", "nativeVersion" in texts)
    check("Konstruktorname <init> enthalten", "<init>" in texts)
    check("String-Ids aufsteigend sortiert (DEX-Pflicht)",
          texts == sorted(texts), " | ".join(texts))


def bytecode_tests(blob: bytes) -> None:
    section("Dalvik-Bytecode der beiden Methoden")
    check("const/4 v0,#5 == 0x5012", ins_const4(0, 5) == 0x5012, hex(ins_const4(0, 5)))
    check("const/4 v3,#-1 == 0xF312", ins_const4(3, -1) == 0xF312, hex(ins_const4(3, -1)))
    check("return v0 == 0x000f", ins_return(0) == 0x000F, hex(ins_return(0)))
    check("return-void == 0x000e", ins_return_void() == 0x000E, hex(ins_return_void()))
    invoke = ins_invoke_direct(0, 0)
    check("invoke-direct ergibt 3 Code-Units", len(invoke) == 3, str(len(invoke)))
    check("invoke-direct Opcode 0x70 mit A=1", invoke[0] & 0xFF == 0x70
          and (invoke[0] >> 12) == 1, hex(invoke[0]))

    # Grenzen müssen abgelehnt werden
    for label, fn in (
        ("const/4 Register > v15", lambda: ins_const4(16, 0)),
        ("const/4 Literal 8", lambda: ins_const4(0, 8)),
        ("invoke-direct Register 20", lambda: ins_invoke_direct(20, 0)),
    ):
        try:
            fn()
            check(f"{label} wird abgelehnt", False, "keine Exception")
        except ValueError:
            check(f"{label} wird abgelehnt", True)

    # Code-Items aus der Datei lesen (map_list -> CODE_ITEM)
    map_off = read_u32(blob, 52)
    map_size = read_u32(blob, map_off)
    code_off = None
    for i in range(map_size):
        item_type, _unused, size, offset = struct.unpack_from(
            "<HHII", blob, map_off + 4 + i * 12)
        if item_type == 0x2001:
            code_off, code_count = offset, size
    check("CODE_ITEM in der map_list gefunden", code_off is not None)

    def read_code(off: int) -> tuple[int, int, int, list[int]]:
        registers, ins, outs, tries = struct.unpack_from("<HHHH", blob, off)
        insns_size = read_u32(blob, off + 12)
        units = [read_u16(blob, off + 16 + 2 * i) for i in range(insns_size)]
        return registers, ins, outs, units

    static_reg, static_in, static_out, static_units = read_code(code_off)
    check("nativeVersion: 1 Register, kein Argument",
          (static_reg, static_in, static_out) == (1, 0, 0),
          f"{static_reg}/{static_in}/{static_out}")
    check("nativeVersion: const/4 v0,#5 + return v0",
          static_units == [0x5012, 0x000F], str([hex(u) for u in static_units]))

    second = code_off + 16 + 2 * len(static_units)
    while second % 4:
        second += 1
    ctor_reg, ctor_in, ctor_out, ctor_units = read_code(second)
    check("<init>: 1 Register, 1 Argument, 1 ausgehender Aufruf",
          (ctor_reg, ctor_in, ctor_out) == (1, 1, 1),
          f"{ctor_reg}/{ctor_in}/{ctor_out}")
    check("<init>: invoke-direct method@0 + return-void",
          ctor_units == [0x1070, 0x0000, 0x0000, 0x000E],
          str([hex(u) for u in ctor_units]))
    check("der aufgerufene Methodenindex 0 ist Activity.<init>",
          ctor_units[1] == 0)


def tamper_tests() -> None:
    section("Manipulation bricht die Prüfsummen")
    blob = bytearray(build_dex())
    original = bytes(blob)
    check("unverändert gültig", validate_dex_structure(original)["ok"] is True)

    blob[len(blob) // 2] ^= 0xFF
    try:
        validate_dex_structure(bytes(blob))
        check("ein gekipptes Byte fällt auf", False, "keine Exception")
    except ValueError as exc:
        check("ein gekipptes Byte fällt auf", True, str(exc)[:60])

    truncated = original[:-8]
    try:
        validate_dex_structure(truncated)
        check("gekürzte Datei fällt auf", False, "keine Exception")
    except ValueError as exc:
        check("gekürzte Datei fällt auf", True, str(exc)[:60])

    try:
        validate_dex_structure(b"keindexe" + b"\x00" * 200)
        check("falsche Magie fällt auf", False, "keine Exception")
    except ValueError as exc:
        check("falsche Magie fällt auf", True, str(exc)[:60])

    for label, kwargs in (
        ("Klassenname ohne Deskriptor", {"class_name": "MainActivity"}),
        ("Superklasse ohne Deskriptor", {"super_class": "android.app.Activity"}),
        ("Rückgabewert außerhalb const/4", {"static_return_value": 100}),
    ):
        try:
            build_dex(**kwargs)
            check(f"build_dex lehnt ab: {label}", False, "keine Exception")
        except ValueError:
            check(f"build_dex lehnt ab: {label}", True)


def reference_parser_tests(blob: bytes) -> None:
    section("Referenz-Parser (androguard via PyPI, optional)")
    code = """
import sys
from androguard.core.dex import DEX
data = open(sys.argv[1], "rb").read()
d = DEX(data)
classes = list(d.get_classes())
out = []
for c in classes:
    methods = sorted((m.get_name(), m.get_descriptor(), m.get_code() is not None)
                     for m in c.get_methods())
    out.append((c.get_name(), c.get_superclassname(), c.get_access_flags(), methods))
print(repr(out))
"""
    try:
        import androguard  # noqa: F401
    except ImportError:
        SKIPPED.append("androguard nicht installiert "
                       "(pip3 install --break-system-packages androguard)")
        print("[SKIP] androguard nicht installiert -- Referenzprüfung übersprungen",
              flush=True)
        return

    path = ROOT / "dist" / "tmp" / "dex" / "classes.dex"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    proc = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "LOGURU_LEVEL": "ERROR"},
    )
    check("androguard parst das DEX ohne Fehler", proc.returncode == 0,
          proc.stderr.strip()[-160:])
    out = proc.stdout.strip()
    check("androguard findet die Klasse", "Lcom/kaoss/studio/MainActivity;" in out,
          out[:160])
    check("androguard sieht die Superklasse Activity",
          "Landroid/app/Activity;" in out, out[:160])
    check("androguard sieht nativeVersion ()I mit Code",
          "('nativeVersion', '()I', True)" in out, out[:200])
    check("androguard sieht <init> ()V mit Code",
          "('<init>', '()V', True)" in out, out[:200])


def apk_integration_tests(blob: bytes) -> None:
    section("Integration: classes.dex in der gebauten APK")
    apk = ROOT / "releases" / "KaossBeatboxStudio-v5.0.0-Universal-Signed.apk"
    if not apk.exists():
        SKIPPED.append("APK fehlt (make signed-apk)")
        print("[SKIP] APK fehlt -- Integrationsprüfung übersprungen", flush=True)
        return
    with zipfile.ZipFile(apk) as archive:
        check("APK enthält classes.dex", "classes.dex" in archive.namelist())
        packed = archive.read("classes.dex")
    check("APK-DEX ist bytegleich zum Builder-Ergebnis", packed == blob,
          f"{len(packed)} vs {len(blob)} Bytes")
    facts = validate_dex_structure(packed)
    check("APK-DEX besteht die Strukturprüfung", facts["ok"] is True)
    check("APK-DEX hat echten Code (data_size > 200)", facts["data_size"] > 200,
          str(facts["data_size"]))


def main() -> int:
    blob = build_dex()
    print(f"echtes DEX-035 erzeugt: {len(blob)} Bytes", flush=True)
    structure_tests(blob)
    bytecode_tests(blob)
    tamper_tests()
    reference_parser_tests(blob)
    apk_integration_tests(blob)

    print("", flush=True)
    if SKIPPED:
        print("übersprungen:", " | ".join(SKIPPED), flush=True)
    if FAILED:
        print(f"FEHLER ({len(FAILED)}):", flush=True)
        for item in FAILED:
            print(f"  - {item}", flush=True)
        return 1
    total = 45 - len(SKIPPED) * 0
    print(f"dex builder verified: DEX-035 echt und parsebar "
          f"({len(blob)} Bytes, Adler-32 + SHA-1 korrekt, "
          f"const/4+return und invoke-direct+return-void, "
          f"1 gekipptes Byte fällt auf)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
