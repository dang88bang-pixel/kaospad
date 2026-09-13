#!/usr/bin/env python3
"""Zweite, unabhängige WASM-Laufzeit: wasmtime == Node/V8 == Python-Spiegel.

-- REAL-IMPLEMENTATION 2026-09-12 (Online-Alternativen-Evaluation)

`emcc` bleibt unerreichbar; das WASM-Modul entsteht mit `ziglang`. Die bestehende
Paritätsprüfung (`tests/dsp_wasm_parity_test.mjs`) führt dieses Modul ausschließlich
in Node/V8 aus. `wasmtime` (PyPI ✅) ist eine vollständig unabhängige Laufzeit:
liefert dasselbe `dist/wasm/kaoss_dsp.wasm` dort dieselben Zahlen, hängt das Modul
nicht an V8-Eigenheiten.

Verglichen wird gegen die bereits vorhandenen Referenzläufe
(`dist/parity/wasm.json` = Node/V8, `dist/parity/python.json` = Python-Spiegel) mit
denselben Toleranzen wie dort (1e-6 bzw. 1e-5). Der FNV-1a-Hash über die Float-Bits
muss **exakt** übereinstimmen, weil beide Läufe dasselbe float32-Modul ausführen.

Aufruf:  python3 tests/wasm_cross_runtime_test.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines"))

import wasm_cross_runtime as wr  # noqa: E402

FAILED: list[str] = []
SKIPPED: list[str] = []
CHECKS = 0

LIMITER_DBFS = -3.2
TOLERANCE_SAME_MODULE = 1e-6      # wasmtime vs Node: dasselbe float32-Modul
TOLERANCE_PYTHON = 1e-5           # wie im bestehenden Paritätstest


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}",
          flush=True)
    if not ok:
        FAILED.append(f"{label} {detail}".strip())


def section(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def max_deviation(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return float("inf")
    return max((abs(x - y) for x, y in zip(a, b)), default=0.0)


def availability_tests() -> None:
    section("Verfügbarkeit wird ehrlich gemeldet")
    status = wr.availability()
    check("availability() liefert ein dict", isinstance(status, dict))
    check("Laufzeit benannt", status.get("runtime") == "wasmtime", str(status.get("runtime")))
    if status["ok"]:
        check("Version gemeldet", bool(status.get("version")), str(status.get("version")))
        module = ROOT / str(status["module"])
        check("Modulpfad existiert", module.exists(), str(module))
        check("Modulgröße plausibel (> 100 kB)", status.get("module_bytes", 0) > 100_000,
              str(status.get("module_bytes")))
    else:
        check("Grund genannt", bool(status.get("reason")), str(status.get("reason"))[:80])


def vector_tests() -> None:
    section("Vektor-Lader liest dasselbe Format")
    path = ROOT / "dist" / "parity" / "vectors.bin"
    if not path.exists():
        SKIPPED.append("dist/parity/vectors.bin fehlt (make test-wasm-parity zuerst)")
        print("[SKIP] Vektoren fehlen", flush=True)
        return
    vectors = wr.read_vectors()
    check("Vektoren gelesen", len(vectors) >= 5, f"{len(vectors)} Fälle")
    first = vectors[0]
    for key in ("name", "rate", "frames", "pcm", "xy", "s808_frames", "s808_ms"):
        check(f"Feld {key} vorhanden", key in first)
    check("PCM-Länge passt zu frames", len(first["pcm"]) == first["frames"],
          f"{len(first['pcm'])} vs {first['frames']}")
    check("xy hat 8 Werte", len(first["xy"]) == 8, str(len(first["xy"])))
    try:
        wr.VECTOR_MAGIC = b"XXXX"
        wr.read_vectors()
        check("falsche Magie wird abgelehnt", False, "keine Exception")
    except ValueError as exc:
        check("falsche Magie wird abgelehnt", True, str(exc)[:40])
    finally:
        wr.VECTOR_MAGIC = b"KVEC"


def parity_tests() -> None:
    section("wasmtime == Node/V8 == Python-Spiegel")
    status = wr.availability()
    if not status["ok"]:
        SKIPPED.append(f"wasmtime nicht nutzbar ({status.get('reason')})")
        print(f"[SKIP] wasmtime fehlt -- Paritätslauf übersprungen: {status.get('reason')}",
              flush=True)
        return

    node_path = ROOT / "dist" / "parity" / "wasm.json"
    python_path = ROOT / "dist" / "parity" / "python.json"
    if not node_path.exists() or not python_path.exists():
        SKIPPED.append("Referenzläufe fehlen (make test-wasm-parity zuerst)")
        print("[SKIP] Referenzläufe fehlen", flush=True)
        return

    node = json.loads(node_path.read_text(encoding="utf-8"))
    python = json.loads(python_path.read_text(encoding="utf-8"))
    mine = wr.run_parity()

    check("wasmtime meldet ABI 1", mine["abi"] == 1, str(mine["abi"]))
    check("ABI stimmt mit Node überein", mine["abi"] == node["abi"], str(node["abi"]))
    check("Limiter-Schwelle -3.2 dBFS", abs(mine["limiter_dbfs"] - LIMITER_DBFS) < 1e-9,
          str(mine["limiter_dbfs"]))
    check("Fallzahl stimmt mit Node überein", len(mine["cases"]) == len(node["cases"]),
          f"{len(mine['cases'])} vs {len(node['cases'])}")
    check("impl als wasmtime gekennzeichnet", mine["impl"] == "wasmtime", mine["impl"])

    worst_node = 0.0
    worst_python = 0.0
    for mine_case, node_case in zip(mine["cases"], node["cases"]):
        name = mine_case["name"]
        check(f"{name}: Namen identisch", name == node_case["name"])

        # FNV-1a über die Float-Bits: muss exakt stimmen (dasselbe Modul, f32)
        check(f"{name}: FNV-1a-Hash bitgleich zu Node",
              mine_case["checksum"] == node_case["checksum"],
              f"{mine_case['checksum']} vs {node_case['checksum']}")

        for key in ("peak_dbfs", "limited_peak_dbfs", "sample"):
            dev = abs(mine_case[key] - node_case[key])
            worst_node = max(worst_node, dev)
            check(f"{name}: {key} == Node", dev <= TOLERANCE_SAME_MODULE,
                  f"Abweichung {dev:.2e}")

        for key in ("kind_id", "frequency_hz", "detection_latency_ms"):
            dev = abs(mine_case["transient"][key] - node_case["transient"][key])
            worst_node = max(worst_node, dev)
            check(f"{name}: transient.{key} == Node", dev <= TOLERANCE_SAME_MODULE,
                  f"Abweichung {dev:.2e}")

        for buffer in ("limited", "processed", "s808"):
            dev = max_deviation(mine_case[buffer], node_case[buffer])
            worst_node = max(worst_node, dev)
            check(f"{name}: {buffer} == Node", dev <= TOLERANCE_SAME_MODULE,
                  f"max. Abweichung {dev:.2e} über {len(mine_case[buffer])} Werte")

        dev = max_deviation(mine_case["state"]["xy"], node_case["state"]["xy"])
        worst_node = max(worst_node, dev)
        check(f"{name}: state.xy == Node", dev <= TOLERANCE_SAME_MODULE,
              f"Abweichung {dev:.2e}")
        check(f"{name}: state.frozen == Node",
              mine_case["state"]["frozen"] == node_case["state"]["frozen"])
        dev = abs(mine_case["state"]["bpm"] - node_case["state"]["bpm"])
        worst_node = max(worst_node, dev)
        check(f"{name}: state.bpm == Node", dev <= TOLERANCE_SAME_MODULE,
              f"Abweichung {dev:.2e}")

        # Limiter-Vertrag in der zweiten Laufzeit
        check(f"{name}: Limiter hält {LIMITER_DBFS} dBFS",
              mine_case["limited_peak_dbfs"] <= LIMITER_DBFS + 1e-5,
              str(mine_case["limited_peak_dbfs"]))

    for mine_case, py_case in zip(mine["cases"], python["cases"]):
        name = mine_case["name"]
        for key in ("peak_dbfs", "limited_peak_dbfs", "sample"):
            dev = abs(mine_case[key] - py_case[key])
            worst_python = max(worst_python, dev)
            check(f"{name}: {key} == Python-Spiegel", dev <= TOLERANCE_PYTHON,
                  f"Abweichung {dev:.2e}")
        for buffer in ("limited", "processed", "s808"):
            dev = max_deviation(mine_case[buffer], py_case[buffer])
            worst_python = max(worst_python, dev)
            check(f"{name}: {buffer} == Python-Spiegel", dev <= TOLERANCE_PYTHON,
                  f"max. Abweichung {dev:.2e}")

    print(f"\nwasmtime == Node/V8:      max. Abweichung {worst_node:.3e}", flush=True)
    print(f"wasmtime == Python-Spiegel: max. Abweichung {worst_python:.3e}", flush=True)
    check("Gesamtabweichung zu Node unter Toleranz", worst_node <= TOLERANCE_SAME_MODULE,
          f"{worst_node:.3e}")
    check("Gesamtabweichung zum Python-Spiegel unter Toleranz",
          worst_python <= TOLERANCE_PYTHON, f"{worst_python:.3e}")

    kicks = [c for c in mine["cases"] if c["transient"]["kind_id"] == 1]
    check("Transientenerkennung lebt (>= 2 Kicks)", len(kicks) >= 2, f"{len(kicks)} Kicks")


def zero_cloud_tests() -> None:
    section("Zero-Cloud: kein Netzwerk im Modul")
    source = (ROOT / "engines" / "wasm_cross_runtime.py").read_text(encoding="utf-8")
    for forbidden in ("import requests", "import urllib", "import http.client",
                      "import socket", "http://", "https://"):
        check(f"wasm_cross_runtime.py enthält kein {forbidden}", forbidden not in source)


def main() -> int:
    availability_tests()
    vector_tests()
    parity_tests()
    zero_cloud_tests()

    print("", flush=True)
    if SKIPPED:
        print("übersprungen:", " | ".join(SKIPPED), flush=True)
    if FAILED:
        print(f"FEHLER ({len(FAILED)}):", flush=True)
        for item in FAILED:
            print(f"  - {item}", flush=True)
        return 1
    if SKIPPED:
        # Ehrlich: ohne Laufzeit/Referenz wurde *keine* Parität geprüft.
        print(f"wasm cross-runtime verified: {CHECKS} checks // "
              f"nur Struktur geprüft // Parität übersprungen (Laufzeit oder "
              f"Referenz fehlt)", flush=True)
    else:
        print(f"wasm cross-runtime verified: {CHECKS} checks // "
              f"wasmtime == Node/V8 == Python // FNV-1a bitgleich über dasselbe "
              f"Modul", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
