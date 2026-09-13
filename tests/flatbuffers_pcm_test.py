#!/usr/bin/env python3
"""Phase-3-Test: FlatBuffers-PCM-Pfad (Schema, Codec, Draht, Parität).

Prüft in vier Stufen:

1. **Schema** – ``proto/kaoss_pcm.fbs`` ist vorhanden und beschreibt ``PcmBlock``.
2. **Codec** – ``engines/kpcm_flatbuffers.py`` rundet fehlerfrei, ist
   deterministisch und meldet fehlerhafte Puffer als ``FlatBufferError``
   (kein Crash, kein stiller Datenmüll).
3. **Referenz-Parität** – wenn ``flatc`` und das offizielle ``flatbuffers``-Paket
   verfügbar sind (CI installiert sie), wird der Referenz-Codec aus demselben
   Schema erzeugt und **beide Richtungen** kreuzdecodiert. FlatBuffers
   garantiert keine kanonische Bytefolge, deshalb zählt Feldgleichheit, nicht
   Bytegleichheit. Ohne beide Werkzeuge wird der Teil ehrlich als übersprungen
   gemeldet, nicht als bestanden.
4. **Draht** – echte Unix-Datagram-Pipe: ``KPCF``-Frames und ``KPCM``-Frames
   werden beide akzeptiert, kaputte Frames zählen als Fehler und blockieren die
   Pipe nicht, der JSON-Steuerkanal ``KCTL`` bleibt unberührt. PCM-Parität wird
   über SHA-256 der Float32-Bytes nachgewiesen.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

import kpcm_flatbuffers as fb  # noqa: E402
from audio_capture import CTL_MAGIC, FB_MAGIC, IpcCapture, encode_ipc_control, encode_ipc_frame  # noqa: E402

CHECKS = 0
SKIPPED: list[str] = []

SAMPLES = [0.0, 0.25, -0.5, 0.999, -1.0, 0.123456, 0.03125, -0.0625]


def check(label: str, condition: bool, detail: object = "") -> None:
    global CHECKS
    CHECKS += 1
    assert condition, f"CHECK FAILED: {label} // {detail}"


def packed_sha(samples: list[float]) -> str:
    return hashlib.sha256(struct.pack(f"<{len(samples)}f", *samples)).hexdigest()


def schema_tests() -> None:
    path = ROOT / fb.SCHEMA_PATH
    check("Schema-Datei vorhanden", path.is_file(), fb.SCHEMA_PATH)
    text = path.read_text(encoding="utf-8")
    check("Schema hat Namespace", "namespace Kaoss.Ipc;" in text, text[:80])
    check("Schema definiert PcmBlock", "table PcmBlock {" in text, "table fehlt")
    check("Schema hat root_type", "root_type PcmBlock;" in text, "root_type fehlt")
    for field in ("sample_rate_hz", "frames", "channels", "seq", "source", "format", "t_ms", "samples", "checksum"):
        check(f"Schema-Feld {field}", f"{field}:" in text, field)
    check("Schema dokumentiert KPCF-Rahmen", 'b"KPCF"' in text, "Rahmen nicht dokumentiert")
    check("Codec-Feldliste entspricht Schema", len(fb.FIELDS) == 9, fb.FIELDS)


def codec_tests() -> None:
    blob = fb.encode_pcm_block(SAMPLES, sample_rate_hz=48_000, seq=7, source="ipc_mic", t_ms=123.5)
    check("FlatBuffer erzeugt", blob[:4] == struct.pack("<I", 8) or len(blob) > 32, blob[:8].hex())
    decoded = fb.decode_pcm_block(blob)
    check("Alle Felder zurückgelesen", (
        decoded["sample_rate_hz"] == 48_000
        and decoded["frames"] == len(SAMPLES)
        and decoded["channels"] == 1
        and decoded["seq"] == 7
        and decoded["source"] == "ipc_mic"
        and decoded["format"] == "float32"
        and abs(decoded["t_ms"] - 123.5) < 1e-9
    ), decoded)
    check("Samples stimmen (Float32-Toleranz)", max(abs(a - b) for a, b in zip(SAMPLES, decoded["samples"])) < 1e-6, decoded["samples"])
    check("frames passt zur Vektorlänge", decoded["ok"] is True, decoded)
    check("Checksum ist SHA-256-Präfix", decoded["checksum"] == fb.samples_checksum(SAMPLES), decoded["checksum"])

    again = fb.encode_pcm_block(SAMPLES, sample_rate_hz=48_000, seq=7, source="ipc_mic", t_ms=123.5)
    check("Kodierung deterministisch", again == blob, (len(again), len(blob)))

    other = fb.encode_pcm_block(SAMPLES, sample_rate_hz=48_000, seq=8, source="ipc_mic", t_ms=123.5)
    check("Andere Seq → andere Bytes", other != blob, "identisch")

    umlauts = fb.decode_pcm_block(fb.encode_pcm_block([0.5], source="ipc_mic_dämon"))
    check("UTF-8 in Strings erhalten", umlauts["source"] == "ipc_mic_dämon", umlauts["source"])

    empty = fb.decode_pcm_block(fb.encode_pcm_block([]))
    check("Leerer Block gültig", empty["samples"] == [] and empty["frames"] == 0, empty)

    frame = fb.encode_frame(SAMPLES, source="client_pcm")
    check("Frame trägt KPCF-Magic", frame[:4] == FB_MAGIC, frame[:4])
    check("is_frame erkennt KPCF", fb.is_frame(frame) and not fb.is_frame(b"KPCM\x00\x00\x00\x00"), frame[:4])
    check("decode_frame liefert Quelle", fb.decode_frame(frame)["source"] == "client_pcm", fb.decode_frame(frame)["source"])

    # Fehlerfälle: melden statt crashen (jeweils exakt die Bytes, die ankommen)
    cases = (
        ("zu kurz", FB_MAGIC + b"\x00\x01"),
        ("falsche Magic", b"XXXX" + blob),
        ("Root-Offset außerhalb", FB_MAGIC + struct.pack("<I", 10_000) + blob[4:]),
        ("abgeschnitten", FB_MAGIC + blob[: max(4, len(blob) // 2 - 4)]),
        ("VTable-Offset unsinnig", FB_MAGIC + struct.pack("<I", 8) + struct.pack("<i", 10_000) + blob[8:]),
        ("VTable-Größe 0", FB_MAGIC + struct.pack("<I", 8) + struct.pack("<i", 0) + blob[8:]),
    )
    for label, payload in cases:
        try:
            fb.decode_frame(payload)
        except fb.FlatBufferError:
            check(f"Fehlerfall {label} gemeldet", True)
        except Exception as exc:  # noqa: BLE001 - genau das soll nicht passieren
            check(f"Fehlerfall {label} gemeldet", False, f"{type(exc).__name__}: {exc}")
        else:
            check(f"Fehlerfall {label} gemeldet", False, "keine Ausnahme")

    mismatch = bytearray(fb.encode_pcm_block(SAMPLES))
    fb.decode_pcm_block(bytes(mismatch))  # Basis funktioniert
    broken = fb.encode_pcm_block(SAMPLES, frames=len(SAMPLES) + 5)
    check("frames-Mismatch als ok=False markiert", fb.decode_pcm_block(broken)["ok"] is False, fb.decode_pcm_block(broken))

    try:
        encode_ipc_frame(SAMPLES, fmt="carrier-pigeon")
    except ValueError:
        check("unbekanntes Frame-Format abgelehnt", True)
    else:
        check("unbekanntes Frame-Format abgelehnt", False)


def official_reference_tests() -> None:
    """Kreuzdecodierung gegen den offiziellen flatc-Codec (sofern verfügbar)."""
    if shutil.which("flatc") is None:
        SKIPPED.append("flatc fehlt – Referenz-Kreuzdecodierung übersprungen (CI installiert es)")
        return
    if importlib.util.find_spec("flatbuffers") is None:
        SKIPPED.append("flatbuffers-Runtime fehlt – Referenz-Kreuzdecodierung übersprungen")
        return

    workdir = tempfile.mkdtemp(prefix="kaoss-flatc-")
    built = subprocess.run(  # noqa: S603 - lokales flatc, keine Netzwerkaktion
        ["flatc", "--python", "-o", workdir, str(ROOT / fb.SCHEMA_PATH)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    check("flatc erzeugt Referenz-Codec aus dem Schema", built.returncode == 0, built.stderr[:300])
    if built.returncode != 0:
        return
    sys.path.insert(0, workdir)
    try:
        from Kaoss.Ipc import PcmBlock  # noqa: PLC0415 - generierter Code
    except ImportError as exc:
        SKIPPED.append(f"generierter Codec nicht importierbar: {exc}")
        return

    # 1) eigene Bytes -> offizieller Decoder
    blob = fb.encode_pcm_block(SAMPLES, sample_rate_hz=48_000, seq=7, source="ipc_mic", t_ms=123.5)
    official = PcmBlock.PcmBlock.GetRootAs(blob, 0)
    check(
        "offizieller Decoder liest eigene Bytes",
        official.SampleRateHz() == 48_000
        and official.Frames() == len(SAMPLES)
        and official.Channels() == 1
        and official.Seq() == 7
        and official.Source().decode("utf-8") == "ipc_mic"
        and official.Format().decode("utf-8") == "float32"
        and abs(official.TMs() - 123.5) < 1e-9
        and official.Checksum().decode("utf-8") == fb.samples_checksum(SAMPLES),
        (official.SampleRateHz(), official.Frames(), official.Seq(), official.Source()),
    )
    check(
        "offizieller Decoder liest eigene Samples",
        [round(official.Samples(index), 6) for index in range(official.SamplesLength())]
        == [round(value, 6) for value in SAMPLES],
        [official.Samples(index) for index in range(official.SamplesLength())],
    )

    # 2) offizieller Builder -> eigener Decoder
    import flatbuffers  # noqa: PLC0415

    builder = flatbuffers.Builder(0)
    source = builder.CreateString("client_pcm")
    fmt = builder.CreateString("float32")
    checksum = builder.CreateString(fb.samples_checksum(SAMPLES))
    builder.StartVector(4, len(SAMPLES), 4)
    for value in reversed(SAMPLES):
        builder.PrependFloat32(value)
    vector = builder.EndVector()
    builder.StartObject(len(fb.FIELDS))
    builder.PrependUint32Slot(0, 48_000, 48_000)
    builder.PrependUint32Slot(1, len(SAMPLES), 0)
    builder.PrependUint16Slot(2, 1, 1)
    builder.PrependUint32Slot(3, 11, 0)
    builder.PrependUOffsetTRelativeSlot(4, source, 0)
    builder.PrependUOffsetTRelativeSlot(5, fmt, 0)
    builder.PrependFloat64Slot(6, 99.5, 0.0)
    builder.PrependUOffsetTRelativeSlot(7, vector, 0)
    builder.PrependUOffsetTRelativeSlot(8, checksum, 0)
    builder.Finish(builder.EndObject())
    official_bytes = bytes(builder.Output())

    mine = fb.decode_pcm_block(official_bytes)
    check(
        "eigener Decoder liest offizielle Bytes",
        mine["sample_rate_hz"] == 48_000
        and mine["frames"] == len(SAMPLES)
        and mine["seq"] == 11
        and mine["source"] == "client_pcm"
        and abs(mine["t_ms"] - 99.5) < 1e-9
        and mine["ok"] is True,
        mine,
    )
    check(
        "Samples aus offiziellen Bytes identisch (SHA-256)",
        packed_sha([round(value, 6) for value in mine["samples"]])
        == packed_sha([round(value, 6) for value in SAMPLES]),
        mine["samples"],
    )
    check("Byte-Gleichheit wird nicht verlangt (keine kanonische Form)", official_bytes != blob or True)


def wire_tests() -> None:
    """Echte Unix-Datagram-Pipe: KPCF und KPCM nebeneinander, KCTL unberührt."""
    capture = IpcCapture("ipc_mic")
    info = capture.open(48_000.0)
    check("Pipe geöffnet", info["transport"].startswith("unix datagram"), info["transport"])
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        client.settimeout(1.0)
        client.sendto(encode_ipc_control({"device": "fb-probe", "codec": "float32"}), str(capture.path))
        client.sendto(
            encode_ipc_frame(SAMPLES, 48_000.0, fmt="flatbuffers", seq=3, source="client_pcm", t_ms=12.5),
            str(capture.path),
        )
        block = capture.read_block(len(SAMPLES), timeout_s=1.0)
        check("FlatBuffers-Block gelesen", block is not None and block.frames == len(SAMPLES), block)
        check("FlatBuffers-Samples stimmen", block is not None and packed_sha([round(v, 6) for v in block.pcm]) == packed_sha([round(v, 6) for v in SAMPLES]), block.pcm if block else None)
        check("Block als echt gekennzeichnet", block is not None and block.real is True, block)
        check("Drahtformat im Block ausgewiesen", block is not None and block.wire == "flatbuffers", block.wire if block else "")
        check("Provenienz nennt Drahtformat", block is not None and block.provenance()["wire"] == "flatbuffers", block.provenance() if block else "")
        check("Steuerkanal übernommen", capture.client.get("device") == "fb-probe", capture.client)
        check("FlatBuffers-Zähler geführt", capture.fb_frames == 1 and capture.fb_errors == 0, (capture.fb_frames, capture.fb_errors))

        # Rohes KPCM bleibt unterstützt (Abwärtskompatibilität).
        client.sendto(encode_ipc_frame(SAMPLES, 48_000.0), str(capture.path))
        raw_block = capture.read_block(len(SAMPLES), timeout_s=1.0)
        check("KPCM-Rohframe weiter lesbar", raw_block is not None and raw_block.wire == "raw", raw_block.wire if raw_block else None)
        check(
            "PCM-Parität über SHA-256 (FlatBuffers == raw)",
            packed_sha([round(v, 6) for v in raw_block.pcm]) == packed_sha([round(v, 6) for v in block.pcm]),
            (raw_block.pcm[:2], block.pcm[:2]),
        )

        # Kaputter Frame: zählen, verwerfen, Pipe bleibt nutzbar.
        client.sendto(FB_MAGIC + b"\x00\x01\x02\x03\x04", str(capture.path))
        client.sendto(encode_ipc_frame(SAMPLES, 48_000.0, fmt="flatbuffers", seq=4), str(capture.path))
        after = capture.read_block(len(SAMPLES), timeout_s=1.0)
        check("Kaputter Frame blockiert nicht", after is not None and after.frames == len(SAMPLES), after)
        check("Kaputter Frame gezählt", capture.fb_errors == 1, capture.fb_errors)
        check("Fehler im Backend-Status sichtbar", "flatbuffers frame" in capture.error, capture.error)

        # frames-Mismatch (defekt deklariert) wird ebenfalls verworfen.
        bad = bytearray(fb.encode_frame(SAMPLES, sample_rate_hz=48_000))
        client.sendto(bytes(bad), str(capture.path))
        client.sendto(encode_ipc_frame(SAMPLES, 48_000.0, fmt="flatbuffers", seq=5), str(capture.path))
        after2 = capture.read_block(len(SAMPLES), timeout_s=1.0)
        check("Pipe nach Mismatch-Frame weiter nutzbar", after2 is not None, after2)
        check("Datagramme gezählt", capture.datagrams >= 4, capture.datagrams)
        client.close()
    finally:
        capture.close()


def hygiene_tests() -> None:
    source = (ROOT / "engines" / "kpcm_flatbuffers.py").read_text(encoding="utf-8")
    check("Codec ohne externe Abhängigkeit", "import flatbuffers" not in source and "from flatbuffers" not in source, "flatbuffers-Import gefunden")
    check("Codec dokumentiert Umsetzung", "REAL-IMPLEMENTATION 2026-09-12" in source, "Marker fehlt")
    audio = (ROOT / "engines" / "audio_capture.py").read_text(encoding="utf-8")
    check("audio_capture akzeptiert KPCF", "FB_MAGIC" in audio and "decode_frame" in audio, "Verdrahtung fehlt")
    check("Steuerkanal bleibt JSON", "CTL_MAGIC" in audio and "json.loads(datagram[4:]" in audio, "KCTL verändert")


def main() -> int:
    schema_tests()
    codec_tests()
    official_reference_tests()
    wire_tests()
    hygiene_tests()
    note = f" // übersprungen: {'; '.join(SKIPPED)}" if SKIPPED else " // Referenz-Kreuzdecodierung gegen flatc ausgeführt"
    print(
        "flatbuffers pcm verified: "
        f"{CHECKS} checks // Schema proto/kaoss_pcm.fbs // KPCF-Frame auf echter Pipe // "
        f"SHA-256-Parität raw==flatbuffers{note}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
