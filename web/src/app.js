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
  return `
    <article class="port-card ${tone}">
      <div class="port-head"><span>:${spec.port}</span><b>${status.status}</b></div>
      <strong>${spec.name}</strong>
      <small>${spec.protocol}</small>
      <p>${spec.rule}</p>
      <code>${status.bind}:${spec.port} // ${status.latency}</code>
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

const pad = document.querySelector('.pad');
const orb = document.querySelector('.orb');
pad.addEventListener('pointermove', (event) => {
  if (event.buttons !== 1 && event.pointerType !== 'touch') return;
  const rect = pad.getBoundingClientRect();
  const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
  const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
  orb.style.left = `${x - 48}px`;
  orb.style.top = `${y - 48}px`;
});

if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js');


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
  try {
    await fetch(`/devices/select?input=${encodeURIComponent(inputSelect.value)}`, { cache: 'no-store' });
  } catch {
    // Native/static fallback still updates the view.
  }
  refreshDeviceMatrix();
});
document.querySelector('#permission-check').addEventListener('click', refreshDeviceMatrix);
refreshDeviceMatrix();
setInterval(refreshDeviceMatrix, 5000);
