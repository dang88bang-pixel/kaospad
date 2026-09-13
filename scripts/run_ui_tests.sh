#!/usr/bin/env bash
# Echte Browser-UI-Tests (Playwright) – mit sauberem SKIP, wenn kein Browser da ist.
#
#   make test-ui            # läuft, wenn Chromium installiert ist
#   make test-ui-install    # npm ci + Chromium herunterladen
#
# Der Playwright-Browser-CDN (cdn.playwright.dev) ist in manchen Sandboxes
# gesperrt; dann meldet dieses Script SKIP statt eines roten Builds – die
# Spec-Dateien selbst werden trotzdem über `make test-ui-list` geprüft.
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d node_modules/@playwright/test ]]; then
  echo "SKIP test-ui: @playwright/test fehlt – 'npm ci' ausführen."
  exit 0
fi

LOG="$(mktemp)"
./node_modules/.bin/playwright test --config tests/ui/playwright.config.mjs "$@" 2>&1 | tee "$LOG"
status=${PIPESTATUS[0]}

if grep -q "Executable doesn't exist" "$LOG"; then
  echo "SKIP test-ui: Chromium-Binary fehlt – 'make test-ui-install' (npm ci && npm run test:ui:install)."
  rm -f "$LOG"
  exit 0
fi

rm -f "$LOG"
exit "$status"
