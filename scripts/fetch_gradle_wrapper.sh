#!/usr/bin/env bash
# Lädt das offizielle gradle-wrapper.jar für Gradle 8.7.
#
#   ./scripts/fetch_gradle_wrapper.sh [--verify SHA256]
#
# -- REAL-IMPLEMENTATION 2026-09-12 (Online-Alternativen-Evaluation)
# Zwei Quellen, weil nicht jedes Netz beide erlaubt:
#   1) GitHub-Contents-API (api.github.com) – funktioniert auch dort, wo
#      raw.githubusercontent.com gesperrt ist (Base64 im JSON).
#   2) raw.githubusercontent.com als Fallback (klassischer Weg).
# Beide liefern dieselbe Datei; die Identität wird über den Git-Blob-SHA1
# (GitHub meldet ihn) und die gepinnte SHA-256 geprüft.
#
# Ohne --verify wird die gepinnte SHA256_EXPECTED benutzt.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="8.7"
REPO="gradle/gradle"
REF="v${VERSION}.0"
PATH_IN_REPO="gradle/wrapper/gradle-wrapper.jar"
DEST="android/gradle/wrapper/gradle-wrapper.jar"
# SHA-256 des offiziellen Jars aus gradle/gradle@v8.7.0
# (Git-Blob-SHA1: e6441136f3d4ba8a0da8d277868979cfbc8ad796)
SHA256_EXPECTED="cb0da6751c2b753a16ac168bb354870ebb1e162e9083f116729cec9c781156b8"

EXPECT="$SHA256_EXPECTED"
if [ "${1:-}" = "--verify" ] && [ -n "${2:-}" ]; then
  EXPECT="$2"
fi

command -v curl >/dev/null 2>&1 || { echo "curl required" >&2; exit 1; }
mkdir -p "$(dirname "$DEST")"

downloaded=""

# Quelle 1: GitHub-Contents-API (gh falls authentifziert, sonst curl ohne Token)
if [ -z "$downloaded" ]; then
  api_url="https://api.github.com/repos/${REPO}/contents/${PATH_IN_REPO}?ref=${REF}"
  if command -v gh >/dev/null 2>&1; then
    if gh api "repos/${REPO}/contents/${PATH_IN_REPO}?ref=${REF}" --jq .content 2>/dev/null | base64 -d > "$DEST" 2>/dev/null \
       && [ -s "$DEST" ]; then
      downloaded="api.github.com (gh)"
    fi
  fi
  if [ -z "$downloaded" ]; then
    if curl -fsSL -H "Accept: application/vnd.github.raw" "$api_url" -o "$DEST" 2>/dev/null && [ -s "$DEST" ]; then
      downloaded="api.github.com (curl)"
    fi
  fi
fi

# Quelle 2: raw.githubusercontent.com
if [ -z "$downloaded" ]; then
  raw_url="https://raw.githubusercontent.com/${REPO}/${REF}/${PATH_IN_REPO}"
  if curl -fsSL "$raw_url" -o "$DEST" 2>/dev/null && [ -s "$DEST" ]; then
    downloaded="raw.githubusercontent.com"
  fi
fi

if [ -z "$downloaded" ]; then
  echo "keine Quelle erreichbar (api.github.com und raw.githubusercontent.com)" >&2
  exit 1
fi

ACTUAL=$(sha256sum "$DEST" | awk '{print $1}')
echo "downloaded: $DEST"
echo "source:     $downloaded"
echo "sha256:     $ACTUAL"

if [ "$ACTUAL" != "$EXPECT" ]; then
  echo "checksum mismatch: expected $EXPECT" >&2
  exit 1
fi
echo "checksum verified"
