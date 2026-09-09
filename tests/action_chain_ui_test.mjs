#!/usr/bin/env node
/**
 * Headless-Test der browserseitigen Aktions- und Interaktionskette.
 *
 * Phase A (offline): `web/src/action-chain.js` wird als ES-Modul geladen und die
 *   komplette Kette gegen den deterministischen Offline-Dispatcher gefahren –
 *   genau der Pfad, den die PWA ohne Backend (file://) nimmt.
 * Phase B (live): dieselbe Kette wird mit dem echten HTTP-Dispatcher aus
 *   `web/src/app.js` gegen einen gestarteten One-App-Server gefahren und der
 *   Client-State-Spiegel mit `/api/state` verglichen (Konvergenz UI ↔ Server).
 *
 * Zero-cloud: es wird ausschließlich 127.0.0.1 angesprochen.
 */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');

const {
  ACTION_BY_NAME,
  ENGINES,
  FULL_CHAIN_SCRIPT,
  LIMITER_DBFS,
  SAMPLE_BANKS,
  chainReducer,
  createAction,
  defaultState,
  formatChainLine,
  isActionReady,
  missingMilestones,
  offlineDispatcher,
  runChain,
  summarize,
} = await import(`file://${path.join(root, 'web/src/action-chain.js')}`);

const checks = [];
function check(label, condition, detail = '') {
  if (!condition) {
    const text = typeof detail === 'string' ? detail : JSON.stringify(detail);
    throw new Error(`CHECK FAILED: ${label} // ${text.slice(0, 400)}`);
  }
  checks.push(label);
}

// --------------------------------------------------------------------------- //
// Phase A – Offline-Kette (PWA ohne Backend)
// --------------------------------------------------------------------------- //
function phaseOffline() {
  check('catalogue size', Object.keys(ACTION_BY_NAME).length === 19, Object.keys(ACTION_BY_NAME));
  check('script size', FULL_CHAIN_SCRIPT.length === 23, FULL_CHAIN_SCRIPT.length);
  check(
    'script actions known',
    FULL_CHAIN_SCRIPT.every((step) => ACTION_BY_NAME[step.action]),
    FULL_CHAIN_SCRIPT.map((step) => step.action),
  );
  check('engines cover 8080-8085', Object.values(ENGINES).map((engine) => engine.port).sort().join(',') === '8080,8081,8082,8083,8084,8085');
  check('sample banks 4x4', SAMPLE_BANKS.length === 4 && SAMPLE_BANKS.every((bank) => bank.slots.length === 4));

  // Statische Ordnungsprüfung: die kanonische Kette erfüllt ihre eigenen Guards.
  let probe = defaultState();
  for (const step of FULL_CHAIN_SCRIPT) {
    const missing = missingMilestones(probe, step.action);
    check(`script order ${step.action}`, missing.length === 0, { action: step.action, missing });
    const spec = ACTION_BY_NAME[step.action];
    if (spec.milestone) probe.milestones.add(spec.milestone);
    if (step.action === 'boot') probe = Object.assign(probe, defaultState(), { milestones: probe.milestones });
  }

  // createAction Guard
  let threw = false;
  try {
    createAction('not.an.action');
  } catch {
    threw = true;
  }
  check('createAction rejects unknown action', threw);

  const created = createAction('kaoss.xy', { module: 2, x: 0.8, y: 0.2 });
  check('createAction maps engine/port', created.engine === 'dsp' && created.port === 8084, created);

  // ready/pre-check API
  const fresh = defaultState();
  check('fresh mic.arm not ready', isActionReady(fresh, 'mic.arm') === false);
  check('fresh boot ready', isActionReady(fresh, 'boot') === true);

  return runChain(offlineDispatcher(), FULL_CHAIN_SCRIPT).then((report) => {
    check('offline chain ok', report.ok === true, report.results.filter((event) => !event.ok));
    check('offline chain steps', report.steps === FULL_CHAIN_SCRIPT.length, report.steps);
    const state = report.state;
    check('offline input', state.input === 'usb_c_audio', state.input);
    check('offline permission granted', state.permissions.record_audio === true, state.permissions);
    check('offline audio running', state.audio.running === true && state.audio.mic_armed === true, state.audio);
    check('offline preset bpm', Number(state.kaoss.bpm) === 128, state.kaoss.bpm);
    check('offline kaoss modules', state.kaoss.modules.length === 4 && state.kaoss.modules[0].frozen === true, state.kaoss.modules);
    check('offline dsp blocks', state.dsp.blocks === 5, state.dsp.blocks);
    check('offline transient counts', state.dsp.kick808 === 2 && state.dsp.snare === 2 && state.dsp.hat === 1, state.dsp);
    check('offline limiter safe', report.summary.limiter_safe === true && state.dsp.max_peak_dbfs <= LIMITER_DBFS + 1e-6, state.dsp.max_peak_dbfs);
    check('offline pads', state.pads.length === 2 && state.pads[0].bank === 'A', state.pads);
    check('offline transport', state.transport.recording === false && state.transport.loop_captured === true, state.transport);
    check('offline loop frames', state.transport.loop_frames === 24000, state.transport);
    check('offline lyrics', state.lyrics.transcripts.length === 1, state.lyrics);
    check('offline rhymes', (state.lyrics.rhymes.beton || []).includes('SEKTOR'), state.lyrics.rhymes);
    check('offline avatar', state.avatar.mode === 'CYPHER_CIRCLE' && state.avatar.avatars === 8, state.avatar);
    check('offline glb', typeof state.avatar.glb === 'string' && state.avatar.glb.endsWith('.glb'), state.avatar.glb);
    check('offline milestones', ['input.selected', 'mic.armed', 'dsp.processed', 'transport.recording', 'avatar.mode'].every((milestone) => state.milestones.has(milestone)), [...state.milestones]);
    check('offline summary', report.summary.length === FULL_CHAIN_SCRIPT.length && report.summary.blocked === 0, report.summary);

    const line = formatChainLine(report.results[10]);
    check('chain line format', /^#\s*\d+ \S+\s+ OK\s+[\d.]+ms :80\d\d/.test(line), line);
    check('chain line content', line.includes('pad.trigger') || line.includes('dsp.process'), line);

    // Determinismus: zweiter Lauf mit identischer Aktionsfolge
    return runChain(offlineDispatcher(), FULL_CHAIN_SCRIPT).then((second) => {
      check('offline deterministic actions', second.summary.actions.join('|') === report.summary.actions.join('|'));
      check('offline deterministic length', second.summary.length === report.summary.length);
      return report;
    });
  });
}

// --------------------------------------------------------------------------- //
// Phase A2 – Blocked-Verhalten (Server-Guard-Simulation)
// --------------------------------------------------------------------------- //
function phaseBlocked() {
  const milestones = new Set();
  let seq = 0;
  const guardDispatch = (action, params = {}) => {
    seq += 1;
    const spec = ACTION_BY_NAME[action];
    const missing = spec.requires.filter((milestone) => !milestones.has(milestone));
    if (missing.length) {
      return {
        seq, action, engine: spec.engine, port: ENGINES[spec.engine].port, ok: false, status: 'BLOCKED',
        latency_ms: 0.05, detail: { blocked_reason: 'interaction chain out of order', missing_milestones: missing },
      };
    }
    if (spec.milestone) milestones.add(spec.milestone);
    return {
      seq, action, engine: spec.engine, port: ENGINES[spec.engine].port, ok: true, status: 'OK',
      latency_ms: 0.2, detail: action === 'dsp.process' ? { report: { transient: { kind: 'KICK808' }, kick808: true, output_peak_dbfs: -3.2 } } : {},
    };
  };

  return runChain(guardDispatch, [
    { action: 'mic.arm' },
    { action: 'dsp.process', signal: 'mouth_bass' },
    { action: 'loop.capture' },
    { action: 'session.export' },
  ]).then((report) => {
    check('blocked chain not ok', report.ok === false);
    check('blocked count', report.summary.blocked === 4, report.summary);
    check('blocked no milestones', report.state.milestones.size === 0, [...report.state.milestones]);
    check('blocked events kept', report.state.events.every((event) => event.status === 'BLOCKED'), report.state.events);
    check('blocked dsp untouched', report.state.dsp.blocks === 0, report.state.dsp);
    return report;
  });
}

// --------------------------------------------------------------------------- //
// Phase B – Live-Kette gegen den echten One-App-Server (Browser-Pfad)
// --------------------------------------------------------------------------- #
function httpDispatcher(baseUrl) {
  return async function dispatch(action, params = {}) {
    const response = await fetch(`${baseUrl}/api/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ action, strict: true, ...params }),
    });
    if (!response.ok) throw new Error(`action http ${response.status}`);
    const payload = await response.json();
    return {
      seq: payload.seq,
      t_ms: payload.t_ms,
      action: payload.action,
      engine: payload.engine,
      port: payload.port,
      status: payload.status,
      ok: payload.ok,
      latency_ms: payload.latency_ms,
      detail: payload.detail || {},
    };
  };
}

async function waitForServer(baseUrl, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/health`, { cache: 'no-store' });
      if (response.ok) return;
    } catch {
      // Server startet noch
    }
    await new Promise((resolve) => setTimeout(resolve, 120));
  }
  throw new Error('one-app server did not start');
}

async function phaseLive() {
  const port = 8093 + (process.pid % 40);
  const baseUrl = `http://127.0.0.1:${port}`;
  const server = spawn('python3', [path.join(root, 'app.py'), '--host', '127.0.0.1', '--port', String(port)], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stderr = '';
  server.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
  try {
    await waitForServer(baseUrl);
    const dispatch = httpDispatcher(baseUrl);

    await dispatch('chain.reset');
    const report = await runChain(dispatch, FULL_CHAIN_SCRIPT);
    check('live chain ok', report.ok === true, report.results.filter((event) => !event.ok).map((event) => [event.action, event.status, event.detail]));
    check('live chain steps', report.steps === FULL_CHAIN_SCRIPT.length, report.steps);
    check('live no blocked', report.summary.blocked === 0, report.summary);
    check('live limiter safe', report.summary.limiter_safe === true, report.summary.max_peak_dbfs);
    check('live input', report.state.input === 'usb_c_audio', report.state.input);
    check('live bpm', Number(report.state.kaoss.bpm) === 128, report.state.kaoss.bpm);
    check('live freeze', report.state.kaoss.modules[0].frozen === true, report.state.kaoss.modules);
    check('live dsp blocks', report.state.dsp.blocks === 5, report.state.dsp.blocks);
    check('live transient mix', report.state.dsp.kick808 === 2 && report.state.dsp.snare === 2 && report.state.dsp.hat === 1, report.state.dsp);
    check('live chain latency budget', report.summary.max_latency_ms < 400, report.summary.max_latency_ms);

    // Konvergenz: Client-Spiegel == Server-State
    const serverState = await (await fetch(`${baseUrl}/api/state`, { cache: 'no-store' })).json();
    check('converged chain length', serverState.chain.length === report.summary.length, [serverState.chain.length, report.summary.length]);
    check('converged actions', serverState.chain.actions.slice(-report.summary.length).join('|') === report.summary.actions.join('|'), serverState.chain.actions);
    check('converged input', serverState.input.selected === report.state.input, serverState.input);
    check('converged bpm', serverState.bpm === Number(report.state.kaoss.bpm), serverState.bpm);
    check('converged freeze', serverState.kaoss.modules[0].frozen === report.state.kaoss.modules[0].frozen, serverState.kaoss.modules);
    check('converged dsp blocks', serverState.dsp.blocks === report.state.dsp.blocks, [serverState.dsp.blocks, report.state.dsp.blocks]);
    check('converged limiter', serverState.dsp.max_peak_dbfs <= LIMITER_DBFS + 1e-6, serverState.dsp.max_peak_dbfs);
    check('converged rhymes', (serverState.lyrics.rhymes.beton || []).includes('SEKTOR'), serverState.lyrics.rhymes);
    check('converged avatar', serverState.avatar.mode === report.state.avatar.mode, serverState.avatar);
    check('converged transport', serverState.transport.recording === report.state.transport.recording, serverState.transport);

    // Blocked-Guard über HTTP
    await dispatch('chain.reset');
    const early = await dispatch('mic.arm', { device_id: 'too-early' });
    check('live blocked guard', early.ok === false && early.status === 'BLOCKED', early);
    check('live blocked milestone', early.detail.missing_milestones.includes('audio.started'), early.detail);

    // Export über HTTP inkl. Aktionskette
    await dispatch('chain.reset');
    await runChain(dispatch, FULL_CHAIN_SCRIPT);
    const exportResponse = await fetch(`${baseUrl}/api/session/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const exported = await exportResponse.json();
    const session = exported.detail.session;
    check('live export format', session.format === '.cypher', session.format);
    check('live export chain', session.chain_length >= FULL_CHAIN_SCRIPT.length, session.chain_length);
    check('live export checksum', typeof session.checksum === 'string' && session.checksum.length === 64, session.checksum);
    check('live export offline', session.created_offline === true && session.zero_cloud === true, session);

    // Determinismus über HTTP: gleiche Kette -> gleicher .cypher Hash
    const firstChecksum = session.checksum;
    await dispatch('chain.reset');
    await runChain(dispatch, FULL_CHAIN_SCRIPT);
    const secondExport = await (await fetch(`${baseUrl}/api/session/export`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
    })).json();
    check('live export deterministic', secondExport.detail.session.checksum === firstChecksum, [firstChecksum, secondExport.detail.session.checksum]);

    // Zero-Cloud Header + Origin-Guard
    const guarded = await fetch(`${baseUrl}/api/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'http://evil.example' },
      body: JSON.stringify({ action: 'boot' }),
    });
    check('live origin guard', guarded.status === 403, guarded.status);
    check('live zero cloud header', guarded.headers.get('x-kaoss-zero-cloud') === 'true', [...guarded.headers]);
  } finally {
    server.kill('SIGTERM');
    await new Promise((resolve) => setTimeout(resolve, 80));
    if (server.exitCode === null) server.kill('SIGKILL');
    if (stderr.trim()) process.stderr.write(`[server stderr] ${stderr.slice(0, 400)}\n`);
  }
}

const offlineReport = await phaseOffline();
await phaseBlocked();
await phaseLive();

console.log(JSON.stringify({
  offline_steps: offlineReport.summary.length,
  offline_limiter_safe: offlineReport.summary.limiter_safe,
  offline_max_latency_ms: offlineReport.summary.max_latency_ms,
  checks: checks.length,
}, null, 0));
console.log(`browser action & interaction chain verified: ${checks.length} checks (offline + blocked + live server)`);
