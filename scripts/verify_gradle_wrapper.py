#!/usr/bin/env python3
"""Verifiziert den Android Gradle Wrapper (Skript + Properties + Jar).

Der offizielle ``gradle-wrapper.jar`` kann in dieser Offline-Sandbox nicht
erzeugt werden (kein JDK/Netz); der CI-Runner nutzt ``gradle/actions/setup-gradle``
und stellt Gradle 8.7 bereit. Dieser Check prüft die statischen Teile hart und
meldet das fehlende Jar als Warnung (``--require-jar`` macht es zum Fehler).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"
PROPS = ANDROID / "gradle" / "wrapper" / "gradle-wrapper.properties"
GRADLEW = ANDROID / "gradlew"
WRAPPER_JAR = ANDROID / "gradle" / "wrapper" / "gradle-wrapper.jar"

EXPECTED_DIST = "https://services.gradle.org/distributions/gradle-8.7-bin.zip"

checks = 0
warnings: list[str] = []


def main() -> int:
    require_jar = "--require-jar" in sys.argv
    global checks

    props = PROPS.read_text(encoding="utf-8").replace("\\://", "://")
    if "distributionUrl" not in props:
        raise SystemExit("FAIL: gradle-wrapper.properties ohne distributionUrl")
    checks += 1
    if EXPECTED_DIST not in props:
        raise SystemExit(f"FAIL: distributionUrl muss {EXPECTED_DIST} sein")
    checks += 1
    if not GRADLEW.is_file():
        raise SystemExit("FAIL: android/gradlew fehlt")
    checks += 1
    if not (GRADLEW.stat().st_mode & 0o111):
        raise SystemExit("FAIL: android/gradlew ist nicht ausführbar")
    checks += 1

    if WRAPPER_JAR.is_file():
        digest = hashlib.sha256(WRAPPER_JAR.read_bytes()).hexdigest()
        checks += 1
        print(f"gradle-wrapper.jar present ({WRAPPER_JAR.stat().st_size} bytes) sha256={digest[:16]}…")
    else:
        warnings.append(
            "gradle-wrapper.jar fehlt lokal (kein JDK/Netz in der Sandbox); "
            "CI stellt Gradle 8.7 über gradle/actions/setup-gradle bereit. "
            "Offizielles Jar: scripts/fetch_gradle_wrapper.sh"
        )
        if require_jar:
            raise SystemExit("FAIL: gradle-wrapper.jar fehlt und --require-jar gesetzt")

    for message in warnings:
        print(f"  warn: {message}")
    print(f"gradle wrapper contract verified: {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
