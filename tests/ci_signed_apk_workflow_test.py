#!/usr/bin/env python3
"""CI/CD-Vertrag fuer die signierte Android-APK.

Laauft ohne Android SDK/JDK und haelt die Kette zusammen:

* **Alle** Workflow-Dateien muessen gueltiges YAML sein. Genau das war bei
  ``multiplatform-ci-cd.yml`` kaputt (``- name: Guard: ...``) und fuehrte zu
  0-Sekunden-Failures ohne Jobs.
* ``android-signed-apk.yml`` muss: auf main/Branch/Tag/Dispatch/PR triggern,
  ``contents: write`` haben, ``assembleRelease`` bauen, explizit mit apksigner
  (v1+v2+v3) signieren, den Guard ``scripts/verify_signed_apk.py`` ausfuehren,
  per ``gh`` ein Release publizieren und die APK nach ``releases/android/``
  committen.
* Der Offline-Stub ``releases/KaossBeatboxStudio-v5.0.0-Universal-Signed.apk``
  bleibt Negativ-Fixture: keine Pipeline darf ihn ueberschreiben.
* Keystore-Material bleibt aus Git raus (.gitignore + keystore.properties-Pfad).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ANDROID_WF = WORKFLOWS / "android-signed-apk.yml"
MULTIPLATFORM_WF = WORKFLOWS / "multiplatform-ci-cd.yml"
GRADLE = ROOT / "android" / "app" / "build.gradle.kts"
STUB_APK = ROOT / "releases" / "KaossBeatboxStudio-v5.0.0-Universal-Signed.apk"
REPO_APK_DIR = ROOT / "releases" / "android"
GUARD = ROOT / "scripts" / "verify_signed_apk.py"

checks = 0
warnings: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    if not condition:
        raise SystemExit(f"FAIL: {label}" + (f" // {detail}" if detail else ""))
    checks += 1


def load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def main() -> int:
    # ------------------------------------------------------------------ #
    # 1. Jedes Workflow-File ist parsebares YAML
    # ------------------------------------------------------------------ #
    workflow_files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    check("workflows vorhanden", len(workflow_files) >= 3, str(len(workflow_files)))

    parsed: dict[Path, object] = {}
    yaml_available = True
    for path in workflow_files:
        data = load_yaml(path)
        if data is None:
            yaml_available = False
            break
        check(f"YAML gueltig: {path.name}", isinstance(data, dict))
        parsed[path] = data
    if not yaml_available:
        warnings.append("PyYAML fehlt lokal - YAML-Strukturchecks uebersprungen (Textchecks laufen)")

    # ------------------------------------------------------------------ #
    # 2. Android-Workflow: Trigger, Rechte, Schritte
    # ------------------------------------------------------------------ #
    check("android-signed-apk.yml vorhanden", ANDROID_WF.is_file())
    text = ANDROID_WF.read_text(encoding="utf-8")

    if yaml_available and ANDROID_WF in parsed:
        data = parsed[ANDROID_WF]  # type: ignore[assignment]
        triggers = data.get("on", data.get(True))  # YAML 1.1: 'on' -> True
        check("trigger definiert", isinstance(triggers, dict), str(type(triggers)))
        push = triggers.get("push", {})
        branches = push.get("branches", [])
        tags = push.get("tags", [])
        check("push auf main", "main" in branches, str(branches))
        check("push auf session-branch", any(str(b).startswith("arena/") for b in branches), str(branches))
        check("push auf tags v*.*.*", any(str(t).startswith("v") for t in tags), str(tags))
        check("workflow_dispatch vorhanden", "workflow_dispatch" in triggers)
        inputs = (triggers.get("workflow_dispatch") or {}).get("inputs", {})
        check("dispatch-input publish_release", "publish_release" in inputs, str(list(inputs)))
        check("dispatch-input commit_to_repo", "commit_to_repo" in inputs, str(list(inputs)))
        check("pull_request vorhanden", "pull_request" in triggers)
        permissions = data.get("permissions", {})
        check("permissions contents=write", permissions.get("contents") == "write", str(permissions))
        jobs = data.get("jobs", {})
        check("genau ein Job", len(jobs) == 1, str(list(jobs)))
        steps = next(iter(jobs.values())).get("steps", [])
        step_text = "\n".join(str(step.get("run", "")) + " " + str(step.get("uses", "")) for step in steps)
        check("checkout mit fetch-depth", any(step.get("uses") == "actions/checkout@v4" for step in steps))
    else:
        step_text = text

    required = [
        ("JDK 17", "actions/setup-java@v4"),
        ("Android SDK", "android-actions/setup-android@v3"),
        ("Gradle", "gradle/actions/setup-gradle@v4"),
        ("assembleRelease", "gradle :app:assembleRelease"),
        ("apksigner sign", "${APKSIGNER}\" sign"),
        ("v1 signing", "--v1-signing-enabled true"),
        ("v2 signing", "--v2-signing-enabled true"),
        ("v3 signing", "--v3-signing-enabled true"),
        ("apksigner verify", "verify --verbose --print-certs"),
        ("zertifikat-export", "--print-certs-pem"),
        ("guard-skript", "scripts/verify_signed_apk.py"),
        ("guard-selftest", "verify_signed_apk.py --selftest"),
        ("zipalign-check", "${ZIPALIGN}\" -c"),
        ("zipalign vor signatur", "${ZIPALIGN}\" -f -p 4"),
        ("jarsigner v1-nachweis", "jarsigner -verify"),
        ("secret keystore", "secrets.KAOSS_KEYSTORE_BASE64"),
        ("secret alias", "secrets.KAOSS_KEY_ALIAS"),
        ("fallback keytool", "keytool -genkeypair"),
        ("cache restore", "actions/cache/restore@v4"),
        ("cache save", "actions/cache/save@v4"),
        ("keystore.properties", "android/keystore.properties"),
        ("gh release create", "gh release create"),
        ("gh release upload", "gh release upload"),
        ("gh token", "github.token"),
        ("artefakt-upload", "actions/upload-artifact@v4"),
        ("repo-commit-pfad", "releases/android"),
        ("git push zurueck", "git push origin"),
        ("sha256sums", "SHA256SUMS.txt"),
        ("signing-nachweis", "SIGNING.txt"),
        ("step-summary", "GITHUB_STEP_SUMMARY"),
    ]
    for label, needle in required:
        check(f"workflow enthaelt {label}", needle in text or needle in step_text, needle)

    forbidden = [
        ("Stub-APK wird ueberschrieben", str(STUB_APK.relative_to(ROOT))),
        ("Wrapper-Platzhalter wird genutzt", "./gradlew"),
    ]
    for label, needle in forbidden:
        check(f"workflow vermeidet: {label}", needle not in text, needle)

    # ------------------------------------------------------------------ #
    # 3. Gradle-Signing liest keystore.properties UND Env
    # ------------------------------------------------------------------ #
    gradle = GRADLE.read_text(encoding="utf-8")
    check("gradle liest keystore.properties", 'rootProject.file("keystore.properties")' in gradle)
    check("gradle liest KAOSS_KEYSTORE_FILE", 'System.getenv("KAOSS_KEYSTORE_FILE")' in gradle or '"KAOSS_KEYSTORE_FILE"' in gradle)
    check("gradle signingConfig ciRelease", 'create("ciRelease")' in gradle)
    check("gradle fail-fast bei fehlendem keystore", "check(file.isFile)" in gradle)
    check("versionName parsebar", re.search(r'versionName\s*=\s*"[^"]+"', gradle) is not None)
    check("versionCode parsebar", re.search(r"versionCode\s*=\s*\d+", gradle) is not None)
    check("plugins-Block vor vals", gradle.index("plugins {") < gradle.index("keystoreProperties"))

    # ------------------------------------------------------------------ #
    # 4. Keystore-Material bleibt aus Git raus
    # ------------------------------------------------------------------ #
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check(".gitignore behandelt Keystore-Material", "android/keystore.properties" in gitignore)

    def is_ignored(probe: str) -> bool:
        return subprocess.run(
            ["git", "check-ignore", "-q", probe], cwd=ROOT, capture_output=True, text=True, timeout=60
        ).returncode == 0

    for probe in (
        "android/keystore.properties",
        "android/signing/kaoss-release.p12",
        "android/signing/kaoss-release.jks",
        "android/signing/kaoss-release-key.pem",
        "signing-cache/kaoss-release.p12",
        "dist-release/app-release.apk",
    ):
        check(f"gitignored: {probe}", is_ignored(probe))
    check("releases/android/*.apk bleibt getrackt", not is_ignored("releases/android/app-release.apk"))

    tracked = subprocess.run(
        ["git", "ls-files", "android/signing"], cwd=ROOT, capture_output=True, text=True, timeout=60
    ).stdout.split()
    check(
        "kein Private-Key/Keystore getrackt",
        not any(name.endswith((".p12", ".pfx", ".jks", "-key.pem")) for name in tracked),
        str(tracked),
    )

    # ------------------------------------------------------------------ #
    # 5. Guard-Skript besteht seinen Selftest
    # ------------------------------------------------------------------ #
    check("guard-skript vorhanden", GUARD.is_file())
    result = subprocess.run([sys.executable, str(GUARD), "--selftest"], cwd=ROOT, capture_output=True, text=True, timeout=180)
    check("guard selftest exit 0", result.returncode == 0, result.stdout[-800:] + result.stderr[-800:])
    check("guard selftest meldet Szenarien", "selftest passed" in result.stdout, result.stdout[-300:])

    # Negativ-Fixture bleibt ein Stub (kein lib/*.so) - Voraussetzung fuer den Release-Guard.
    check("stub apk weiterhin vorhanden", STUB_APK.is_file())
    result = subprocess.run(
        [sys.executable, str(GUARD), str(STUB_APK), "--no-pwa-assets"], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    check("guard lehnt stub apk ab", result.returncode != 0, result.stdout[-400:])

    # ------------------------------------------------------------------ #
    # 6. Multi-Platform-Workflow bleibt konsistent (Release-Guard-Strings)
    # ------------------------------------------------------------------ #
    multi = MULTIPLATFORM_WF.read_text(encoding="utf-8")
    for needle in ("verify_release_artifacts.py", "generate_sbom.py", "sha256sum", "assembleRelease"):
        check(f"multiplatform workflow enthaelt {needle}", needle in multi)

    # ------------------------------------------------------------------ #
    # 7. Repo-Ablage der signierten APK (wird von CI befuellt)
    # ------------------------------------------------------------------ #
    check("releases/android/README.md vorhanden", (REPO_APK_DIR / "README.md").is_file())
    apks = sorted(REPO_APK_DIR.glob("*.apk"))
    if apks:
        check("genau eine apk im repo-tree", len(apks) == 1, str([a.name for a in apks]))
        report = REPO_APK_DIR / "apksigner-report.txt"
        if report.is_file():
            # Kein --require-v1: minSdk 26 -> apksigner ueberspringt die v1-Pruefung.
            result = subprocess.run(
                [
                    sys.executable, str(GUARD), str(apks[0]),
                    "--apksigner-report", str(report),
                ],
                cwd=ROOT, capture_output=True, text=True, timeout=180,
            )
            check("committete apk besteht guard", result.returncode == 0, result.stdout[-800:])
        else:
            warnings.append(f"{report.relative_to(ROOT)} fehlt - Guard fuer Repo-APK uebersprungen")
    else:
        warnings.append(
            "noch keine CI-APK in releases/android/ (erscheint nach dem ersten Lauf von "
            ".github/workflows/android-signed-apk.yml)"
        )

    for message in warnings:
        print(f"  warn: {message}")
    print(f"signed apk CI/CD contract verified: {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
