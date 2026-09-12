#!/usr/bin/env bash
# Lädt das offizielle gradle-wrapper.jar für Gradle 8.7 (benötigt Netzwerk;
# nur für Entwickler-Maschinen oder CI mit Internetzugang, nie in der Sandbox).
#
#   ./scripts/fetch_gradle_wrapper.sh [--verify SHA256]
#
# Ohne --verify wird nur heruntergeladen und der SHA-256 ausgegeben.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="8.7"
URL="https://raw.githubusercontent.com/gradle/gradle/v${VERSION}.0/gradle/wrapper/gradle-wrapper.jar"
DEST="android/gradle/wrapper/gradle-wrapper.jar"
EXPECT=""

if [ "${1:-}" = "--verify" ]; then
  EXPECT="${2:-}"
fi

command -v curl >/dev/null 2>&1 || { echo "curl required" >&2; exit 1; }

mkdir -p android/gradle/wrapper
curl -fsSL "$URL" -o "$DEST"
ACTUAL=$(sha256sum "$DEST" | awk '{print $1}')
echo "downloaded: $DEST"
echo "sha256:     $ACTUAL"

if [ -n "$EXPECT" ]; then
  if [ "$ACTUAL" != "$EXPECT" ]; then
    echo "checksum mismatch: expected $EXPECT" >&2
    exit 1
  fi
  echo "checksum verified"
fi
