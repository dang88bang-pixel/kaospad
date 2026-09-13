"""Echter DEX-035-Builder ohne JDK/d8 -- REAL-IMPLEMENTATION 2026-09-12.

Hintergrund (Online-Alternativen-Evaluation): `d8`/`dx` brauchen eine JDK, die
weder per `apt` (keine Root-Rechte) noch per Adoptium-API (Netz gesperrt) zu
bekommen ist. Die DEX-Spezifikation ist jedoch vollständig dokumentiert und ein
minimales, *gueltiges* DEX ist wenige hundert Bytes gross. Dieses Modul
assembliert ein echtes DEX (Header, string/type/proto/method-Ids, class_def,
class_data, Code-Items mit realen Dalvik-Instruktionen, map_list, Adler-32-
Checksumme und SHA-1-Signatur) statt des bisherigen Platzhalters, der von
unabhaengigen Parsern mit `229 is not a valid TypeMapItem` abgelehnt wurde.

Enthaltene Klasse:
    public class MainActivity extends android.app.Activity {
        public static int nativeVersion() { return 5; }   // const/4 + return
        public MainActivity() { super(); }                // invoke-direct + return-void
    }

Abhaengigkeiten: nur Python-Standardbibliothek. Validierbar mit `androguard`
bzw. `lief` (beide via PyPI erreichbar) -- siehe `tests/dex_builder_test.py`.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from typing import Dict, List, Sequence, Tuple

DEX_MAGIC = b"dex\n035\x00"
ENDIAN_TAG = 0x12345678
HEADER_SIZE = 0x70
NO_INDEX = 0xFFFFFFFF

# access flags
ACC_PUBLIC = 0x0001
ACC_STATIC = 0x0008
ACC_SUPER = 0x0200
ACC_CONSTRUCTOR = 0x10000

# map item types
T_HEADER = 0x0000
T_STRING_ID = 0x0001
T_TYPE_ID = 0x0002
T_PROTO_ID = 0x0003
T_FIELD_ID = 0x0004
T_METHOD_ID = 0x0005
T_CLASS_DEF = 0x0006
T_MAP_LIST = 0x1000
T_CLASS_DATA = 0x2000
T_CODE_ITEM = 0x2001
T_STRING_DATA = 0x2002


def _uleb128(value: int) -> bytes:
    if value < 0:
        raise ValueError("uleb128 braucht einen nicht-negativen Wert")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _u16(value: int) -> bytes:
    return struct.pack("<H", value & 0xFFFF)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def _align4(data: bytes) -> bytes:
    pad = (-len(data)) % 4
    return data + b"\x00" * pad


def _mutf8(text: str) -> bytes:
    """MUTF-8: fuer den hier verwendeten ASCII-Bereich identisch zu UTF-8."""
    encoded = text.encode("utf-8")
    if b"\x00" in encoded:
        raise ValueError("MUTF-8 kodiert NUL als C0 80 -- Eingabe enthaelt NUL")
    return encoded


# --- Dalvik-Instruktionen (die wir wirklich emittieren) -----------------------

def ins_const4(reg: int, literal: int) -> int:
    """`const/4 vA, #+B` (Format 11n) als 16-Bit-Code-Unit."""
    if not 0 <= reg <= 15:
        raise ValueError("const/4: Register ausserhalb v0..v15")
    if not -8 <= literal <= 7:
        raise ValueError("const/4: Literal ausserhalb -8..7")
    return ((literal & 0xF) << 12) | (reg << 8) | 0x12


def ins_return(reg: int) -> int:
    """`return vAA` (Format 11x)."""
    return (reg << 8) | 0x0F


def ins_return_void() -> int:
    """`return-void` (Format 10x)."""
    return 0x0E


def ins_invoke_direct(reg: int, method_index: int) -> List[int]:
    """`invoke-direct {vC}, method@BBBB` (Format 35c) als drei Code-Units."""
    if not 0 <= reg <= 15:
        raise ValueError("invoke-direct: Register ausserhalb v0..v15")
    unit0 = (1 << 12) | (0 << 8) | 0x70          # A=1 Argument, G=0, op=0x70
    unit1 = method_index & 0xFFFF                # BBBB
    unit2 = reg & 0xF                            # C = erstes Argumentregister
    return [unit0, unit1, unit2]


def build_dex(
    class_name: str = "Lcom/kaoss/studio/MainActivity;",
    super_class: str = "Landroid/app/Activity;",
    static_method: str = "nativeVersion",
    static_return_value: int = 5,
) -> bytes:
    """Erzeugt ein gueltiges DEX-035 mit genau einer Klasse.

    Die Klasse erbt von ``super_class``, hat einen Konstruktor, der ``super()``
    aufruft, und eine statische Methode, die ``static_return_value`` liefert.
    """
    if not class_name.startswith("L") or not class_name.endswith(";"):
        raise ValueError("class_name muss ein DEX-Typdeskriptor sein (L…;)")
    if not super_class.startswith("L") or not super_class.endswith(";"):
        raise ValueError("super_class muss ein DEX-Typdeskriptor sein (L…;)")
    if not -8 <= static_return_value <= 7:
        raise ValueError("static_return_value muss in const/4 passen (-8..7)")

    # --- Zeichenketten (DEX verlangt Sortierung nach kodierten Bytes) ---------
    strings = sorted(
        {
            "<init>",            # Methodenname Konstruktor
            "I",                 # Shorty/Return-Typ int
            class_name,
            super_class,
            "V",                 # Shorty/Return-Typ void
            static_method,
        }
    )
    s_idx = {text: i for i, text in enumerate(strings)}

    # --- Typen (sortiert nach String-Index des Deskriptors) -------------------
    types = sorted({class_name, super_class, "I", "V"}, key=lambda t: s_idx[t])
    t_idx = {name: i for i, name in enumerate(types)}

    # --- Protos: ()I und ()V --------------------------------------------------
    protos: List[Tuple[int, int, int]] = [
        (s_idx["I"], t_idx["I"], 0),   # shorty "I", return int, keine Parameter
        (s_idx["V"], t_idx["V"], 0),   # shorty "V", return void, keine Parameter
    ]
    proto_of_return = {t_idx["I"]: 0, t_idx["V"]: 1}

    # --- Methoden (sortiert nach class_idx, proto_idx, name_idx) --------------
    method_rows = sorted(
        [
            (t_idx[super_class], proto_of_return[t_idx["V"]], s_idx["<init>"], "super_init"),
            (t_idx[class_name], proto_of_return[t_idx["I"]], s_idx[static_method], "static"),
            (t_idx[class_name], proto_of_return[t_idx["V"]], s_idx["<init>"], "ctor"),
        ]
    )
    m_idx = {row[3]: i for i, row in enumerate(method_rows)}

    # --- Layout berechnen -----------------------------------------------------
    string_ids_off = HEADER_SIZE
    type_ids_off = string_ids_off + 4 * len(strings)
    proto_ids_off = type_ids_off + 4 * len(types)
    method_ids_off = proto_ids_off + 12 * len(protos)
    class_defs_off = method_ids_off + 8 * len(method_rows)
    data_off = class_defs_off + 32

    body = bytearray()

    # string data items
    string_data_off = data_off + len(body)
    string_data_offsets = []
    for text in strings:
        string_data_offsets.append(data_off + len(body))
        raw = _mutf8(text)
        body += _uleb128(len(raw)) + raw + b"\x00"

    # code items (4-Byte-ausgerichtet)
    body += b"\x00" * ((-len(body)) % 4)

    def code_item(registers: int, ins: int, outs: int, insns: Sequence[int]) -> bytes:
        out = _u16(registers) + _u16(ins) + _u16(outs) + _u16(0)   # tries_size
        out += _u32(0)                                             # debug_info_off
        out += _u32(len(insns))                                    # insns_size
        out += b"".join(_u16(unit) for unit in insns)
        return out

    static_code_off = data_off + len(body)
    body += code_item(
        registers=1,
        ins=0,
        outs=0,
        insns=[ins_const4(0, static_return_value), ins_return(0)],
    )
    body += b"\x00" * ((-len(body)) % 4)

    ctor_code_off = data_off + len(body)
    body += code_item(
        registers=1,
        ins=1,
        outs=1,
        insns=ins_invoke_direct(0, m_idx["super_init"]) + [ins_return_void()],
    )
    body += b"\x00" * ((-len(body)) % 4)

    # class data item
    class_data_off = data_off + len(body)
    class_data = _uleb128(0) + _uleb128(0)          # static/instance fields
    class_data += _uleb128(2) + _uleb128(0)         # direct/virtual methods
    previous = 0
    for method_id, flags, code_off in (
        (m_idx["static"], ACC_PUBLIC | ACC_STATIC, static_code_off),
        (m_idx["ctor"], ACC_PUBLIC | ACC_CONSTRUCTOR, ctor_code_off),
    ):
        class_data += _uleb128(method_id - previous)
        previous = method_id
        class_data += _uleb128(flags)
        class_data += _uleb128(code_off)
    body += class_data
    body += b"\x00" * ((-len(body)) % 4)

    # map list
    map_off = data_off + len(body)
    map_items = sorted(
        [
            (T_HEADER, 1, 0),
            (T_STRING_ID, len(strings), string_ids_off),
            (T_TYPE_ID, len(types), type_ids_off),
            (T_PROTO_ID, len(protos), proto_ids_off),
            (T_METHOD_ID, len(method_rows), method_ids_off),
            (T_CLASS_DEF, 1, class_defs_off),
            (T_STRING_DATA, len(strings), string_data_off),
            (T_CODE_ITEM, 2, static_code_off),
            (T_CLASS_DATA, 1, class_data_off),
            (T_MAP_LIST, 1, map_off),
        ],
        key=lambda item: item[2],
    )
    body += _u32(len(map_items))
    for item_type, size, offset in map_items:
        body += _u16(item_type) + _u16(0) + _u32(size) + _u32(offset)

    # --- Id-Tabellen (liegen zwischen Header und Datenteil) -------------------
    ids = bytearray()
    ids += b"".join(_u32(off) for off in string_data_offsets)
    ids += b"".join(_u32(s_idx[name]) for name in types)
    for shorty_idx, return_type_idx, parameters_off in protos:
        ids += _u32(shorty_idx) + _u32(return_type_idx) + _u32(parameters_off)
    for class_idx, proto_idx, name_idx, _ in method_rows:
        ids += _u16(class_idx) + _u16(proto_idx) + _u32(name_idx)
    # class_def
    ids += (
        _u32(t_idx[class_name])
        + _u32(ACC_PUBLIC | ACC_SUPER)
        + _u32(t_idx[super_class])
        + _u32(0)                # interfaces_off
        + _u32(NO_INDEX)         # source_file_idx
        + _u32(0)                # annotations_off
        + _u32(class_data_off)
        + _u32(0)                # static_values_off
    )

    file_size = HEADER_SIZE + len(ids) + len(body)

    # --- Header ---------------------------------------------------------------
    header = bytearray(HEADER_SIZE)
    header[0:8] = DEX_MAGIC
    struct.pack_into("<I", header, 8, 0)                      # checksum (spaeter)
    header[12:32] = b"\x00" * 20                              # signature (spaeter)
    struct.pack_into("<I", header, 32, file_size)
    struct.pack_into("<I", header, 36, HEADER_SIZE)
    struct.pack_into("<I", header, 40, ENDIAN_TAG)
    struct.pack_into("<I", header, 44, 0)                     # link_size
    struct.pack_into("<I", header, 48, 0)                     # link_off
    struct.pack_into("<I", header, 52, map_off)
    struct.pack_into("<I", header, 56, len(strings))
    struct.pack_into("<I", header, 60, string_ids_off)
    struct.pack_into("<I", header, 64, len(types))
    struct.pack_into("<I", header, 68, type_ids_off)
    struct.pack_into("<I", header, 72, len(protos))
    struct.pack_into("<I", header, 76, proto_ids_off)
    struct.pack_into("<I", header, 80, 0)                     # field_ids_size
    struct.pack_into("<I", header, 84, 0)                     # field_ids_off
    struct.pack_into("<I", header, 88, len(method_rows))
    struct.pack_into("<I", header, 92, method_ids_off)
    struct.pack_into("<I", header, 96, 1)                     # class_defs_size
    struct.pack_into("<I", header, 100, class_defs_off)
    struct.pack_into("<I", header, 104, len(body))            # data_size
    struct.pack_into("<I", header, 108, data_off)

    blob = bytearray(header) + ids + body
    if len(blob) != file_size:
        raise RuntimeError(f"DEX-Layout inkonsistent: {len(blob)} != {file_size}")

    blob[12:32] = hashlib.sha1(bytes(blob[32:])).digest()      # signature (ab 0x0C)
    struct.pack_into("<I", blob, 8, zlib.adler32(bytes(blob[12:])) & 0xFFFFFFFF)
    return bytes(blob)


def validate_dex_structure(blob: bytes) -> Dict[str, object]:
    """Prueft Header, Pruefsummen und map_list -- ohne Fremdabhaengigkeit."""
    if len(blob) < HEADER_SIZE:
        raise ValueError("zu kurz fuer einen DEX-Header")
    if blob[:8] != DEX_MAGIC:
        raise ValueError("DEX-Magie fehlt")
    file_size = struct.unpack_from("<I", blob, 32)[0]
    if file_size != len(blob):
        raise ValueError(f"file_size {file_size} != {len(blob)}")
    if struct.unpack_from("<I", blob, 36)[0] != HEADER_SIZE:
        raise ValueError("header_size != 0x70")
    if struct.unpack_from("<I", blob, 40)[0] != ENDIAN_TAG:
        raise ValueError("endian_tag falsch")

    stored_checksum = struct.unpack_from("<I", blob, 8)[0]
    actual_checksum = zlib.adler32(bytes(blob[12:])) & 0xFFFFFFFF
    if stored_checksum != actual_checksum:
        raise ValueError(f"Adler-32 falsch: {stored_checksum:#x} != {actual_checksum:#x}")
    stored_sig = blob[12:32]
    actual_sig = hashlib.sha1(bytes(blob[32:])).digest()
    if stored_sig != actual_sig:
        raise ValueError("SHA-1-Signatur falsch")

    map_off = struct.unpack_from("<I", blob, 52)[0]
    map_size = struct.unpack_from("<I", blob, map_off)[0]
    seen_types = []
    for i in range(map_size):
        base = map_off + 4 + i * 12
        item_type, _unused, size, offset = struct.unpack_from("<HHII", blob, base)
        if not 0 <= offset < len(blob):
            raise ValueError(f"map-Eintrag {i} zeigt ausserhalb der Datei")
        seen_types.append(item_type)
    required = {T_HEADER, T_STRING_ID, T_TYPE_ID, T_PROTO_ID, T_METHOD_ID,
                T_CLASS_DEF, T_STRING_DATA, T_CODE_ITEM, T_CLASS_DATA, T_MAP_LIST}
    missing = required - set(seen_types)
    if missing:
        raise ValueError(f"map_list unvollstaendig: {sorted(missing)}")

    return {
        "ok": True,
        "file_size": file_size,
        "map_items": map_size,
        "string_ids": struct.unpack_from("<I", blob, 56)[0],
        "type_ids": struct.unpack_from("<I", blob, 64)[0],
        "proto_ids": struct.unpack_from("<I", blob, 72)[0],
        "method_ids": struct.unpack_from("<I", blob, 88)[0],
        "class_defs": struct.unpack_from("<I", blob, 96)[0],
        "data_size": struct.unpack_from("<I", blob, 104)[0],
        "map_types": seen_types,
        "sha1": stored_sig.hex(),
    }
