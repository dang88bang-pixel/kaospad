#!/usr/bin/env python3
"""Audit-Inventar: welche Datei ist REAL, MOCK, STUB, TODO, FIXME, PLACEHOLDER oder DEAD?

Erzeugt `docs/audit/INVENTAR.csv` und `docs/audit/GAP-MATRIX.csv` und druckt eine
Zusammenfassung. Keine Code-Änderungen – reine Bestandserhebung (Phase 1).

    python3 scripts/audit_inventory.py [--root .] [--out docs/audit]

Klassifikation (höchste gefundene Stufe gewinnt):

    PLACEHOLDER  NotImplementedError / "PLACEHOLDER"-Marker / leerer Pflicht-Body
    STUB         "STUB"/"SHIM"-Marker, Datei- oder Symbolname *_stub/stub_*,
                 oder Funktion deren Body nur pass/return None/return {} ist
    MOCK         "MOCK"-Marker oder Mock-/Fake-/Dummy-Bezeichner
    TODO         TODO/FIXME/HACK-Marker im Quelltext
    DEAD         keine Referenz irgendwo im Repo, kein Einstiegspunkt, kein Test
    REAL         sonst – mit Beleg (Testreferenz, Makefile/CI-Eintrag, Ausführbarkeit)

Zusätzlich pro Datei: Zeilen, Marker-Fundstellen, Dummy-Rückgaben,
unauflösbare lokale Imports und ob ein Test die Datei referenziert.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
from collections import Counter
from pathlib import Path

SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".cpp", ".hpp", ".cc", ".h", ".kt", ".kts", ".rs", ".sh", ".html", ".css", ".json", ".yml", ".yaml", ".xml", ".gradle", ".toml"}
SKIP_DIRS = {".git", "node_modules", "build", "dist", "backups", "__pycache__", ".cache", "test-results", "playwright-report", ".gradle", "target"}
# Klassische Kommentar-Marker (im Repo: null Treffer, aber der Vollständigkeit halber).
MARKER_RE = re.compile(r"(?://|#|<!--|/\*|^\s*\*+)\s*(TODO|FIXME|HACK|XXX)\b[:\- ]?(.*)", re.IGNORECASE)
# Dieses Repo markiert Ersatz-Implementierungen in Prosa/Docstrings/UI-Strings
# ("daemon stub", "0.4ms shim", "offline-placeholder:whisper:5.0.0"). Ohne diese
# Klasse wäre das Inventar blind.
PROSE_MARKER_RE = re.compile(r"\b(SHIM|STUB|PLACEHOLDER|MOCK(?:ED)?|DUMMY|FAKE|SIMULATOR)\b", re.IGNORECASE)
SELF = Path(__file__).resolve().name
# Bewusste No-Op-Overrides (Logging abschalten) sind keine fehlende Implementierung.
INTENTIONAL_NOOP = {"log_message", "log_request", "log_error", "do_OPTIONS"}
DUMMY_RETURN_RE = re.compile(r"^\s*(?:return\s+(?:0|false|nullptr|NULL|\{\}|\[\]|None)\s*;?|pass\s*(?:#.*)?|\.\.\.\s*)$")
ENTRY_HINTS = ("if __name__ ==", "int main(", "fun main(", "fn main(", "#!/")

STATUS_ORDER = ["REAL", "DEAD", "TODO", "MOCK", "STUB", "PLACEHOLDER"]


def iter_sources(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


def local_import_targets(path: Path, root: Path) -> list[str]:
    """Lokale Importe/Includes, die auf keine vorhandene Datei zeigen."""
    text = path.read_text(encoding="utf-8", errors="replace")
    missing: list[str] = []
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return ["<syntax error>"]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                head = node.module.split(".")[0]
                if head in {"engines", "scripts", "tests", "mopac_dance_learner", "neurallift_360"}:
                    candidates = [root / f"{node.module.replace('.', '/')}{ext}" for ext in (".py", "/__init__.py")]
                    if not any(c.exists() for c in candidates):
                        missing.append(node.module)
    else:
        for match in re.finditer(r"""(?:from|import)\s+['"](\.[^'"]+)['"]""", text):
            spec = match.group(1)
            base = (path.parent / spec).resolve()
            if not any((base.with_suffix(ext)).exists() for ext in ("", ".js", ".mjs", ".css", ".json", ".wasm")):
                missing.append(spec)
        for match in re.finditer(r'#include\s+"([^"]+)"', text):
            spec = match.group(1)
            if not (path.parent / spec).exists() and not (root / "android/app/src/main/cpp" / spec).exists():
                missing.append(spec)
    return missing


def empty_body_symbols(text: str, path: Path) -> list[str]:
    """Python-Funktionen ohne echten Body (pass / return None / ...)."""
    if path.suffix != ".py":
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in INTENTIONAL_NOOP:
            continue
        body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        if not body:
            found.append(node.name)
            continue
        if len(body) == 1:
            only = body[0]
            if isinstance(only, ast.Pass):
                found.append(node.name)
            elif isinstance(only, ast.Return) and (only.value is None or (isinstance(only.value, ast.Constant) and only.value.value is None)):
                found.append(node.name)
    return found


def classify(path: Path, root: Path, all_text: dict[Path, str]) -> dict[str, object]:
    rel = path.relative_to(root).as_posix()
    text = all_text[path]
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)

    markers: list[str] = []
    proof = ""
    header_markers: set[str] = set()
    body_markers: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = MARKER_RE.search(line)
        prose = PROSE_MARKER_RE.search(line) if not match else None
        if not match and not prose:
            continue
        kind = (match.group(1) if match else prose.group(1)).upper()
        markers.append(f"{kind}:{lineno}")
        proof = proof or line.strip()[:100]
        # Nur die Kopfzone (Modul-Docstring / Datei-Kommentar) beschreibt die
        # Datei selbst. Treffer tief im Code beziehen sich meist auf etwas
        # anderes (UI-Label, Beschreibung einer Fremd-Komponente, Test-Harness).
        (header_markers if lineno <= 20 else body_markers).add(kind)

    dummy = sum(1 for line in text.splitlines() if DUMMY_RETURN_RE.match(line))
    not_impl = len(re.findall(r"raise\s+NotImplementedError", text))
    placeholder_values = 0 if path.name == SELF else len(re.findall(r"offline-placeholder:", text))
    empty_syms = empty_body_symbols(text, path)
    missing_imports = local_import_targets(path, root)

    lowered = text.lower() if path.name != SELF else ""
    name = path.stem.lower()
    is_test = bool(re.search(r"(^|/)(tests?)/", rel)) or name.endswith(("_test", "Test", ".test")) or name.startswith("test_")
    is_entry = any(hint in text for hint in ENTRY_HINTS)

    # Referenzen: wird die Datei irgendwo sonst genannt?
    needles = {path.name, path.stem}
    refs = 0
    for other, other_text in all_text.items():
        if other == path:
            continue
        if any(needle and needle in other_text for needle in needles):
            refs += 1

    category = (
        "Test" if is_test else
        "Build/CI" if re.search(r"(^|/)(\.github/workflows/|scripts/|Makefile|CMakeLists\.txt)|\.(gradle|gradle\.kts|toml|xml)$|package(-lock)?\.json$", rel) else
        "Engine" if rel.startswith("engines/") else
        "Web" if rel.startswith("web/") or "/assets/www/" in rel else
        "Native" if rel.startswith(("android/", "desktop/")) else
        "Quelle"
    )

    status = "REAL"
    evidence: list[str] = []

    # Platzhalter/fehlende Implementierung – immer relevant.
    if not_impl or placeholder_values or "PLACEHOLDER" in header_markers:
        status = "PLACEHOLDER"
        if not_impl:
            evidence.append(f"NotImplementedError={not_impl}")
        if placeholder_values:
            evidence.append(f"offline-placeholder-Werte={placeholder_values}")
    elif category in {"Quelle", "Engine", "Web", "Native"}:
        if {"STUB", "SHIM", "SIMULATOR"} & header_markers or "_stub" in name or name.startswith("stub_"):
            status = "STUB"
        elif {"MOCK", "MOCKED", "DUMMY", "FAKE"} & header_markers or re.search(r"\b(mock|fake|dummy)[a-z_]*\s*[=(]", lowered):
            status = "MOCK"
        elif {"TODO", "FIXME", "HACK", "XXX"} & header_markers:
            status = "TODO"
        elif empty_syms:
            status = "STUB"
            evidence.append("leere Bodies: " + ",".join(empty_syms[:4]))
    elif category == "Test":
        # Tests werden durch Ausführung validiert, nicht durch Marker.
        if empty_syms:
            evidence.append("leere Bodies: " + ",".join(empty_syms[:4]))

    if {"STUB", "SHIM", "SIMULATOR", "MOCK", "PLACEHOLDER"} & body_markers and status in {"REAL", "TODO"}:
        evidence.append("Ersatz-Implementierung nur in Teilbereich (siehe Beleg)")

    # Build-/CI-Konfiguration wird vom Tooling referenziert, nicht per Text.
    if status == "REAL" and refs == 0 and not is_entry and not is_test and category != "Build/CI":
        status = "DEAD"
        evidence.append("keine Textreferenz im Repo")
    if category == "Build/CI" and refs == 0:
        evidence.append("vom Tooling referenziert (Gradle/CMake/Actions)")

    test_ref = any(("tests/" in other_path.as_posix() or other_path.suffix in {".mjs", ".js"}) and path.name in other_text
                   for other_path, other_text in all_text.items() if other_path != path)
    if test_ref:
        evidence.append("von Test referenziert")
    if missing_imports:
        evidence.append("unauflösbare Imports: " + ",".join(missing_imports[:3]))

    return {
        "Datei": rel,
        "Kategorie": category,
        "Zeilen": lines,
        "Status": status,
        "Marker": " ".join(markers[:8]),
        "MarkerAnzahl": len(markers),
        "DummyReturns": dummy,
        "NotImplemented": not_impl,
        "Referenzen": refs,
        "TestReferenz": "ja" if test_ref else "nein",
        "Beleg": proof,
        "Hinweis": "; ".join(evidence),
    }


def gap_matrix(root: Path, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Gefordert (FULL_IMPLEMENTATION_TODO.md) vs. vorhanden vs. Status."""
    todo_doc = root / "docs" / "FULL_IMPLEMENTATION_TODO.md"
    if not todo_doc.exists():
        return []
    status_by_file = {row["Datei"]: row for row in rows}
    out: list[dict[str, object]] = []
    checkbox = re.compile(r"^\s*-\s*\[( |x|~)\]\s*(.+)$")
    table_row = re.compile(r"^\|(.+)\|$")
    for lineno, line in enumerate(todo_doc.read_text(encoding="utf-8").splitlines(), start=1):
        requirement = None
        demanded = None
        match = checkbox.match(line)
        if match:
            demanded = {" ": "offen", "x": "erledigt", "~": "teilweise"}[match.group(1)]
            requirement = match.group(2).strip()
        else:
            cells = [c.strip() for c in table_row.match(line).group(1).split("|")] if table_row.match(line) else []
            if len(cells) >= 3 and any(tag in cells[-1] for tag in ("🧪", "🧩", "⛔", "🔁")):
                requirement = " | ".join(cells[:-1])
                demanded = cells[-1]
        if not requirement:
            continue
        paths = re.findall(r"`([^`]+\.(?:py|js|mjs|cpp|hpp|kt|sh|html|json|md|wasm))`", requirement)
        present = [p for p in paths if (root / p).exists()]
        statuses = sorted({str(status_by_file[p]["Status"]) for p in present if p in status_by_file})
        out.append({
            "Zeile": lineno,
            "Gefordert": requirement[:180],
            "DokuStatus": demanded,
            "Pfade": " ".join(paths) or "-",
            "Vorhanden": f"{len(present)}/{len(paths)}" if paths else "-",
            "CodeStatus": ",".join(statuses) or "-",
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="docs/audit")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    files = iter_sources(root)
    all_text = {path: path.read_text(encoding="utf-8", errors="replace") for path in files}
    rows = [classify(path, root, all_text) for path in files]
    rows.sort(key=lambda row: (STATUS_ORDER.index(str(row["Status"])), str(row["Datei"])), reverse=True)

    with (out_dir / "INVENTAR.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    gaps = gap_matrix(root, rows)
    if gaps:
        with (out_dir / "GAP-MATRIX.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(gaps[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(gaps)

    counts = Counter(str(row["Status"]) for row in rows)
    categories = Counter(str(row["Kategorie"]) for row in rows)
    summary = {
        "dateien": len(rows),
        "zeilen": sum(int(row["Zeilen"]) for row in rows),
        "status": dict(counts),
        "marker_gesamt": sum(int(row["MarkerAnzahl"]) for row in rows),
        "dateien_mit_markern": sum(1 for row in rows if int(row["MarkerAnzahl"]) > 0),
        "dummy_returns": sum(int(row["DummyReturns"]) for row in rows),
        "not_implemented": sum(int(row["NotImplemented"]) for row in rows),
        "unaufloesbare_imports": sum(1 for row in rows if "unauflösbare Imports" in str(row["Hinweis"])),
        "kategorien": dict(categories),
        "gap_zeilen": len(gaps),
        "gap_offen": sum(1 for g in gaps if g["DokuStatus"] in {"offen", "teilweise", "🧩 TODO"}),
        "gap_blockiert": sum(1 for g in gaps if "⛔" in str(g["DokuStatus"])),
        "gap_shim": sum(1 for g in gaps if "🧪" in str(g["DokuStatus"])),
        "inventar": (out_dir / "INVENTAR.csv").relative_to(root).as_posix(),
        "gap_matrix": (out_dir / "GAP-MATRIX.csv").relative_to(root).as_posix() if gaps else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\nNicht-REAL Dateien (höchste Stufe zuerst):")
    for row in rows:
        if row["Status"] != "REAL":
            print(f"  {row['Status']:<11} {row['Datei']:<62} {row['Zeilen']:>5} Zeilen  {row['Hinweis']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
