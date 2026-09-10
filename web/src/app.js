import { WebAudioCypherEngine } from './audio-engine.js';
import {
  ACTION_BY_NAME,
  ENGINES,
  FULL_CHAIN_SCRIPT,
  SAMPLE_BANKS,
  chainReducer,
  createAction,
  defaultState,
  formatChainLine,
  missingMilestones,
  offlineDispatcher,
  summarize,
} from './action-chain.js';

const runtimeConfig = {
  port: location.port || (location.protocol === 'https:' ? '443' : '80'),
  base_url: location.origin,
  endpoints: [],
  zero_cloud: true,
};

async function loadRuntimeConfig() {
  try {
    const response = await fetch('/api/runtime', { cache: 'no-store' });
    if (!response.ok) throw new Error('runtime fallback');
    Object.assign(runtimeConfig, await response.json());
  } catch {
    runtimeConfig.endpoints = ['/api/status', '/native-bridge/ports', '/devices/status', '/rhymes', '/api/action'];
  }
  document.querySelector('#runtime-port').textContent = String(runtimeConfig.port || location.port || 'AUTO');
  document.querySelector('#runtime-base').textContent = runtimeConfig.base_url || location.origin;
  document.querySelector('#runtime-cloud').textContent = runtimeConfig.zero_cloud ? 'LOCKED' : 'CHECK';
  document.querySelector('#runtime-endpoints').textContent = String(runtimeConfig.endpoints?.length || 0);
  return runtimeConfig;
}

const DAEMONS = [
  { port: 8080, name: 'master-system-orchestrator', rule: 'Session State + Profile laden', protocol: 'HTTP JSON' },
  { port: 8081, name: 'audio-loopback-daemon', rule: 'What-U-Hear Float32 Pipe', protocol: 'Raw PCM' },
  { port: 8082, name: 'neurallift-engine', rule: 'Foto zu GLB Avatar', protocol: 'mmap / GLB' },
  { port: 8083, name: 'avatar-orchestrator', rule: '60 FPS Skeleton Matrix', protocol: 'WebSocket' },
  { port: 8084, name: 'dsp-transient-bridge', rule: 'BPM + Kick/Snare/Hat Trigger', protocol: 'UDP 64B' },
  { port: 8085, name: 'offline-whisper-daemon', rule: 'Text + Reimketten Lookup', protocol: 'IPC UTF-8' },
];

const bridge = globalThis.__KAOSS_NATIVE_BRIDGE__;
const bridgeMode = document.querySelector('#bridge-mode');
const portGrid = document.querySelector('#port-grid');
const daemonList = document.querySelector('#daemon');

daemonList.innerHTML = DAEMONS
  .map(({ port }) => `<div>127.0.0.1:${port} // localhost IPC reserved // zero-cloud</div>`)
  .join('');

loadRuntimeConfig();

function offlineStatusFor(port) {
  return {
    port,
    bind: '127.0.0.1',
    status: port === 8082 ? 'READY' : 'RESERVED',
    latency: port === 8081 || port === 8084 ? '<1.2ms' : 'AUTO',
    source: 'browser-safe simulation',
  };
}

let cachedNativeStatuses = null;

async function fetchNativeStatuses() {
  if (cachedNativeStatuses) return cachedNativeStatuses;
  try {
    const response = await fetch('/native-bridge/ports', { cache: 'no-store' });
    if (!response.ok) throw new Error(`native bridge http ${response.status}`);
    const payload = await response.json();
    if (payload?.ok && Array.isArray(payload.ports)) cachedNativeStatuses = payload.ports;
  } catch {
    cachedNativeStatuses = null;
  }
  return cachedNativeStatuses;
}

async function readPortStatus(spec) {
  if (bridge?.portStatus) {
    return bridge.portStatus(spec.port);
  }
  const nativeStatuses = await fetchNativeStatuses();
  const nativeStatus = nativeStatuses?.find((item) => item.port === spec.port);
  if (nativeStatus) return nativeStatus;
  // Browser-facing static preview falls back safely. When served by the
  // localhost IPC suite on :8080, /native-bridge/ports provides live status.
  return offlineStatusFor(spec.port);
}

function renderPortCard(spec, status) {
  const tone = status.status === 'READY' || status.status === 'LOCKED' ? 'locked' : 'reserved';
  const hits = status.chain_hits ? ` // ${status.chain_hits} chain hits` : '';
  return `
    <article class="port-card ${tone}">
      <div class="port-head"><span>:${spec.port}</span><b>${status.status}</b></div>
      <strong>${spec.name}</strong>
      <small>${spec.protocol}</small>
      <p>${spec.rule}</p>
      <code>${status.bind}:${spec.port} // ${status.latency}${hits}</code>
    </article>
  `;
}

async function refreshPortView() {
  cachedNativeStatuses = null;
  const statuses = await Promise.all(DAEMONS.map(async (spec) => [spec, await readPortStatus(spec)]));
  portGrid.innerHTML = statuses.map(([spec, status]) => renderPortCard(spec, status)).join('');
  bridgeMode.value = bridge?.portStatus
    ? 'BRIDGE: NATIVE LIVE'
    : cachedNativeStatuses
      ? 'BRIDGE: LOCALHOST IPC LIVE'
      : 'BRIDGE: AUTO SAFE SIM';
}

document.querySelector('#portview-auto').addEventListener('click', refreshPortView);
refreshPortView();
setInterval(refreshPortView, 4000);

// --------------------------------------------------------------------------- //
// Aktions- & Interaktionskette
// --------------------------------------------------------------------------- //
let chainState = defaultState();
const offlineDispatch = offlineDispatcher();
const chainLog = document.querySelector('#action-chain-log');
const chainStateOutput = document.querySelector('#chain-state');
const strictToggle = document.querySelector('#chain-strict');
const transportState = document.querySelector('#transport-state');
const avatarState = document.querySelector('#avatar-state');
const transcribeOutput = document.querySelector('#transcribe-output');
const xyReadout = document.querySelector('#xy-readout');

function renderChain(event) {
  const summary = summarize(chainState);
  document.querySelector('#chain-length').textContent = String(summary.length);
  document.querySelector('#chain-seq').textContent = `seq ${summary.seq}`;
  document.querySelector('#chain-blocked').textContent = String(summary.blocked);
  document.querySelector('#chain-latency').textContent = `${summary.max_latency_ms.toFixed(3)} ms`;
  document.querySelector('#chain-total').textContent = `total ${summary.total_latency_ms.toFixed(3)} ms`;
  document.querySelector('#state-peak').textContent = `${summary.max_peak_dbfs.toFixed(1)} dBFS`;
  document.querySelector('#state-limiter').textContent = summary.limiter_safe ? 'limiter -3.2 dBFS SAFE' : 'limiter CHECK';
  document.querySelector('#state-input').textContent = chainState.input;
  document.querySelector('#state-route').textContent = chainState.audio.mic_armed
    ? `mic armed // ${chainState.audio.sample_rate_hz / 1000} kHz`
    : chainState.audio.running
      ? `running // ${chainState.audio.roundtrip_ms} ms roundtrip`
      : 'route standby';
  document.querySelector('#state-transport').textContent = chainState.transport.recording ? 'RECORDING' : 'STOP';
  document.querySelector('#state-bpm').textContent = `${Number(chainState.kaoss.bpm || chainState.preset?.bpm || 92.4).toFixed(1)} BPM`;
  const frozen = chainState.kaoss.modules.filter((module) => module.frozen).length;
  document.querySelector('#state-freeze').textContent = `${frozen}/4`;
  document.querySelector('#state-loop').textContent = `loop ${chainState.transport.loop_frames} frames`;
  document.querySelector('#state-avatar').textContent = chainState.avatar.mode;
  document.querySelector('#state-glb').textContent = chainState.avatar.glb || 'procedural_default_avatar.glb';
  transportState.value = `TRANSPORT: ${chainState.transport.recording ? 'RECORDING' : chainState.transport.loop_captured ? 'LOOP HELD' : 'IDLE'}`;
  avatarState.value = `AVATAR: ${chainState.avatar.mode} // ${chainState.avatar.fps} FPS // ${chainState.avatar.avatars} AVATARE`;
  chainStateOutput.value = `CHAIN: ${summary.length} SCHRITTE // ${summary.blocked} BLOCKED // ${chainState.offlineFallback ? 'OFFLINE FALLBACK' : 'LIVE'}`;
  const lines = chainState.events.slice(-14).map(formatChainLine);
  chainLog.textContent = lines.length ? lines.join('\n') : 'CHAIN // noch keine Aktion – starte die vollständige Kette';
  chainLog.scrollTop = chainLog.scrollHeight;
  syncFreezeButtons();
  if (event) flashAction(event);
}

function flashAction(event) {
  const button = document.querySelector(`[data-action="${event.action}"]`);
  if (!button) return;
  button.classList.add(event.ok ? 'flash-ok' : 'flash-blocked');
  setTimeout(() => button.classList.remove('flash-ok', 'flash-blocked'), 420);
}

/**
 * Eine Aktion ausführen: POST an die One-App State Engine, bei fehlendem Backend
 * deterministischer Offline-Fallback (statische PWA-Preview).
 */
async function dispatchAction(action, params = {}) {
  const request = createAction(action, params);
  let event;
  try {
    const response = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ action, strict: strictToggle?.checked ?? true, ...params }),
    });
    if (!response.ok) throw new Error(`action http ${response.status}`);
    const payload = await response.json();
    event = {
      seq: payload.seq,
      t_ms: payload.t_ms,
      action: payload.action,
      engine: payload.engine,
      port: payload.port,
      status: payload.status,
      ok: payload.ok,
      latency_ms: payload.latency_ms,
      detail: payload.detail || {},
      server_state: payload.state,
    };
    chainState.offlineFallback = false;
  } catch (error) {
    if (location.protocol === 'file:') {
      event = offlineDispatch(action, params);
      chainState.offlineFallback = true;
    } else {
      event = {
        seq: chainState.seq + 1,
        action,
        engine: request.engine,
        port: request.port,
        status: 'ERROR',
        ok: false,
        latency_ms: 0,
        detail: { error: String(error.message || error), live: true },
      };
      chainState.offlineFallback = false;
    }
  }
  chainState = chainReducer(chainState, event);
  renderChain(event);
  return event;
}

async function runFullChain() {
  chainStateOutput.value = 'CHAIN: LÄUFT …';
  // Die Referenzkette startet immer aus einem definierten Zustand.
  await dispatchAction('chain.reset');
  chainState = defaultState();
  renderChain();
  // dispatchAction reduziert jedes Event genau einmal in chainState – deshalb
  // hier bewusst keine zweite Reduktion über runChain().
  const events = [];
  for (const step of FULL_CHAIN_SCRIPT) {
    const { action, ...params } = step;
    events.push(await dispatchAction(action, params));
  }
  renderChain();
  const summary = summarize(chainState);
  chainStateOutput.value = `CHAIN: ${summary.length} SCHRITTE // ${summary.blocked} BLOCKED // ${summary.limiter_safe ? 'LIMITER SAFE' : 'LIMITER CHECK'}`;
  return { ok: events.every((event) => event.ok), steps: events.length, results: events, state: chainState, summary };
}

document.querySelector('#run-full-chain').addEventListener('click', runFullChain);
document.querySelector('#chain-reset').addEventListener('click', async () => {
  await dispatchAction('chain.reset');
  chainState = defaultState();
  renderChain();
});

// --------------------------------------------------------------------------- //
// XY Pad + Freeze Module
// --------------------------------------------------------------------------- //
let liveEngine;
const pad = document.querySelector('#xy-pad');
const orb = document.querySelector('.orb');
let lastXYDispatch = 0;

pad.addEventListener('pointermove', (event) => {
  if (event.buttons !== 1 && event.pointerType !== 'touch') return;
  const rect = pad.getBoundingClientRect();
  const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
  const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
  orb.style.left = `${x - 48}px`;
  orb.style.top = `${y - 48}px`;
  const nx = x / rect.width;
  const ny = y / rect.height;
  liveEngine?.applyXY(nx, ny);
  xyReadout.value = `XY ${nx.toFixed(2)} / ${ny.toFixed(2)} // MODULE 2+3`;
  const now = Date.now();
  if (now - lastXYDispatch < 70) return;
  lastXYDispatch = now;
  if (!chainState.audio.running) return;
  dispatchAction('kaoss.xy', { module: 2, x: Number(nx.toFixed(3)), y: Number(ny.toFixed(3)) });
  dispatchAction('kaoss.xy', { module: 3, x: Number((1 - nx).toFixed(3)), y: Number(ny.toFixed(3)) });
});

pad.addEventListener('pointerdown', () => {
  if (!chainState.audio.running) dispatchAction('audio.start', { sample_rate_hz: 96000, frames_per_buffer: 128 });
});

const freezeState = [false, false, false, false];

function syncFreezeButtons() {
  document.querySelectorAll('.freeze').forEach((button) => {
    const module = Number(button.dataset.module);
    const frozen = Boolean(chainState.kaoss.modules[module]?.frozen);
    freezeState[module] = frozen;
    button.classList.toggle('locked', frozen);
    button.querySelector('span').textContent = frozen ? 'FREEZE ON' : 'FREEZE OFF';
  });
}

document.querySelectorAll('.freeze').forEach((button) => {
  button.addEventListener('click', async () => {
    const module = Number(button.dataset.module);
    const frozen = !freezeState[module];
    const event = await dispatchAction('kaoss.freeze', { module, frozen });
    const detail = event.detail || {};
    document.querySelector('#vault-state').value = detail.frozen
      ? `FX${module + 1} ${detail.name || ''}: FROZEN`
      : `FX${module + 1} ${detail.name || ''}: LIVE`;
  });
});

// --------------------------------------------------------------------------- //
// Sample Bank Pads A-D
// --------------------------------------------------------------------------- //
const padGrid = document.querySelector('#pad-grid');

function renderPadGrid() {
  padGrid.innerHTML = SAMPLE_BANKS.map((bank) => bank.slots
    .map((slot) => `<button type="button" class="drum-pad" data-pad="${bank.bank}/${slot}" data-bank="${bank.bank}" data-slot="${slot}"><span>BANK ${bank.bank}</span><strong>${slot}</strong><small>${bank.label}</small></button>`)
    .join(''))
    .join('');
  padGrid.querySelectorAll('.drum-pad').forEach((button) => {
    button.addEventListener('click', async () => {
      const bank = button.dataset.bank;
      const slot = button.dataset.slot;
      const event = await dispatchAction('pad.trigger', { bank, slot });
      if (event.status === 'BLOCKED') {
        document.querySelector('#vault-state').value = `PAD BLOCKED: erst ${event.detail.missing_milestones.join(', ')}`;
        return;
      }
      const padInfo = event.detail?.pad || {};
      document.querySelector('#vault-state').value = `PAD ${bank}/${slot} // ${padInfo.transient || 'OK'} // ${padInfo.peak_dbfs ?? '-'} dBFS`;
      const signal = SAMPLE_BANKS.find((item) => item.bank === bank)?.signal || 'mouth_bass';
      if (bank === 'A') liveEngine?.trigger808().catch(() => {});
      if (bank === 'B') liveEngine?.triggerSnare().catch(() => {});
      if (bank === 'C' || bank === 'D') dispatchAction('dsp.process', { signal, frames: 128 });
    });
  });
}

renderPadGrid();

// --------------------------------------------------------------------------- //
// Transport: Record + Loop Capture
// --------------------------------------------------------------------------- //
document.querySelector('#record-toggle').addEventListener('click', async (event) => {
  const running = !chainState.transport.recording;
  const result = await dispatchAction('transport.record', { running });
  if (result.ok) {
    event.target.textContent = running ? 'RECORD STOP' : 'RECORD START';
    return;
  }
  const missing = result.detail?.missing_milestones || [];
  document.querySelector('#vault-state').value = result.status === 'BLOCKED'
    ? `RECORD BLOCKED: erst ${missing.join(', ') || 'DSP-Block verarbeiten'}`
    : `RECORD FEHLER: ${result.detail?.error || result.status}`;
});

document.querySelector('#loop-capture').addEventListener('click', async () => {
  const result = await dispatchAction('loop.capture', { subdivision: 16 });
  const detail = result.detail || {};
  document.querySelector('#vault-state').value = detail.loop_frames
    ? `LOOP: ${detail.loop_frames} FRAMES // ${detail.loop_ms} MS // ${detail.step_ms} MS STEP`
    : 'LOOP BLOCKED: erst Aufnahme starten';
});

// --------------------------------------------------------------------------- //
// Avatar Stage + NeuralLift
// --------------------------------------------------------------------------- //
const avatarMode = document.querySelector('#avatar-mode');
document.querySelector('#avatar-apply').addEventListener('click', () => dispatchAction('avatar.mode', { mode: avatarMode.value }));
document.querySelector('#neurallift-run').addEventListener('click', async () => {
  const result = await dispatchAction('neurallift.generate', { source: 'camera_frame_0001.jpg' });
  document.querySelector('#vault-state').value = `GLB: ${result.detail?.glb || 'FALLBACK'} // offline`;
});

// --------------------------------------------------------------------------- //
// Drück & laber: Transkript + Reime
// --------------------------------------------------------------------------- //
document.querySelector('#transcribe-run').addEventListener('click', async () => {
  const text = document.querySelector('#transcribe-input').value;
  const result = await dispatchAction('transcribe', { text });
  if (result.status === 'BLOCKED') {
    transcribeOutput.value = 'TRANSKRIPT BLOCKED: erst Mic armen';
    return;
  }
  const rhymes = Object.values(result.detail?.rhymes || {}).flat();
  transcribeOutput.value = `${result.detail?.transcript?.text || text} // ${rhymes.slice(0, 6).join(' · ') || 'keine Reime'}`;
  const rhymeOutput = document.querySelector('#rhyme-output');
  if (rhymes.length) rhymeOutput.value = rhymes.slice(0, 8).join(' · ');
});

// --------------------------------------------------------------------------- //
// Live Audio Engine (WebAudio)
// --------------------------------------------------------------------------- //
const audioState = document.querySelector('#audio-state');
const meterFill = document.querySelector('#meter-fill');
const meterReadout = document.querySelector('#meter-readout');
const browserDeviceSelect = document.querySelector('#browser-device-select');

liveEngine = new WebAudioCypherEngine({
  onState: (message) => { audioState.value = message; },
  onLevel: ({ peak, dbfs }) => {
    const pct = Math.max(0, Math.min(100, peak * 100));
    meterFill.style.width = `${pct}%`;
    meterReadout.value = `PEAK: ${dbfs.toFixed(1)} dBFS`;
  },
});

async function populateBrowserInputs() {
  try {
    const inputs = await liveEngine.enumerateAudioInputs();
    const options = ['<option value="">Default Browser Input</option>'].concat(
      inputs.map((device, index) => `<option value="${device.deviceId}">${device.label || `Audio Input ${index + 1}`}</option>`),
    );
    browserDeviceSelect.innerHTML = options.join('');
  } catch {
    browserDeviceSelect.innerHTML = '<option value="">Default Browser Input</option>';
  }
}

document.querySelector('#start-audio').addEventListener('click', async () => {
  try {
    await liveEngine.init();
    await populateBrowserInputs();
    await dispatchAction('permission.grant', { key: 'record_audio', granted: true });
    await dispatchAction('audio.start', { sample_rate_hz: Math.round(liveEngine.context?.sampleRate || 96000), frames_per_buffer: 128 });
  } catch (error) {
    audioState.value = `AUDIO ERROR: ${error.message}`;
  }
});

document.querySelector('#arm-mic').addEventListener('click', async () => {
  try {
    await liveEngine.armMic(browserDeviceSelect.value);
    await populateBrowserInputs();
    const event = await dispatchAction('mic.arm', { device_id: browserDeviceSelect.value || 'browser-default' });
    if (event.status === 'BLOCKED') audioState.value = `MIC BLOCKED: ${event.detail?.missing_milestones?.join(', ')}`;
    refreshDeviceMatrix();
  } catch (error) {
    audioState.value = `MIC ERROR: ${error.message}`;
    dispatchAction('mic.arm', { device_id: browserDeviceSelect.value || 'browser-default' });
  }
});

document.querySelector('#trigger-808').addEventListener('click', () => {
  liveEngine.trigger808().catch((error) => { audioState.value = `808 ERROR: ${error.message}`; });
  dispatchAction('dsp.process', { signal: 'mouth_bass', frames: 128 });
});

document.querySelector('#trigger-snare').addEventListener('click', () => {
  liveEngine.triggerSnare().catch((error) => { audioState.value = `SNARE ERROR: ${error.message}`; });
  dispatchAction('dsp.process', { signal: 'snare', frames: 128 });
});

async function lookupRhymes() {
  const word = document.querySelector('#rhyme-word').value || 'beton';
  const out = document.querySelector('#rhyme-output');
  const event = await dispatchAction('rhyme.lookup', { word });
  const rhymes = event.detail?.rhymes;
  if (Array.isArray(rhymes) && rhymes.length) {
    out.value = rhymes.join(' · ');
    return;
  }
  try {
    const response = await fetch(`/rhymes?word=${encodeURIComponent(word)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('offline fallback');
    const payload = await response.json();
    out.value = payload.rhymes.join(' · ');
  } catch {
    const local = word.toLowerCase().endsWith('on') ? ['BETON', 'SEKTOR', 'DÄMON', 'NEON', 'PHONON'] : ['KAOSS', 'RAUS', 'HAUS', 'APPLAUS'];
    out.value = local.join(' · ');
  }
}

document.querySelector('#lookup-rhyme').addEventListener('click', lookupRhymes);
populateBrowserInputs();

// --------------------------------------------------------------------------- //
// Plug & Play I/O Matrix
// --------------------------------------------------------------------------- //
const inputSelect = document.querySelector('#input-select');
const deviceGrid = document.querySelector('#device-grid');
const permissionGrid = document.querySelector('#permission-grid');
const permissionMode = document.querySelector('#permission-mode');

function fallbackDeviceStatus(selected = inputSelect?.value || 'internal_mic') {
  const permissionRows = [
    { key: 'record_audio', android: 'android.permission.RECORD_AUDIO', granted: false, note: 'Browser/Native Runtime Prompt' },
    { key: 'modify_audio', android: 'android.permission.MODIFY_AUDIO_SETTINGS', granted: true, note: 'Declared for native route switching' },
    { key: 'bluetooth_connect', android: 'android.permission.BLUETOOTH_CONNECT', granted: true, note: 'Android 12+ declared' },
    { key: 'bluetooth_scan', android: 'android.permission.BLUETOOTH_SCAN', granted: true, note: 'BLE discovery declared' },
    { key: 'usb_host', android: 'android.hardware.usb.host', granted: true, note: 'USB host feature declared' },
  ];
  const devices = [
    { id: 'usb_c_audio', label: 'USB-C Audio Interface', status: selected === 'usb_c_audio' ? 'LOCKED' : 'AVAILABLE', sample_rate_hz: 96000, bit_depth: '32-bit float', latency_ms: 1.2, route: 'UAC2 direct monitor / 127.0.0.1:8081', configurable: true },
    { id: 'internal_mic', label: 'Internes Mikrofon', status: selected === 'internal_mic' ? 'LOCKED' : 'AVAILABLE', sample_rate_hz: 48000, bit_depth: '24-bit capture shim', latency_ms: 2.6, route: 'AudioRecord / default input', configurable: true },
    { id: 'bluetooth_client', label: 'Bluetooth Client / BLE Mic', status: selected === 'bluetooth_client' ? 'LOCKED' : 'PAIRABLE', sample_rate_hz: 48000, bit_depth: 'LC3plus shim', latency_ms: 4.8, route: 'BLE jitter buffer +42ms compensation', configurable: true },
  ];
  return { ok: true, selected, plug_and_play: true, permissions: permissionRows, devices };
}

async function browserMicPermission() {
  try {
    if (navigator.permissions?.query) {
      const result = await navigator.permissions.query({ name: 'microphone' });
      return result.state;
    }
  } catch {
    // Some browsers intentionally hide microphone permission query.
  }
  return 'prompt';
}

async function readDeviceStatus(selected = inputSelect.value) {
  if (bridge?.deviceStatus) return bridge.deviceStatus(selected);
  try {
    const response = await fetch(`/devices/status?selected=${encodeURIComponent(selected)}`, { cache: 'no-store' });
    if (response.ok) return response.json();
  } catch {
    // Static preview fallback below.
  }
  return fallbackDeviceStatus(selected);
}

function renderDevice(device) {
  const active = device.status === 'LOCKED';
  return `
    <article class="device-card ${active ? 'locked' : ''}">
      <div class="port-head"><span>${device.id.replaceAll('_', ' ')}</span><b>${device.status}</b></div>
      <strong>${device.label}</strong>
      <small>${device.sample_rate_hz / 1000} kHz // ${device.bit_depth}</small>
      <p>${device.route}</p>
      <code>${device.latency_ms} ms // ${device.configurable ? 'konfigurierbar' : 'fest'}</code>
    </article>
  `;
}

function renderPermission(permission) {
  return `
    <article class="permission-card ${permission.granted ? 'locked' : 'reserved'}">
      <div class="port-head"><span>${permission.key}</span><b>${permission.granted ? 'BEREIT' : 'PROMPT'}</b></div>
      <strong>${permission.android}</strong>
      <small>${permission.note}</small>
    </article>
  `;
}

async function refreshDeviceMatrix() {
  const status = await readDeviceStatus(inputSelect.value);
  const micState = await browserMicPermission();
  const permissions = status.permissions.map((permission) =>
    permission.key === 'record_audio'
      ? { ...permission, granted: permission.granted && micState !== 'denied', note: `${permission.note} // browser=${micState}` }
      : permission,
  );
  deviceGrid.innerHTML = status.devices.map(renderDevice).join('');
  permissionGrid.innerHTML = permissions.map(renderPermission).join('');
  permissionMode.value = `PERMISSION: ${micState.toUpperCase()} // ${status.selected}`;
}

inputSelect.addEventListener('change', async () => {
  await dispatchAction('input.select', { input: inputSelect.value });
  refreshDeviceMatrix();
});
document.querySelector('#permission-check').addEventListener('click', async () => {
  const event = await dispatchAction('permission.check');
  const detail = event.detail || {};
  permissionMode.value = detail.pending?.length
    ? `PERMISSION: PENDING ${detail.pending.join(', ')}`
    : `PERMISSION: ALLE BEREIT // ${chainState.input}`;
  refreshDeviceMatrix();
});
refreshDeviceMatrix();
setInterval(refreshDeviceMatrix, 5000);

// --------------------------------------------------------------------------- //
// Presets, Bänke, Export
// --------------------------------------------------------------------------- //
const presetSelect = document.querySelector('#preset-select');
const vaultState = document.querySelector('#vault-state');
const bankGrid = document.querySelector('#bank-grid');
const liveLog = document.querySelector('#live-log');
let presetCache = null;

function fallbackPresets() {
  return {
    presets: [
      { id: '90s_tape', name: '90s Tape Reel', bpm: 92.4, drive: 0.38, filter: 0.62, delay: 0.28 },
      { id: 'acid_berlin', name: 'Acid Berlin', bpm: 128, drive: 0.44, filter: 0.82, delay: 0.18 },
      { id: 'cyber_drill', name: 'Cyber Drill', bpm: 142, drive: 0.52, filter: 0.46, delay: 0.12 },
      { id: 'lofi_cypher', name: 'Lo-Fi Cypher', bpm: 84, drive: 0.24, filter: 0.36, delay: 0.42 },
    ],
    sample_banks: SAMPLE_BANKS.map(({ bank, label, slots }) => ({ bank, label, slots })),
  };
}

async function loadPresets() {
  if (presetCache) return presetCache;
  try {
    const response = await fetch('/api/presets', { cache: 'no-store' });
    if (!response.ok) throw new Error('preset fallback');
    presetCache = await response.json();
  } catch {
    presetCache = { ok: true, ...fallbackPresets() };
  }
  presetSelect.innerHTML = presetCache.presets
    .map((preset) => `<option value="${preset.id}">${preset.name} // ${preset.bpm} BPM</option>`)
    .join('');
  bankGrid.innerHTML = presetCache.sample_banks
    .map((bank) => `<article class="bank-card"><span>BANK ${bank.bank}</span><strong>${bank.label}</strong><small>${bank.slots.join(' · ')}</small></article>`)
    .join('');
  return presetCache;
}

async function applyPreset({ dispatch = true } = {}) {
  const data = await loadPresets();
  const preset = data.presets.find((item) => item.id === presetSelect.value) || data.presets[0];
  liveEngine?.applyXY(preset.filter, preset.delay);
  // Beim Boot wird das Preset nur lokal gesetzt: die Aktionskette soll erst mit
  // einer echten Benutzerinteraktion (oder der vollständigen Kette) starten.
  if (!dispatch) {
    vaultState.value = `PRESET: ${String(preset.name || preset.id).toUpperCase()} // ${preset.bpm} BPM (READY)`;
    return preset;
  }
  const event = await dispatchAction('preset.apply', { preset: preset.id });
  const applied = event.detail?.preset || preset;
  vaultState.value = `PRESET: ${String(applied.name || applied.id).toUpperCase()} // ${applied.bpm} BPM`;
  return applied;
}

function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function exportSession() {
  const input = inputSelect?.value || 'internal_mic';
  const preset = presetSelect?.value || '90s_tape';
  try {
    const response = await fetch('/api/session/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ preset, input }),
    });
    if (!response.ok) throw new Error('export fallback');
    const payload = await response.json();
    const session = payload.detail?.session || payload.session;
    downloadJson(`kaoss-${preset}-${input}.cypher`, session);
    vaultState.value = `VAULT: EXPORTED ${preset} // ${session?.chain_length ?? 0} CHAIN STEPS`;
    return session;
  } catch {
    downloadJson(`kaoss-${preset}-${input}.cypher`, { format: '.cypher', preset, input, offline: true, limiter_dbfs: -3.2, freezeState, events: chainState.events });
    vaultState.value = `VAULT: EXPORTED FALLBACK ${preset}`;
    return null;
  }
}

async function loadLogs() {
  try {
    const response = await fetch('/api/logs', { cache: 'no-store' });
    if (!response.ok) throw new Error('log fallback');
    const payload = await response.json();
    liveLog.textContent = payload.logs.join('\n');
  } catch {
    liveLog.textContent = ['BOOT static preview', 'PORTVIEW safe fallback', 'DSP WebAudio ready', 'VAULT local export ready'].join('\n');
  }
}

document.querySelector('#apply-preset').addEventListener('click', applyPreset);
document.querySelector('#export-session').addEventListener('click', exportSession);
document.querySelector('#import-session')?.addEventListener('click', async () => {
  try {
    const latest = await fetch('/api/session/latest', { cache: 'no-store' });
    if (!latest.ok) throw new Error('keine persistierte Session');
    const body = await latest.json();
    const replay = await fetch('/api/session/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: body.session || body }),
    });
    const payload = await replay.json();
    vaultState.value = payload.ok
      ? `VAULT: REPLAY ${payload.replay?.steps || 0} STEPS`
      : `VAULT: REPLAY BLOCKED ${JSON.stringify(payload.replay?.blocked || [])}`;
    hydrateFromServer();
  } catch (error) {
    vaultState.value = `VAULT: REPLAY ERROR ${error.message}`;
  }
});
loadPresets().then(() => applyPreset({ dispatch: false }));
loadLogs();
setInterval(loadLogs, 6000);

// --------------------------------------------------------------------------- //
// Boot: State von der Engine holen, damit die UI die laufende Kette zeigt
// --------------------------------------------------------------------------- //
async function hydrateFromServer() {
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (!response.ok) throw new Error('state fallback');
    const state = await response.json();
    if (state?.chain?.length) {
      const events = await fetch(`/api/events?since=0`, { cache: 'no-store' }).then((res) => (res.ok ? res.json() : { events: [] }));
      chainState = defaultState();
      (events.events || []).forEach((event) => { chainState = chainReducer(chainState, event); });
    }
    if (state?.input?.selected) inputSelect.value = state.input.selected;
    renderChain();
  } catch {
    renderChain();
  }
}

hydrateFromServer();

// Debug-/Test-Hook: headless Kettenausführung aus der Browserkonsole oder Playwright.
globalThis.__KAOSS_CHAIN__ = {
  state: () => chainState,
  summary: () => summarize(chainState),
  dispatch: dispatchAction,
  runFullChain,
  script: FULL_CHAIN_SCRIPT,
  catalogue: ACTION_BY_NAME,
  engines: ENGINES,
  missing: (action) => missingMilestones(chainState, action),
};

if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js');
