#!/usr/bin/env python3
"""FlatBuffers-Codec für die KPCM-PCM-Pfade – ohne externe Abhängigkeit.

-- REAL-IMPLEMENTATION 2026-09-12 (Audit Phase 3)

Schema: ``proto/kaoss_pcm.fbs`` (``Kaoss.Ipc.PcmBlock``). Rahmen auf dem Draht:

    b"KPCF" | <FlatBuffer-Puffer, little-endian>

Warum hier ein eigener Codec steht: Das Repo bleibt abhängigkeitsfrei
(Zero-Cloud, lauffähig ohne ``pip install``). Die **Gültigkeit** wird nicht
behauptet, sondern geprüft – ``tests/flatbuffers_pcm_test.py`` erzeugt mit dem
offiziellen ``flatc`` aus demselben Schema den Referenz-Codec und kreuzdecodiert
beide Richtungen (eigene Bytes → offizieller Decoder und umgekehrt). FlatBuffers
garantiert keine kanonische Bytefolge, deshalb ist Byte-Gleichheit kein
Kriterium – Wohlgeformtheit und Feldgleichheit sind es.

Implementiert ist genau die Teilmenge des Formats, die ``PcmBlock`` braucht:
eine Tabelle mit VTable, vorzeichenlose Ganzzahlen, ``double``, Strings und ein
``[float]``-Vektor. Little-endian, Ausrichtung gemäß Spezifikation.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Any, Sequence

FRAME_MAGIC = b"KPCF"
SCHEMA_PATH = "proto/kaoss_pcm.fbs"

#: Felder in Deklarationsreihenfolge des Schemas (= VTable-Slots).
FIELDS: tuple[tuple[str, str], ...] = (
    ("sample_rate_hz", "uint32"),
    ("frames", "uint32"),
    ("channels", "uint16"),
    ("seq", "uint32"),
    ("source", "string"),
    ("format", "string"),
    ("t_ms", "double"),
    ("samples", "vector_float32"),
    ("checksum", "string"),
)

DEFAULTS: dict[str, Any] = {
    "sample_rate_hz": 48_000,
    "frames": 0,
    "channels": 1,
    "seq": 0,
    "source": "",
    "format": "float32",
    "t_ms": 0.0,
    "samples": [],
    "checksum": "",
}

#: Feste Feldpositionen innerhalb des Tabellenkörpers (siehe ``_layout``).
_LAYOUT = {
    "soffset": 0,
    "sample_rate_hz": 4,
    "frames": 8,
    "seq": 12,
    "t_ms": 16,
    "channels": 24,
    "source": 28,
    "format": 32,
    "samples": 36,
    "checksum": 40,
}
OBJECT_SIZE = 44


class FlatBufferError(ValueError):
    """Puffer ist kein wohlgeformter FlatBuffer (oder kein ``PcmBlock``)."""


def samples_checksum(samples: Sequence[float]) -> str:
    """SHA-256 über die little-endian-Float32-Samples, erste 16 Hex-Zeichen."""
    packed = struct.pack(f"<{len(samples)}f", *[float(value) for value in samples]) if samples else b""
    return hashlib.sha256(packed).hexdigest()[:16]


def _align(buf: bytearray, alignment: int) -> None:
    pad = (-len(buf)) % alignment
    if pad:
        buf.extend(b"\x00" * pad)


def _encode_string(buf: bytearray, value: str) -> int:
    _align(buf, 4)
    start = len(buf)
    data = value.encode("utf-8")
    buf.extend(struct.pack("<I", len(data)))
    buf.extend(data)
    buf.append(0)  # FlatBuffers-Strings sind nullterminiert (zählt nicht zur Länge)
    return start


def _encode_float_vector(buf: bytearray, values: Sequence[float]) -> int:
    _align(buf, 4)
    start = len(buf)
    buf.extend(struct.pack("<I", len(values)))
    if values:
        buf.extend(struct.pack(f"<{len(values)}f", *[float(value) for value in values]))
    return start


def encode_pcm_block(
    samples: Sequence[float],
    *,
    sample_rate_hz: int = 48_000,
    frames: int | None = None,
    channels: int = 1,
    seq: int = 0,
    source: str = "",
    fmt: str = "float32",
    t_ms: float = 0.0,
    checksum: str | None = None,
) -> bytes:
    """Baut den ``PcmBlock``-FlatBuffer (ohne Rahmen-Magic)."""
    values = [float(value) for value in samples]
    payload = {
        "sample_rate_hz": int(sample_rate_hz),
        "frames": int(len(values) if frames is None else frames),
        "channels": int(channels),
        "seq": int(seq),
        "source": str(source),
        "format": str(fmt),
        "t_ms": float(t_ms),
        "samples": values,
        "checksum": samples_checksum(values) if checksum is None else str(checksum),
    }

    vtable_size = 4 + 2 * len(FIELDS)
    vtable_padded = (vtable_size + 7) & ~7  # VTable auf 8 Byte auffüllen → Tabelle bleibt 8-ausgerichtet
    # VTable-Slots in Deklarationsreihenfolge des Schemas.
    vtable_slots = tuple(_LAYOUT[name] for name, _kind in FIELDS)

    buf = bytearray(b"\x00\x00\x00\x00")  # Platz für den Root-Offset
    # VTable *vor* der Tabelle, damit der soffset positiv bleibt.
    _align(buf, 8)
    vtable_start = len(buf)
    buf.extend(b"\x00" * vtable_padded)
    vtable_head = vtable_start
    table_start = len(buf)

    # Tabellenkörper mit fester Feldlage.
    _align(buf, 8)
    if len(buf) != table_start:
        raise FlatBufferError(f"Layout-Fehler: Tabelle bei {len(buf)}, erwartet {table_start}")
    body = bytearray(OBJECT_SIZE)
    struct.pack_into("<i", body, _LAYOUT["soffset"], table_start - vtable_start)
    struct.pack_into("<I", body, _LAYOUT["sample_rate_hz"], payload["sample_rate_hz"])
    struct.pack_into("<I", body, _LAYOUT["frames"], payload["frames"])
    struct.pack_into("<I", body, _LAYOUT["seq"], payload["seq"])
    struct.pack_into("<d", body, _LAYOUT["t_ms"], payload["t_ms"])
    struct.pack_into("<H", body, _LAYOUT["channels"], payload["channels"])
    buf.extend(body)

    # Kinder (Strings/Vektor) hinter der Tabelle; uoffsets zeigen nach vorn.
    for name, kind in FIELDS:
        if kind not in {"string", "vector_float32"}:
            continue
        if kind == "string":
            child = _encode_string(buf, payload[name])
        else:
            child = _encode_float_vector(buf, payload[name])
        field_pos = table_start + _LAYOUT[name]
        struct.pack_into("<I", buf, field_pos, child - field_pos)

    struct.pack_into("<I", buf, 0, table_start)

    # VTable schreiben (Größe, Objektgröße, Feldpositionen).
    struct.pack_into("<H", buf, vtable_head, vtable_size)
    struct.pack_into("<H", buf, vtable_head + 2, OBJECT_SIZE)
    for index, offset in enumerate(vtable_slots):
        struct.pack_into("<H", buf, vtable_head + 4 + 2 * index, offset)
    return bytes(buf)


def encode_frame(
    samples: Sequence[float],
    **kwargs: Any,
) -> bytes:
    """Komplettes Datagramm: ``b"KPCF"`` + FlatBuffer."""
    return FRAME_MAGIC + encode_pcm_block(samples, **kwargs)


def decode_pcm_block(data: bytes) -> dict[str, Any]:
    """Liest einen ``PcmBlock`` – auch aus fremden (offiziellen) Buildern."""
    buf = data
    if len(buf) < 8:
        raise FlatBufferError(f"Puffer zu kurz: {len(buf)} Bytes")
    root_offset = struct.unpack_from("<I", buf, 0)[0]
    if root_offset + 4 > len(buf):
        raise FlatBufferError(f"Root-Offset {root_offset} außerhalb des Puffers ({len(buf)} B)")
    table = root_offset
    soffset = struct.unpack_from("<i", buf, table)[0]
    vtable = table - soffset
    if vtable < 0 or vtable + 4 > len(buf):
        raise FlatBufferError(f"VTable-Offset {vtable} ungültig")
    vtable_size, object_size = struct.unpack_from("<HH", buf, vtable)
    if vtable_size < 4 or vtable + vtable_size > len(buf):
        raise FlatBufferError(f"VTable-Größe {vtable_size} ungültig")
    if object_size == 0:
        raise FlatBufferError("Objektgröße 0 – kein PcmBlock")

    def slot(index: int) -> int:
        position = vtable + 4 + 2 * index
        if index >= (vtable_size - 4) // 2 or position + 2 > len(buf):
            return 0
        return struct.unpack_from("<H", buf, position)[0]

    def read_scalar(index: int, code: str, size: int, default: Any) -> Any:
        offset = slot(index)
        if offset == 0 or table + offset + size > len(buf):
            return default
        return struct.unpack_from(code, buf, table + offset)[0]

    def read_bytes_at(index: int, element_size: int = 1) -> bytes | None:
        """Liest String/Vektor. ``length`` ist die *Elementzahl*, nicht die Bytezahl."""
        offset = slot(index)
        if offset == 0:
            return None
        field_pos = table + offset
        if field_pos + 4 > len(buf):
            raise FlatBufferError("Feldposition außerhalb des Puffers")
        target = field_pos + struct.unpack_from("<I", buf, field_pos)[0]
        if target + 4 > len(buf):
            raise FlatBufferError("uoffset außerhalb des Puffers")
        length = struct.unpack_from("<I", buf, target)[0]
        start = target + 4
        end = start + length * element_size
        if end > len(buf):
            raise FlatBufferError(f"Vektorlänge {length} (Elementgröße {element_size}) außerhalb des Puffers")
        return buf[start:end]

    result: dict[str, Any] = {}
    for index, (name, kind) in enumerate(FIELDS):
        if kind == "uint32":
            result[name] = int(read_scalar(index, "<I", 4, DEFAULTS[name]))
        elif kind == "uint16":
            result[name] = int(read_scalar(index, "<H", 2, DEFAULTS[name]))
        elif kind == "double":
            result[name] = float(read_scalar(index, "<d", 8, DEFAULTS[name]))
        elif kind == "string":
            raw = read_bytes_at(index)
            result[name] = raw.decode("utf-8", "replace") if raw is not None else DEFAULTS[name]
        elif kind == "vector_float32":
            raw = read_bytes_at(index, element_size=4)
            if raw is None:
                result[name] = list(DEFAULTS[name])
            else:
                count = len(raw) // 4
                result[name] = list(struct.unpack(f"<{count}f", raw[: count * 4])) if count else []
        else:  # pragma: no cover - Schema kennt keine weiteren Typen
            raise FlatBufferError(f"unbekannter Feldtyp {kind}")

    result["frames_declared"] = result["frames"]
    result["ok"] = result["frames"] == 0 or result["frames"] == len(result["samples"])
    return result


def decode_frame(data: bytes) -> dict[str, Any]:
    """Prüft die ``KPCF``-Magic und decodiert den Block."""
    if not data.startswith(FRAME_MAGIC):
        raise FlatBufferError(f"Frame-Magic fehlt (erwartet {FRAME_MAGIC!r}, gesehen {data[:4]!r})")
    return decode_pcm_block(data[len(FRAME_MAGIC) :])


def is_frame(data: bytes) -> bool:
    """Erkennung am 4-Byte-Präfix (für den Multiplexer in ``audio_capture``)."""
    return data[:4] == FRAME_MAGIC
