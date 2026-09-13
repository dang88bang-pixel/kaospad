// Playwright-Konfiguration für die echten Browser-UI-Tests der Kaoss One App.
//
//   npm ci                       # @playwright/test
//   npm run test:ui:install      # Chromium einmalig herunterladen
//   npm run test:ui              # = make test-ui
//
// Der One-App-Server wird von Playwright selbst gestartet (127.0.0.1, Zero-Cloud)
// und nach dem Lauf beendet.
import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const port = Number(process.env.KAOSS_UI_PORT || 8123);

export default defineConfig({
  testDir: path.dirname(fileURLToPath(import.meta.url)),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: {
    command: `python3 app.py --host 127.0.0.1 --port ${port}`,
    cwd: root,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
