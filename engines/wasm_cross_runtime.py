#!/usr/bin/env python3
"""Zweite, unabhängige WASM-Laufzeit (wasmtime) für den Paritätsbeweis.

-- REAL-IMPLEMENTATION 2026-09-12 (Online-Alternativen-Evaluation)

Hintergrund: `emcc` bleibt unerreichbar (`storage.googleapis.com` gesperrt), das
WASM-Modul wird mit `ziglang` gebaut. Die bestehende 4-Wege-Parität
(`tests/dsp_wasm_parity_test.mjs`) führt dieses Modul **nur in Node/V8** aus.
`wasmtime` kommt per PyPI (✅ erreichbar) und ist eine vollständig unabhängige
Laufzeit — wenn dasselbe `dist/wasm/kaoss_dsp.wasm` dort dieselben Zahlen
liefert, ist belegt, dass das Modul nicht an V8-Eigenheiten hängt.

Dieses Modul lädt die Vektoren aus ``dist/parity/vectors.bin`` und rechnet
dasselbe JSON-Layout wie ``scripts/dsp_parity_vectors.py`` — nur eben in
wasmtime statt in Python, Node oder dem nativen Binary.

Abhängigkeit: ``wasmtime`` (optional). Fehlt es, meldet :func:`availability`
das ehrlich; der Produktcode importiert wasmtime nie.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
WASM_PATH = ROOT / "dist" / "wasm" / "kaoss_dsp.wasm"
VECTORS_PATH = ROOT / "dist" / "parity" / "vectors.bin"

VECTOR_MAGIC = b"KVEC"   # wie in scripts/dsp_parity_vectors.py
VECTOR_VERSION = 1


class WasmRuntimeUnavailable(RuntimeError):
    """wasmtime oder das WASM-Modul ist nicht verfügbar."""


def availability() -> Dict[str, object]:
    """Ehrlicher Verfügbarkeitsbericht -- wirft nie."""
    try:
        import wasmtime  # noqa: F401
    except Exception as exc:
        return {
            "ok": False,
            "runtime": "wasmtime",
            "reason": f"{type(exc).__name__}: {exc}",
            "hint": "pip3 install --break-system-packages wasmtime",
        }
    version = getattr(wasmtime, "__version__", None)
    if version is None:
        try:
            from importlib.metadata import version as _pkg_version

            version = _pkg_version("wasmtime")
        except Exception:
            version = "unbekannt"
    if not WASM_PATH.exists():
        return {
            "ok": False,
            "runtime": "wasmtime",
            "version": version,
            "reason": f"WASM-Modul fehlt: {WASM_PATH} (make wasm)",
        }
    return {
        "ok": True,
        "runtime": "wasmtime",
        "version": version,
        "module": str(WASM_PATH.relative_to(ROOT)),
        "module_bytes": WASM_PATH.stat().st_size,
    }


def read_vectors(path: Path | None = None) -> List[Dict[str, Any]]:
    """Liest ``vectors.bin`` (Format von ``scripts/dsp_parity_vectors.py``)."""
    source = path or VECTORS_PATH
    raw = source.read_bytes()
    if raw[:4] != VECTOR_MAGIC:
        raise ValueError(f"bad vector magic: {raw[:4]!r}")
    version, cases = struct.unpack_from("<II", raw, 4)
    if version != VECTOR_VERSION:
        raise ValueError(f"unsupported vector version {version}")
    offset = 12
    vectors: List[Dict[str, Any]] = []
    for _ in range(cases):
        (name_len,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        name = raw[offset:offset + name_len].decode("utf-8")
        offset += name_len
        rate = struct.unpack_from("<d", raw, offset)[0]
        offset += 8
        (frames,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        pcm = list(struct.unpack_from(f"<{frames}f", raw, offset))
        offset += frames * 4
        xy = list(struct.unpack_from("<8f", raw, offset))
        offset += 32
        (s808_frames,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        s808_ms = struct.unpack_from("<d", raw, offset)[0]
        offset += 8
        vectors.append({
            "name": name,
            "rate": rate,
            "frames": frames,
            "pcm": pcm,
            "xy": xy,
            "s808_frames": s808_frames,
            "s808_ms": s808_ms,
        })
    return vectors


class WasmtimeDsp:
    """Dünne Fassade über die Kaoss-DSP-ABI in wasmtime."""

    def __init__(self, module_path: Path | None = None) -> None:
        status = availability()
        if not status["ok"]:
            raise WasmRuntimeUnavailable(str(status["reason"]))
        from wasmtime import Engine, Linker, Module, Store, WasiConfig

        self.status = status
        self._engine = Engine()
        self._store = Store(self._engine)
        self._store.set_wasi(WasiConfig())
        self._module = Module.from_file(self._engine, str(module_path or WASM_PATH))
        linker = Linker(self._engine)
        linker.define_wasi()
        instance = linker.instantiate(self._store, self._module)
        self.exports = instance.exports(self._store)
        self._memory = self.exports["memory"]
        self.abi = int(self.exports["kaoss_dsp_abi_version"](self._store))
        self.limiter_dbfs = float(self.exports["kaoss_dsp_limiter_dbfs"](self._store))
        self.quad = int(self.exports["kaoss_quad_create"](self._store))

    # -- Speicherverwaltung ---------------------------------------------------
    def _malloc(self, count: int) -> int:
        ptr = int(self.exports["malloc"](self._store, count))
        if not ptr:
            raise MemoryError("kaoss_dsp.wasm malloc lieferte 0")
        return ptr

    def _free(self, ptr: int) -> None:
        self.exports["free"](self._store, ptr)

    # wasmtime: read(store, start, stop) mit *absolutem* stop; write(store, bytes, start).
    _ELEMENT_SIZE = {"B": 1, "f": 4, "d": 8}

    def _view(self, ptr: int, count: int, fmt: str) -> List[float]:
        size = self._ELEMENT_SIZE[fmt]
        raw = bytes(self._memory.read(self._store, ptr, ptr + count * size))
        if len(raw) != count * size:
            raise MemoryError(
                f"Speicherlesen lieferte {len(raw)} statt {count * size} Bytes")
        return list(struct.unpack(f"<{count}{fmt}", raw))

    def _write_floats(self, ptr: int, values: Sequence[float]) -> None:
        payload = struct.pack(f"<{len(values)}f", *values)
        self._memory.write(self._store, payload, ptr)

    def close(self) -> None:
        if self.quad:
            self.exports["kaoss_quad_destroy"](self._store, self.quad)
            self.quad = 0

    # -- ABI-Aufrufe ----------------------------------------------------------
    def brickwall_buffer(self, pcm: Sequence[float]) -> List[float]:
        count = len(pcm)
        src = self._malloc(count * 4)
        out = self._malloc(count * 4)
        try:
            self._write_floats(src, pcm)
            self.exports["kaoss_dsp_brickwall_buffer"](
                self._store, src, out, count, float(self.limiter_dbfs))
            return self._view(out, count, "f")
        finally:
            self._free(src)
            self._free(out)

    def peak_dbfs(self, pcm: Sequence[float]) -> float:
        count = len(pcm)
        ptr = self._malloc(count * 4)
        try:
            self._write_floats(ptr, pcm)
            return float(self.exports["kaoss_dsp_peak_dbfs"](self._store, ptr, count))
        finally:
            self._free(ptr)

    def brickwall_sample(self, sample: float) -> float:
        return float(self.exports["kaoss_dsp_brickwall_sample"](
            self._store, float(sample), float(self.limiter_dbfs)))

    def checksum(self, pcm: Sequence[float]) -> str:
        count = len(pcm)
        ptr = self._malloc(count * 4)
        try:
            self._write_floats(ptr, pcm)
            digest = int(self.exports["kaoss_dsp_checksum"](self._store, ptr, count))
            return f"{digest & 0xFFFFFFFFFFFFFFFF:016x}"
        finally:
            self._free(ptr)

    def detect_transient(self, pcm: Sequence[float], rate: float) -> Dict[str, float]:
        count = len(pcm)
        src = self._malloc(count * 4)
        out = self._malloc(3 * 8)
        try:
            self._write_floats(src, pcm)
            self.exports["kaoss_dsp_detect_transient"](
                self._store, src, count, float(rate), out)
            view = self._view(out, 3, "d")
            return {
                "kind_id": int(view[0]),
                "frequency_hz": float(view[1]),
                "detection_latency_ms": float(view[2]),
            }
        finally:
            self._free(src)
            self._free(out)

    def synthesize_808(self, rate: float, duration_ms: float, frames: int) -> List[float]:
        want = max(1, int(frames))
        out = self._malloc(want * 4)
        try:
            written = int(self.exports["kaoss_dsp_synthesize_808"](
                self._store, out, want, float(rate), float(duration_ms), 1))
            values = self._view(out, want, "f")
            return values[:max(written, 0)]
        finally:
            self._free(out)

    def set_xy(self, module: int, x: float, y: float) -> bool:
        return int(self.exports["kaoss_quad_set_xy"](
            self._store, self.quad, int(module), float(x), float(y))) == 1

    def process(self, pcm: Sequence[float]) -> List[float]:
        count = len(pcm)
        src = self._malloc(count * 4)
        out = self._malloc(count * 4)
        try:
            self._write_floats(src, pcm)
            self.exports["kaoss_quad_process"](self._store, self.quad, src, out, count)
            return self._view(out, count, "f")
        finally:
            self._free(src)
            self._free(out)

    def state(self) -> Dict[str, Any]:
        xy_ptr = self._malloc(8 * 4)
        frozen_ptr = self._malloc(4)
        bpm_ptr = self._malloc(4)
        try:
            self.exports["kaoss_quad_read_state"](
                self._store, self.quad, xy_ptr, frozen_ptr, bpm_ptr)
            return {
                "xy": self._view(xy_ptr, 8, "f"),
                "frozen": [int(v) for v in self._view(frozen_ptr, 4, "B")],
                "bpm": self._view(bpm_ptr, 1, "f")[0],
            }
        finally:
            self._free(xy_ptr)
            self._free(frozen_ptr)
            self._free(bpm_ptr)


def run_parity(vectors: Sequence[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """Führt alle Vektorfälle in wasmtime aus (JSON-Layout wie die übrigen Läufe)."""
    cases_in = list(vectors) if vectors is not None else read_vectors()
    dsp = WasmtimeDsp()
    cases: List[Dict[str, Any]] = []
    try:
        for vector in cases_in:
            pcm = [float(v) for v in vector["pcm"]]
            rate = float(vector["rate"])
            limited = dsp.brickwall_buffer(pcm)
            transient = dsp.detect_transient(pcm, rate)
            synth = dsp.synthesize_808(rate, float(vector["s808_ms"]),
                                       int(vector["s808_frames"]))
            synth += [0.0] * (int(vector["s808_frames"]) - len(synth))

            # frische Kette pro Fall, damit die Quad-Zustände nicht übersprechen
            dsp.exports["kaoss_quad_destroy"](dsp._store, dsp.quad)
            dsp.quad = int(dsp.exports["kaoss_quad_create"](dsp._store))
            xy = [float(v) for v in vector["xy"]]
            for module in range(4):
                dsp.set_xy(module, xy[module], xy[4 + module])
            processed = dsp.process(pcm)
            state = dsp.state()

            cases.append({
                "name": vector["name"],
                "frames": int(vector["frames"]),
                "sample_rate_hz": rate,
                "peak_dbfs": round(dsp.peak_dbfs(pcm), 9),
                "limited_peak_dbfs": round(dsp.peak_dbfs(limited), 9),
                "sample": round(dsp.brickwall_sample(1.0), 9),
                "checksum": dsp.checksum(limited),
                "transient": transient,
                "limited": [round(v, 9) for v in limited],
                "processed": [round(v, 9) for v in processed],
                "s808": [round(v, 9) for v in synth],
                "state": state,
            })
    finally:
        dsp.close()
    return {
        "impl": "wasmtime",
        "abi": dsp.abi,
        "limiter_dbfs": dsp.limiter_dbfs,
        "runtime": dsp.status,
        "cases": cases,
    }
