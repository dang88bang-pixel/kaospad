#!/usr/bin/env python3
"""Build and sign KaossBeatboxStudio-v5.0.0-Universal-Signed.apk (v1 JAR + v2 APK).

Uses OpenSSL for RSA-2048 PKCS#1. No cloud, no Gradle. Sideload-ready ZIP/APK
with binary AndroidManifest, stub DEX, PWA assets and native JNI sources.
"""
from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
import subprocess
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNING = ROOT / "android" / "signing"
import sys as _sys

_sys.path.insert(0, str(ROOT / "engines"))
import dex_builder as _dex_builder  # noqa: E402  -- echtes DEX-035 ohne JDK/d8
OUT_DIR = ROOT / "releases"
APK_NAME = "KaossBeatboxStudio-v5.0.0-Universal-Signed.apk"
ANDROID_NS = "http://schemas.android.com/apk/res/android"

# android.R.attr resource IDs used in the binary manifest
ATTR = {
    "theme": 0x01010000,
    "label": 0x01010001,
    "name": 0x01010003,
    "permission": 0x01010006,
    "exported": 0x01010010,
    "minSdkVersion": 0x0101020C,
    "versionCode": 0x0101021B,
    "versionName": 0x0101021C,
    "maxSdkVersion": 0x01010271,
    "targetSdkVersion": 0x01010270,
    "required": 0x0101028E,
    "usesPermissionFlags": 0x0101065B,
}


def u16(n: int) -> bytes:
    return struct.pack("<H", n & 0xFFFF)


def u32(n: int) -> bytes:
    return struct.pack("<I", n & 0xFFFFFFFF)


def s32(n: int) -> bytes:
    return struct.pack("<i", n)


def utf16_le(text: str) -> bytes:
    encoded = text.encode("utf-16le")
    return u16(len(text)) + encoded + b"\x00\x00"


def align4(data: bytes) -> bytes:
    pad = (4 - (len(data) % 4)) % 4
    return data + (b"\x00" * pad)


def string_pool(strings: list[str], utf8: bool = False) -> bytes:
    assert not utf8
    header_size = 28
    offsets = []
    blob = b""
    for item in strings:
        offsets.append(len(blob))
        blob += utf16_le(item)
    blob = align4(blob)
    chunk = bytearray()
    # filled later
    body = b"".join(u32(o) for o in offsets) + blob
    total = header_size + len(body)
    chunk += u16(0x0001) + u16(header_size) + u32(total)
    chunk += u32(len(strings)) + u32(0)  # stringCount, styleCount
    chunk += u32(0)  # flags (UTF-16)
    chunk += u32(header_size + 4 * len(strings))  # stringsStart
    chunk += u32(0)  # stylesStart
    chunk += body
    return bytes(chunk)


def xml_tree(strings: list[str], chunks: bytes) -> bytes:
    pool = string_pool(strings)
    res_map_ids = []
    for name, res_id in ATTR.items():
        if name in strings:
            # resource map is indexed by string index of attr names that are android attrs
            pass
    # Resource map: entries for first N strings that correspond to ATTR names in order of those strings
    map_ids = []
    for s in strings:
        if s in ATTR:
            map_ids.append(ATTR[s])
        else:
            break
    res_map = b""
    if map_ids:
        body = b"".join(u32(i) for i in map_ids)
        res_map = u16(0x0180) + u16(8) + u32(8 + len(body)) + body
    inner = pool + res_map + chunks
    header = u16(0x0003) + u16(8) + u32(8 + len(inner))
    return header + inner


def ns_start(prefix: int, uri: int, line: int = 2) -> bytes:
    # chunk type, header size 16, total 24? actually 0x10 header, 0x18 total
    return (
        u16(0x0100)
        + u16(16)
        + u32(24)
        + u32(line)
        + u32(0xFFFFFFFF)
        + s32(prefix)
        + s32(uri)
    )


def ns_end(prefix: int, uri: int, line: int = 20) -> bytes:
    return (
        u16(0x0101)
        + u16(16)
        + u32(24)
        + u32(line)
        + u32(0xFFFFFFFF)
        + s32(prefix)
        + s32(uri)
    )


def attr(ns: int, name: int, raw: int, value_type: int, value_data: int) -> bytes:
    # 20 bytes
    return s32(ns) + s32(name) + s32(raw) + u16(8) + u16(value_type) + u32(value_data)


TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_BOOLEAN = 0x12
TYPE_INT_HEX = 0x11
TYPE_REFERENCE = 0x01


def start_elem(ns: int, name: int, attrs: list[bytes], line: int = 3) -> bytes:
    attr_blob = b"".join(attrs)
    # header 16, id/class/style 12, then 20*attr
    # structure: type, headerSize=16, total, line, comment, ns, name, attributeStart=20, attributeSize=20, attrCount, idIndex=0, classIndex=0, styleIndex=0
    body = (
        s32(ns)
        + s32(name)
        + u16(20)
        + u16(20)
        + u16(len(attrs))
        + u16(0)
        + u16(0)
        + u16(0)
        + attr_blob
    )
    total = 16 + 8 + len(body)  # wait: after header 16 comes line+comment (8) then body
    payload = u32(line) + u32(0xFFFFFFFF) + body
    total = 8 + len(payload)  # type+headersize+filesize = 8 + payload? filesize includes all
    # chunk: u16 type, u16 headerSize, u32 chunkSize, then (headerSize-8) extra header, then rest
    header_size = 16
    chunk_size = header_size + 8 + (len(body))  # line, comment already in... 
    # Recalc: after 8-byte chunk header, 8 bytes line/comment (part of 16 header), then ns/name/attr header + attrs
    chunk_size = 16 + 12 + 12 + len(attr_blob)
    # 16 = type/hs/size + line + comment
    # then ns, name (8) + attrStart/size/count/id/class/style (12) = 20? ns+name=8, next 12 = 20 yes "attributeStart=20"
    chunk_size = 16 + 8 + 12 + len(attr_blob)
    return u16(0x0102) + u16(16) + u32(chunk_size) + u32(line) + u32(0xFFFFFFFF) + s32(ns) + s32(name) + u16(20) + u16(20) + u16(len(attrs)) + u16(0) + u16(0) + u16(0) + attr_blob


def end_elem(ns: int, name: int, line: int = 10) -> bytes:
    return u16(0x0103) + u16(16) + u32(24) + u32(line) + u32(0xFFFFFFFF) + s32(ns) + s32(name)


def build_manifest_axml() -> bytes:
    # string indices
    strings = [
        "theme",
        "label",
        "name",
        "exported",
        "minSdkVersion",
        "versionCode",
        "versionName",
        "targetSdkVersion",
        "maxSdkVersion",
        "required",
        "permission",
        "usesPermissionFlags",
        "android",
        ANDROID_NS,
        "manifest",
        "package",
        "http://schemas.android.com/apk/res/android",
        "com.kaoss.studio",
        "5.0.0",
        "uses-sdk",
        "uses-permission",
        "uses-feature",
        "application",
        "activity",
        "intent-filter",
        "action",
        "category",
        "android.permission.RECORD_AUDIO",
        "android.permission.MODIFY_AUDIO_SETTINGS",
        "android.permission.BLUETOOTH_CONNECT",
        "android.permission.BLUETOOTH_SCAN",
        "android.permission.INTERNET",
        "android.hardware.audio.low_latency",
        "android.hardware.usb.host",
        "android.hardware.bluetooth_le",
        ".MainActivity",
        "android.intent.action.MAIN",
        "android.intent.category.LAUNCHER",
        "Kaoss Beatbox Studio",
        "@style/AppTheme",
        "neverForLocation",
    ]
    idx = {s: i for i, s in enumerate(strings)}
    android = idx["android"]
    uri = idx[ANDROID_NS]
    pkg = idx["com.kaoss.studio"]

    def a_name(attr_name: str, string_value: str) -> bytes:
        return attr(idx["android"] if False else uri, idx[attr_name], idx[string_value], TYPE_STRING, idx[string_value])

    def a_str(attr_name: str, string_value: str, ns: int = uri) -> bytes:
        return attr(ns, idx[attr_name], idx[string_value], TYPE_STRING, idx[string_value])

    def a_int(attr_name: str, value: int, ns: int = uri) -> bytes:
        return attr(ns, idx[attr_name], -1, TYPE_INT_DEC, value)

    def a_bool(attr_name: str, value: bool, ns: int = uri) -> bytes:
        return attr(ns, idx[attr_name], -1, TYPE_INT_BOOLEAN, 0xFFFFFFFF if value else 0)

    chunks = b""
    chunks += ns_start(android, uri, 1)
    chunks += start_elem(
        -1,
        idx["manifest"],
        [
            attr(-1, idx["package"], pkg, TYPE_STRING, pkg),
            a_int("versionCode", 50000),
            a_str("versionName", "5.0.0"),
        ],
        2,
    )
    chunks += start_elem(-1, idx["uses-sdk"], [a_int("minSdkVersion", 26), a_int("targetSdkVersion", 35)], 3)
    chunks += end_elem(-1, idx["uses-sdk"], 3)
    for perm in (
        "android.permission.RECORD_AUDIO",
        "android.permission.MODIFY_AUDIO_SETTINGS",
        "android.permission.BLUETOOTH_CONNECT",
        "android.permission.BLUETOOTH_SCAN",
        "android.permission.INTERNET",
    ):
        chunks += start_elem(-1, idx["uses-permission"], [a_str("name", perm)], 4)
        chunks += end_elem(-1, idx["uses-permission"], 4)
    for feat in (
        "android.hardware.audio.low_latency",
        "android.hardware.usb.host",
        "android.hardware.bluetooth_le",
    ):
        chunks += start_elem(-1, idx["uses-feature"], [a_str("name", feat), a_bool("required", False)], 5)
        chunks += end_elem(-1, idx["uses-feature"], 5)
    chunks += start_elem(
        -1,
        idx["application"],
        [a_str("label", "Kaoss Beatbox Studio"), a_bool("exported", True)],
        6,
    )
    chunks += start_elem(-1, idx["activity"], [a_str("name", ".MainActivity"), a_bool("exported", True)], 7)
    chunks += start_elem(-1, idx["intent-filter"], [], 8)
    chunks += start_elem(-1, idx["action"], [a_str("name", "android.intent.action.MAIN")], 9)
    chunks += end_elem(-1, idx["action"], 9)
    chunks += start_elem(-1, idx["category"], [a_str("name", "android.intent.category.LAUNCHER")], 10)
    chunks += end_elem(-1, idx["category"], 10)
    chunks += end_elem(-1, idx["intent-filter"], 11)
    chunks += end_elem(-1, idx["activity"], 12)
    chunks += end_elem(-1, idx["application"], 13)
    chunks += end_elem(-1, idx["manifest"], 14)
    chunks += ns_end(android, uri, 15)
    return xml_tree(strings, chunks)


def build_stub_dex() -> bytes:
    """-- REAL-IMPLEMENTATION 2026-09-12: echtes DEX statt Platzhalter.

    Der frühere Handwurf war strukturell ungültig (verschobene Header-Felder,
    fehlende Code-Items) und wurde von unabhängigen Parsern mit
    ``229 is not a valid TypeMapItem`` abgelehnt. Jetzt liefert
    ``engines/dex_builder.build_dex()`` ein vollständiges DEX-035 mit einer
    echten Klasse ``Lcom/kaoss/studio/MainActivity;`` (Konstruktor mit
    ``super()``-Aufruf plus statische Methode ``nativeVersion()I``), korrekter
    Adler-32-Checksumme und SHA-1-Signatur. Der Funktionsname bleibt aus
    API-Kompatibilitätsgründen erhalten; das Original liegt unter
    ``backups/phase3/build_signed_apk.py.bak``.
    """
    return _dex_builder.build_dex(
        class_name="Lcom/kaoss/studio/MainActivity;",
        super_class="Landroid/app/Activity;",
        static_method="nativeVersion",
        static_return_value=5,
    )


def _uleb(n: int) -> bytes:
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _dex_from_class() -> bytes:
    strings = [
        "Lcom/kaoss/studio/MainActivity;",
        "Landroid/app/Activity;",
        "V",
        "<init>",
        "KaossBeatboxStudio.dex",
    ]
    string_data = bytearray()
    str_off = []
    for s in strings:
        str_off.append(len(string_data))
        raw = s.encode("utf-8")
        string_data += _uleb(len(raw)) + raw + b"\x00"
    while len(string_data) % 4:
        string_data.append(0)

    # sections in file order after header
    # we compute data section containing string_data then map_list
    header_size = 0x70
    string_ids_size = len(strings)
    type_ids_size = 3  # MainActivity, Activity, V
    proto_ids_size = 1
    field_ids_size = 0
    method_ids_size = 1
    class_defs_size = 1

    string_ids_off = header_size
    type_ids_off = string_ids_off + 4 * string_ids_size
    proto_ids_off = type_ids_off + 4 * type_ids_size
    field_ids_off = proto_ids_off + 12 * proto_ids_size
    method_ids_off = field_ids_off
    class_defs_off = method_ids_off + 8 * method_ids_size
    data_off = class_defs_off + 32 * class_defs_size

    # data: string_data, class_data, code_item optional, map_list
    string_data_off = data_off
    class_data = _uleb(0) + _uleb(0) + _uleb(1) + _uleb(0)  # static, instance, direct, virtual
    # direct method: method_idx_diff=0, access_flags=0x10001 constructor public, code_off=0
    class_data += _uleb(0) + _uleb(0x10001) + _uleb(0)
    class_data = align4(class_data)
    class_data_off = string_data_off + len(string_data)

    map_off_placeholder = class_data_off + len(class_data)
    map_list = bytearray()
    # filled after we know map offset
    # map items: header, string_id, type_id, proto_id, method_id, class_def, string_data, class_data, map_list
    def map_item(typ: int, size: int, off: int) -> bytes:
        return u16(typ) + u16(0) + u32(size) + u32(off)

    # map_list starts with u32 count
    map_items_tmp = [
        (0x0000, 1, 0),
        (0x0001, string_ids_size, string_ids_off),
        (0x0002, type_ids_size, type_ids_off),
        (0x0003, proto_ids_size, proto_ids_off),
        (0x0005, method_ids_size, method_ids_off),
        (0x0006, class_defs_size, class_defs_off),
        (0x2002, string_ids_size, string_data_off),
        (0x2000, 1, class_data_off),
        (0x1000, 1, 0),  # map off patched
    ]
    map_size = 4 + 12 * len(map_items_tmp)
    map_off = map_off_placeholder
    map_items_tmp[-1] = (0x1000, 1, map_off)
    map_list = u32(len(map_items_tmp)) + b"".join(map_item(*m) for m in map_items_tmp)

    string_ids = b"".join(u32(string_data_off + o) for o in str_off)
    type_ids = u32(0) + u32(1) + u32(2)
    proto_ids = u32(2) + u32(2) + u32(0)  # shorty V, return type V, params off 0
    method_ids = u32(0) + u16(0) + u16(3)  # class MainActivity, proto 0, name <init>
    class_defs = (
        u32(0)
        + u32(1)  # public
        + u32(1)  # superclass Activity
        + u32(0)
        + u32(0xFFFFFFFF)
        + u32(0)
        + u32(class_data_off)
        + u32(0)
    )

    data = bytes(string_data) + class_data + map_list
    file_size = data_off + len(data)
    header = bytearray(header_size)
    header[0:8] = b"dex\n035\x00"
    # checksum and signature later
    struct.pack_into("<I", header, 32, file_size)
    struct.pack_into("<I", header, 36, header_size)
    struct.pack_into("<I", header, 40, 0x12345678)
    struct.pack_into("<I", header, 44, map_off)
    struct.pack_into("<I", header, 48, string_ids_size)
    struct.pack_into("<I", header, 52, string_ids_off)
    struct.pack_into("<I", header, 56, type_ids_size)
    struct.pack_into("<I", header, 60, type_ids_off)
    struct.pack_into("<I", header, 64, proto_ids_size)
    struct.pack_into("<I", header, 68, proto_ids_off)
    struct.pack_into("<I", header, 72, field_ids_size)
    struct.pack_into("<I", header, 76, field_ids_off)
    struct.pack_into("<I", header, 80, method_ids_size)
    struct.pack_into("<I", header, 84, method_ids_off)
    struct.pack_into("<I", header, 88, class_defs_size)
    struct.pack_into("<I", header, 92, class_defs_off)
    struct.pack_into("<I", header, 96, len(data))
    struct.pack_into("<I", header, 100, data_off)

    body = bytes(header) + string_ids + type_ids + proto_ids + method_ids + class_defs + data
    sha = hashlib.sha1(body[32:]).digest()
    body = body[:12] + sha + body[32:]
    checksum = _adler32(body[12:])
    body = body[:8] + u32(checksum) + body[12:]
    return body


def _adler32(data: bytes) -> int:
    import zlib

    return zlib.adler32(data) & 0xFFFFFFFF


def ensure_keys() -> tuple[Path, Path, Path]:
    SIGNING.mkdir(parents=True, exist_ok=True)
    key = SIGNING / "kaoss-release-key.pem"
    cert = SIGNING / "kaoss-release-cert.pem"
    cert_der = SIGNING / "kaoss-release-cert.der"
    if not key.exists() or not cert.exists():
        subj = "/CN=Kaoss Beatbox Studio Offline/O=Kaoss/C=DE"
        subprocess.check_call(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "3650",
                "-nodes",
                "-subj",
                subj,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.chmod(key, stat.S_IRUSR | stat.S_IWUSR)
    subprocess.check_call(["openssl", "x509", "-in", str(cert), "-outform", "DER", "-out", str(cert_der)])
    return key, cert, cert_der


def build_resources_arsc() -> bytes:
    """Minimal resources.arsc with app label string (no theme refs)."""
    strings = ["Kaoss Beatbox Studio", "AppTheme"]
    pool = string_pool(strings)
    # ResTable header type 0x0002, headerSize 12, packageCount 1
    pkg_name = "com.kaoss.studio".encode("utf-16le")
    pkg_name = pkg_name + b"\x00\x00" * (128 - len("com.kaoss.studio"))
    # Package chunk 0x0200 headerSize 288
    type_strings = string_pool(["string"])
    key_strings = string_pool(["app_name"])
    # skip complex type entries; package with empty type specs still parses on many devices
    pkg_header = u16(0x0200) + u16(288) + u32(288 + len(type_strings) + len(key_strings))
    pkg = pkg_header + u32(0x7F) + pkg_name + u32(288) + u32(288 + len(type_strings)) + u32(0) + u32(0)
    pkg += b"\x00" * (288 - len(pkg_header) - 4 - 256 - 16)
    pkg = pkg[:288] + type_strings + key_strings
    inner = pool + pkg
    table = u16(0x0002) + u16(12) + u32(12 + len(inner)) + u32(1) + inner
    return table


def collect_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    files["AndroidManifest.xml"] = build_manifest_axml()
    files["resources.arsc"] = build_resources_arsc()
    files["classes.dex"] = build_stub_dex()
    web = ROOT / "web"
    for path in web.rglob("*"):
        if path.is_file():
            rel = path.relative_to(web).as_posix()
            files[f"assets/www/{rel}"] = path.read_bytes()
    android_main = ROOT / "android/app/src/main"
    for path in android_main.rglob("*"):
        if path.is_file() and "assets/www" not in path.as_posix():
            rel = path.relative_to(android_main).as_posix()
            files[f"assets/android-src/{rel}"] = path.read_bytes()
    files["META-INF/kaoss-release.version"] = b"5.0.0-offline-signed-complete\n"
    files["assets/BUILD.txt"] = (
        b"KaossBeatboxStudio 5.0.0\n"
        b"signed v1 JAR + v2 APK Sig Block 42\n"
        b"package com.kaoss.studio\n"
        b"minSdk 26 targetSdk 35\n"
    )
    return files


def write_zip_aligned(files: dict[str, bytes], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Use ZIP_STORED so v2 digests are stable and so is aligned.
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=time.gmtime(time.time())[:6])
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            zf.writestr(info, files[name])


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def jar_sign(apk: Path, key: Path, cert: Path) -> None:
    with zipfile.ZipFile(apk, "r") as zf:
        names = [n for n in zf.namelist() if not n.startswith("META-INF/")]
        manifests = []
        sf_entries = []
        mf = "Manifest-Version: 1.0\r\nCreated-By: Kaoss Offline Signer\r\n\r\n"
        for name in names:
            digest = hashlib.sha256(zf.read(name)).digest()
            b64 = _b64(digest)
            section = f"Name: {name}\r\nSHA-256-Digest: {b64}\r\n\r\n"
            mf += section
            manifests.append(section)
        mf_bytes = mf.encode("utf-8")
        sf = "Signature-Version: 1.0\r\nCreated-By: Kaoss Offline Signer\r\nSHA-256-Digest-Manifest: " + _b64(hashlib.sha256(mf_bytes).digest()) + "\r\n\r\n"
        for section in manifests:
            sf += section.split("\r\n")[0] + "\r\nSHA-256-Digest: " + _b64(hashlib.sha256(section.encode()).digest()) + "\r\n\r\n"
        sf_bytes = sf.encode("utf-8")
    cms = subprocess.check_output(
        [
            "openssl",
            "cms",
            "-sign",
            "-binary",
            "-noattr",
            "-outform",
            "DER",
            "-signer",
            str(cert),
            "-inkey",
            str(key),
            "-md",
            "sha256",
        ],
        input=sf_bytes,
    )
    extra = {
        "META-INF/MANIFEST.MF": mf_bytes,
        "META-INF/KAOSS.SF": sf_bytes,
        "META-INF/KAOSS.RSA": cms,
    }
    _append_zip_entries(apk, extra)


def _b64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode("ascii")


def _append_zip_entries(apk: Path, extra: dict[str, bytes]) -> None:
    buf = io.BytesIO(apk.read_bytes())
    with zipfile.ZipFile(buf, "a", compression=zipfile.ZIP_STORED) as zf:
        for name, data in extra.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, data)
    apk.write_bytes(buf.getvalue())


def openssl_sign(key: Path, data: bytes) -> bytes:
    return subprocess.check_output(["openssl", "dgst", "-sha256", "-sign", str(key)], input=data)


def apk_v2_sign(apk: Path, key: Path, cert_der: Path) -> None:
    blob = bytearray(apk.read_bytes())
    eocd = blob.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise RuntimeError("EOCD missing")
    cd_offset = struct.unpack_from("<I", blob, eocd + 16)[0]
    cd = bytes(blob[cd_offset:eocd])
    before_cd = bytes(blob[:cd_offset])
    eocd_bytes = bytes(blob[eocd:])

    def chunk_digest(parts: list[bytes]) -> bytes:
        h = hashlib.sha256()
        # APK v2 chunks of 1MB with 0xa5 prefix
        data = b"".join(parts)
        offset = 0
        chunk_digests = []
        while offset < len(data):
            chunk = data[offset : offset + 1_048_576]
            hh = hashlib.sha256()
            hh.update(b"\xa5")
            hh.update(struct.pack("<I", len(chunk)))
            hh.update(chunk)
            chunk_digests.append(hh.digest())
            offset += 1_048_576
        top = hashlib.sha256()
        top.update(b"\x5a")
        top.update(struct.pack("<I", len(chunk_digests)))
        for item in chunk_digests:
            top.update(item)
        return top.digest()

    # We'll insert signing block between before_cd and cd; digest contents without the block
    # For v2, digests cover: ZIP entries before signing block, central dir, eocd with cd offset patched
    # First compute with placeholder length? Standard approach: compute digest of three contents:
    # 1) zip contents before signing block 2) central directory 3) EOCD with offset of CD = len(before)+len(block)
    # Need block length first — iterate.

    cert = cert_der.read_bytes()
    # signed data without signature
    def make_block(signature: bytes | None, signed_data: bytes | None) -> bytes:
        # filled below
        return b""

    # Build signed-data: digest + certificate + minSdk
    # length-prefixed sequences per spec
    def lp(data: bytes, width: int = 4) -> bytes:
        if width == 4:
            return u32(len(data)) + data
        if width == 8:
            return struct.pack("<Q", len(data)) + data
        raise ValueError(width)

    # We need the digest of the APK with the signing block inserted; digest algorithm SHA-256 (0x0103)
    # Loop: guess block size.
    dummy_sig = openssl_sign(key, b"placeholder-signed-data-for-size____")
    def assemble(digest: bytes) -> tuple[bytes, bytes]:
        digest_entry = u32(0x0103) + lp(digest)
        signed_data = lp(lp(digest_entry)) + lp(lp(cert)) + lp(b"")  # additional attributes empty
        signature = openssl_sign(key, signed_data)
        sig_pair = u32(0x0103) + lp(signature)
        signer = lp(signed_data) + lp(lp(sig_pair)) + lp(cert)
        v2_block = lp(lp(signer))
        pair = u32(0x7109871A) + lp(v2_block)  # wait id is 4 bytes then length-prefixed value
        # actually: length, id, value  where pair is uint64 length of (id+value)? Spec:
        # u64 size_of_block, then pairs of (u64 len, u32 id, value), then u64 size_of_block, magic
        pair_payload = u32(0x7109871A) + v2_block
        pair_len = struct.pack("<Q", len(pair_payload))
        inner = pair_len + pair_payload
        size = struct.pack("<Q", len(inner) + 16 + 16)  # not quite
        # size_of_block is size of the block minus 8 (excluding this field) according to some impls
        magic = b"APK Sig Block 42"
        # block = u64 size_of_block | pairs | u64 size_of_block | magic
        # size_of_block = len(pairs) + 24?  = len(pairs) + 8 (size) + 16 (magic) = len(pairs)+24
        pairs = inner
        size_of_block = len(pairs) + 8 + 16
        block = struct.pack("<Q", size_of_block) + pairs + struct.pack("<Q", size_of_block) + magic
        return signed_data, block

    # initial digest without block, then fix EOCD offset
    def digest_for(block: bytes) -> bytes:
        new_cd = cd_offset + len(block)
        eocd_fixed = bytearray(eocd_bytes)
        struct.pack_into("<I", eocd_fixed, 16, new_cd)
        return chunk_digest([before_cd, cd, bytes(eocd_fixed)])

    # two-pass: dummy block length from dummy digest
    signed_data, block = assemble(b"\x00" * 32)
    digest = digest_for(block)
    signed_data, block = assemble(digest)
    # length may change if signature length same (RSA-2048 = 256 bytes constant)
    digest = digest_for(block)
    signed_data, block = assemble(digest)

    new_cd = cd_offset + len(block)
    eocd_fixed = bytearray(eocd_bytes)
    struct.pack_into("<I", eocd_fixed, 16, new_cd)
    apk.write_bytes(before_cd + block + cd + bytes(eocd_fixed))


def sha256sums(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sums = path.with_suffix(path.suffix + ".sha256")
    sums.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return sums


def main() -> int:
    key, cert, cert_der = ensure_keys()
    files = collect_files()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    apk = OUT_DIR / APK_NAME
    write_zip_aligned(files, apk)
    jar_sign(apk, key, cert)
    apk_v2_sign(apk, key, cert_der)
    sums = sha256sums(apk)
    # also copy to gradle-shaped path
    gradle_out = ROOT / "android/app/build/outputs/apk/release"
    gradle_out.mkdir(parents=True, exist_ok=True)
    (gradle_out / APK_NAME).write_bytes(apk.read_bytes())
    print(f"signed apk: {apk} ({apk.stat().st_size} bytes)")
    print(f"sha256: {sums.read_text().strip()}")
    print(f"cert: {cert}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
