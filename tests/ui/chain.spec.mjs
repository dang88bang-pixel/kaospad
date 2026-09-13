// Echte Browser-UI-Tests (Chromium) der vollständigen Aktions- und Interaktionskette.
//
// Ergänzt den DOM-Stub-Harness (tests/web_ui_interaction_chain_test.mjs): hier
// laufen echtes DOM, echte Pointer-Events, echtes EventSource/SSE und echte
// fetch()-Aufrufe gegen den One-App-Server.
import { expect, test } from '@playwright/test';

const LIMITER_DBFS = -3.2;

async function waitForApp(page) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  const failed = [];
  page.on('requestfailed', (request) => failed.push(`${request.method()} ${request.url()}`));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#runtime-port')).not.toHaveText('AUTO', { timeout: 15_000 });
  return { errors, failed };
}

test('One App bootet: Runtime, Katalog und State werden geladen', async ({ page }) => {
  const { errors, failed } = await waitForApp(page);
  await expect(page.locator('#runtime-endpoints')).not.toHaveText('0');
  await expect(page.locator('#chain-length')).toBeVisible();
  await expect(page.locator('#dsp-core-state')).not.toHaveText('DSP: –', { timeout: 15_000 });
  const core = await page.locator('#dsp-core-state').textContent();
  expect(core).toMatch(/DSP: (WASM ABI \d+|JS FALLBACK)/);
  expect(errors, errors.join('\n')).toEqual([]);
  expect(failed.filter((item) => !item.includes('favicon')), failed.join('\n')).toEqual([]);
});

test('Vollständige Kette läuft im Browser: 23 Schritte, kein BLOCKED, Limiter hält', async ({ page }) => {
  await waitForApp(page);
  await page.locator('#run-full-chain').click();
  await expect
    .poll(async () => (await page.evaluate(() => globalThis.__KAOSS_CHAIN__.summary())).length, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(23);
  const summary = await page.evaluate(() => globalThis.__KAOSS_CHAIN__.summary());
  expect(summary.blocked).toBe(0);
  expect(summary.max_peak_dbfs).toBeLessThanOrEqual(LIMITER_DBFS + 1e-6);
  await expect(page.locator('#chain-blocked')).toHaveText('0');
  await expect(page.locator('#chain-state')).toContainText('23 SCHRITTE');
  await expect(page.locator('#state-bpm')).toContainText('128.0 BPM');
  await expect(page.locator('#state-peak')).toContainText('-3.2');
  await expect(page.locator('#state-input')).toHaveText('usb_c_audio');
  const log = await page.locator('#action-chain-log').textContent();
  expect(log).toContain('session.export');
  expect(log.split('\n').length).toBeGreaterThan(5);
});

test('SSE pusht Ketten-Events live in die UI (ohne Polling)', async ({ page }) => {
  await waitForApp(page);
  // EventSource ist im Browser echt vorhanden und verbunden.
  await expect
    .poll(async () => page.evaluate(() => Boolean(globalThis.__KAOSS_CHAIN__.stream())), { timeout: 15_000 })
    .toBe(true);
  await expect(page.locator('#stream-state')).toContainText('STREAM: LIVE', { timeout: 15_000 });

  const before = await page.evaluate(() => globalThis.__KAOSS_CHAIN__.streamEvents().length);
  await page.evaluate(() => globalThis.__KAOSS_CHAIN__.dispatch('input.select', { input: 'internal_mic' }));
  await expect
    .poll(async () => page.evaluate(() => globalThis.__KAOSS_CHAIN__.streamEvents().length), { timeout: 15_000 })
    .toBeGreaterThan(before);
  // Dieser Text kommt ausschließlich vom SSE-`chain`-Listener (nicht vom Polling).
  await expect(page.locator('#stream-state')).toHaveText(/STREAM: LIVE \/\/ seq \d+ input\.select OK/, {
    timeout: 15_000,
  });

  // Polling-Fallback bleibt dieselbe Quelle: /api/events kennt dieselbe Seq.
  const api = await page.evaluate(async () => {
    const response = await fetch('/api/events?since=0', { cache: 'no-store' });
    return response.json();
  });
  expect(api.ok).toBe(true);
  expect(api.events.at(-1).action).toBe('input.select');
});

test('Capture-Panel zeigt Backend, Block und ehrliche Provenienz', async ({ page }) => {
  await waitForApp(page);
  await page.locator('#input-select').selectOption('bluetooth_client');
  await page.locator('#capture-open').click();
  // Ohne Hardware/Client sind NONE (geschlossen) bzw. FIXTURE/FILE (geöffnet,
  // aber nicht live) die korrekten, ehrlichen Werte.
  await expect(page.locator('#capture-state')).toHaveText(
    /CAPTURE: (NONE|FIXTURE|FILE|ALSA|USB_UAC2|IPC_BLE|IPC_UAC2|IPC_MIC|CLIENT_PCM) (LIVE|ARMED \(wartet\)|FIXTURE)/,
    { timeout: 15_000 },
  );
  await page.locator('#capture-pull').click();
  await expect(page.locator('#capture-state')).toHaveText(
    /CAPTURE-BLOCK: ((\w+) (REAL|FILE) \/\/ \d+f @\d+(\.\d+)?Hz peak -?\d+(\.\d+)? dBFS|keiner \(\w+\))/,
    { timeout: 15_000 },
  );

  const status = await page.evaluate(async () => {
    const response = await fetch('/api/audio/capture', { cache: 'no-store' });
    return response.json();
  });
  expect(status.ok).toBe(true);
  expect(status.probe.zero_cloud).toBe(true);
  expect(Object.keys(status.probe.backends)).toEqual(expect.arrayContaining(['alsa', 'usb_uac2', 'ipc', 'file']));
  // Ohne Hardware/Client darf sich das System nicht als live ausgeben.
  if (!status.status.armed || status.status.blocks === 0) {
    expect(status.status.real_capture).toBe(false);
  }
});

test('Session-Store: Export persistiert, letzte Sitzung ist ladbar und replaybar', async ({ page }) => {
  await waitForApp(page);
  await page.locator('#run-full-chain').click();
  await expect(page.locator('#chain-state')).toContainText('23 SCHRITTE', { timeout: 30_000 });

  await page.locator('#export-session').click();
  await expect(page.locator('#vault-state')).toContainText(/VAULT: EXPORTED|VAULT: .*CYPHER/i, { timeout: 15_000 });
  await expect
    .poll(async () => page.evaluate(() => document.querySelector('#session-latest').value), { timeout: 15_000 })
    .toMatch(/SESSION: \d+ Schritte/);

  await page.locator('#restore-session').click();
  await expect(page.locator('#vault-state')).toContainText('SITZUNG IMPORTIERT', { timeout: 15_000 });

  const replay = await page.evaluate(async () => {
    const response = await fetch('/api/session/replay', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    return response.json();
  });
  expect(replay.ok).toBe(true);
  expect(replay.replay.params_restored).toBe(true);
  expect(replay.replay.checksum_match).toBe(true);
  expect(replay.replay.blocked).toEqual([]);
});

test('XY-Pad steuert per echtem Pointer-Event die Kaoss-Module', async ({ page }) => {
  await waitForApp(page);
  await page.evaluate(async () => {
    await globalThis.__KAOSS_CHAIN__.dispatch('audio.start', { sample_rate_hz: 96000, frames_per_buffer: 128 });
  });
  const pad = page.locator('#xy-pad');
  const box = await pad.boundingBox();
  await page.mouse.move(box.x + box.width * 0.25, box.y + box.height * 0.75);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.2, { steps: 8 });
  await page.mouse.up();
  await expect(page.locator('#xy-readout')).toContainText(/XY 0\.\d\d \/ 0\.\d\d/);
  const readout = await page.locator('#xy-readout').textContent();
  expect(readout).not.toContain('XY 0.00 / 0.00');
});

test('Reihenfolge-Guard: dsp.process ohne mic.arm wird BLOCKED angezeigt', async ({ page }) => {
  await waitForApp(page);
  await page.evaluate(() => globalThis.__KAOSS_CHAIN__.dispatch('chain.reset'));
  const event = await page.evaluate(() => globalThis.__KAOSS_CHAIN__.dispatch('dsp.process', { signal: 'mouth_bass' }));
  expect(event.status).toBe('BLOCKED');
  expect(event.detail.missing_milestones).toContain('mic.armed');
  await expect(page.locator('#chain-blocked')).not.toHaveText('0');
});
