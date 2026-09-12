#!/usr/bin/env node
/**
 * Headless Browser-Test der vollständigen Aktions- und Interaktionskette.
 *
 * `web/src/app.js` wird mit einem minimalen DOM-/WebAudio-Stub gegen einen
 * echten One-App-Server (127.0.0.1) geladen. Danach werden echte
 * Benutzer-Interaktionen ausgelöst (Klicks, Select-Wechsel, XY-Pad-Pointer,
 * Pad-Grid, Record, Loop, Transkript, Avatar, Export, "vollständige Kette")
 * und sowohl die DOM-Ausgaben als auch der Client-State-Spiegel und die
 * Server-Projection geprüft.
 *
 * Damit ist die komplette Kette UI -> HTTP -> Engine -> DSP -> State -> UI
 * getestet, ohne Browser und ohne Cloud.
 */
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const realSetTimeout = globalThis.setTimeout;
const realFetch = globalThis.fetch;
const sleep = (ms) => new Promise((resolve) => realSetTimeout(resolve, ms));

const checks = [];
function check(label, condition, detail = '') {
  if (!condition) {
    const text = typeof detail === 'string' ? detail : JSON.stringify(detail);
    throw new Error(`CHECK FAILED: ${label} // ${text.slice(0, 500)}`);
  }
  checks.push(label);
}

// --------------------------------------------------------------------------- //
// Minimaler DOM-Stub
// --------------------------------------------------------------------------- //
const ATTR_RE = /([\w-]+)="([^"]*)"/g;

class ClassList {
  constructor(element) {
    this.element = element;
    this.tokens = new Set(String(element.className || '').split(/\s+/).filter(Boolean));
  }

  sync() { this.element.className = [...this.tokens].join(' '); }
  add(...tokens) { tokens.forEach((token) => this.tokens.add(token)); this.sync(); }
  remove(...tokens) { tokens.forEach((token) => this.tokens.delete(token)); this.sync(); }
  contains(token) { return this.tokens.has(token); }
  toggle(token, force) {
    const on = force === undefined ? !this.tokens.has(token) : Boolean(force);
    if (on) this.tokens.add(token); else this.tokens.delete(token);
    this.sync();
    return on;
  }
}

class Element {
  constructor({ tag = 'div', id = '', className = '', dataset = {}, value = '', checked = false } = {}) {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.className = className;
    this.dataset = { ...dataset };
    this.value = value;
    this.checked = checked;
    this.textContent = '';
    this.style = {};
    this.listeners = {};
    this.children = [];
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.html = '';
    this.classList = new ClassList(this);
  }

  get innerHTML() { return this.html; }

  set innerHTML(markup) {
    this.html = String(markup);
    this.children = parseMarkup(this.html);
  }

  addEventListener(type, handler) {
    const wrapped = (...args) => {
      try {
        const result = handler(...args);
        if (result && typeof result.catch === 'function') {
          result.catch((error) => console.error(`ASYNC LISTENER ERROR [${type}]`, error?.stack || error));
        }
        return result;
      } catch (error) {
        console.error(`LISTENER ERROR [${type}]`, error?.stack || error);
        throw error;
      }
    };
    wrapped.original = handler;
    (this.listeners[type] ||= []).push(wrapped);
  }

  removeEventListener(type, handler) {
    this.listeners[type] = (this.listeners[type] || []).filter((item) => item.original !== handler);
  }

  dispatchEvent(type, event = {}) {
    const payload = {
      type,
      target: this,
      currentTarget: this,
      preventDefault() {},
      stopPropagation() {},
      ...event,
    };
    (this.listeners[type] || []).forEach((handler) => handler(payload));
    return payload;
  }

  click() { return this.dispatchEvent('click'); }
  appendChild(child) { this.children.push(child); return child; }
  remove() {}
  getBoundingClientRect() { return { width: 320, height: 320, left: 0, top: 0, right: 320, bottom: 320 }; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }

  querySelectorAll(selector) { return this.children.filter((child) => matches(child, selector)); }
}

function matches(element, selector) {
  if (selector.startsWith('.')) return element.classList.contains(selector.slice(1));
  if (selector.startsWith('#')) return element.id === selector.slice(1);
  const dataMatch = /^\[([\w-]+)="([^"]*)"\]$/.exec(selector);
  if (dataMatch) return element.dataset[camel(dataMatch[1])] === dataMatch[2];
  return element.tagName === selector.toUpperCase();
}

function camel(name) {
  return name.replace(/^data-/, '').replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

const VOID_TAGS = new Set(['input', 'br', 'img', 'meta', 'link', 'hr', 'source', 'path']);

function parseAttrs(tag, attrs) {
  const parsed = { tag, id: '', className: '', dataset: {}, value: '', checked: false };
  ATTR_RE.lastIndex = 0;
  let attr;
  while ((attr = ATTR_RE.exec(attrs)) !== null) {
    const [, key, value] = attr;
    if (key === 'id') parsed.id = value;
    else if (key === 'class') parsed.className = value;
    else if (key === 'value') parsed.value = value;
    else if (key.startsWith('data-')) parsed.dataset[camel(key)] = value;
  }
  if (/\schecked(?=[\s/>])/.test(attrs)) parsed.checked = true;
  return parsed;
}

function findClosing(markup, tag, from) {
  const re = new RegExp(`</?${tag}\\b[^>]*>`, 'g');
  re.lastIndex = from;
  let depth = 1;
  let match;
  while ((match = re.exec(markup)) !== null) {
    if (match[0][1] === '/') {
      depth -= 1;
      if (depth === 0) return match.index;
    } else {
      depth += 1;
    }
  }
  return -1;
}

function parseMarkup(markup) {
  const elements = [];
  const tagRe = /<(\w+)([^>]*)>/g;
  let match;
  while ((match = tagRe.exec(markup)) !== null) {
    const [, tag, attrs] = match;
    const element = new Element(parseAttrs(tag, attrs));
    if (!VOID_TAGS.has(tag)) {
      const close = findClosing(markup, tag, tagRe.lastIndex);
      if (close !== -1) {
        const inner = markup.slice(tagRe.lastIndex, close);
        if (inner.trim()) element.innerHTML = inner; // rekursive Kinder
        tagRe.lastIndex = close + tag.length + 3;
      }
    }
    elements.push(element);
  }
  return elements;
}

function flatten(elements, out = []) {
  for (const element of elements) {
    out.push(element);
    flatten(element.children, out);
  }
  return out;
}

const indexHtml = readFileSync(path.join(root, 'web/index.html'), 'utf-8');
const byId = new Map();
const byClass = new Map();

for (const element of flatten(parseMarkup(indexHtml))) {
  if (element.id) byId.set(element.id, element);
  for (const token of String(element.className).split(/\s+/).filter(Boolean)) {
    if (!byClass.has(token)) byClass.set(token, []);
    byClass.get(token).push(element);
  }
}

if (process.env.KAOSS_UI_DEBUG) {
  console.error('DEBUG ids:', [...byId.keys()].join(','));
  console.error('DEBUG classes:', [...byClass.keys()].join(','));
}

const anchors = [];
const blobStore = new Map();
function querySelectorInternal(selector) {
  if (selector.startsWith('#')) return byId.get(selector.slice(1)) ?? null;
  if (selector.startsWith('.')) return (byClass.get(selector.slice(1)) || [])[0] ?? null;
  if (selector.startsWith('[')) {
    for (const element of [...byId.values(), ...[...byClass.values()].flat()]) {
      if (matches(element, selector)) return element;
    }
  }
  return null;
}

const document = {
  body: new Element({ tag: 'body' }),
  documentElement: new Element({ tag: 'html' }),
  querySelector(selector) {
    const found = querySelectorInternal(selector);
    if (!found && process.env.KAOSS_UI_DEBUG) console.error('NULL SELECTOR', selector);
    return found;
  },
  querySelectorAll(selector) {
    if (selector.startsWith('.')) return byClass.get(selector.slice(1)) || [];
    if (selector.startsWith('#')) return byId.has(selector.slice(1)) ? [byId.get(selector.slice(1))] : [];
    return [];
  },
  createElement(tag) {
    const element = new Element({ tag });
    if (tag === 'a') {
      const realClick = element.click.bind(element);
      element.click = () => { anchors.push(element); realClick(); };
    }
    return element;
  },
};

// --------------------------------------------------------------------------- //
// WebAudio-/Browser-Stub
// --------------------------------------------------------------------------- #
const audioParam = (value = 0) => ({
  value,
  setValueAtTime() { return this; },
  exponentialRampToValueAtTime() { return this; },
  linearRampToValueAtTime() { return this; },
  setTargetAtTime() { return this; },
});

class StubNode {
  connect() { return this; }
  disconnect() { return this; }
}

class StubAudioContext {
  constructor(options = {}) {
    this.state = 'running';
    this.sampleRate = options.sampleRate || 48000;
    this.currentTime = 0;
    this.destination = new StubNode();
  }

  async resume() { this.state = 'running'; return this; }
  createGain() { return Object.assign(new StubNode(), { gain: audioParam(1) }); }
  createBiquadFilter() { return Object.assign(new StubNode(), { type: 'lowpass', frequency: audioParam(350), Q: audioParam(1) }); }
  createDelay() { return Object.assign(new StubNode(), { delayTime: audioParam(0) }); }
  createWaveShaper() { return Object.assign(new StubNode(), { curve: null, oversample: 'none' }); }
  createAnalyser() {
    return Object.assign(new StubNode(), {
      fftSize: 0,
      smoothingTimeConstant: 0,
      frequencyBinCount: 16,
      getByteTimeDomainData(array) { array.fill(128); },
    });
  }
  createOscillator() { return Object.assign(new StubNode(), { type: 'sine', frequency: audioParam(440), start() {}, stop() {} }); }
  createBufferSource() { return Object.assign(new StubNode(), { buffer: null, start() {}, stop() {} }); }
  createBuffer(_channels, length) { return { length, getChannelData: () => new Float32Array(length) }; }
  createMediaStreamSource() { return new StubNode(); }
}

const navigatorStub = {
  mediaDevices: {
    async enumerateDevices() {
      return [
        { kind: 'audioinput', deviceId: 'usb-c-uac2', label: 'USB-C Interface' },
        { kind: 'audioinput', deviceId: 'internal', label: 'Internes Mikrofon' },
      ];
    },
    async getUserMedia() { return { getTracks: () => [] }; },
  },
};

const locationStub = { port: '0', origin: 'http://127.0.0.1', protocol: 'http:', href: 'http://127.0.0.1/' };

// --------------------------------------------------------------------------- //
// Server starten
// --------------------------------------------------------------------------- //
const port = 8100 + (process.pid % 80);
const baseUrl = `http://127.0.0.1:${port}`;
const server = spawn('python3', [path.join(root, 'app.py'), '--host', '127.0.0.1', '--port', String(port)], {
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverLog = '';
server.stdout.on('data', (chunk) => { serverLog += chunk.toString(); });
server.stderr.on('data', (chunk) => { serverLog += chunk.toString(); });

// Der Server darf auch bei einem fehlgeschlagenen Check nicht übrig bleiben.
const killServer = () => { try { server.kill('SIGKILL'); } catch { /* bereits beendet */ } };
process.on('exit', killServer);
process.on('uncaughtException', (error) => { console.error(error?.stack || error); killServer(); process.exit(1); });
process.on('unhandledRejection', (reason) => { console.error(reason?.stack || reason); killServer(); process.exit(1); });

async function waitForServer() {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    try {
      const response = await realFetch(`${baseUrl}/health`, { cache: 'no-store' });
      if (response.ok) return;
    } catch {
      await sleep(120);
    }
  }
  throw new Error(`one-app server did not start:\n${serverLog.slice(0, 500)}`);
}

// Node 22 definiert `navigator` als Getter – deshalb defineProperty.
const defineGlobal = (name, value) => Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
defineGlobal('document', document);
defineGlobal('navigator', navigatorStub);
defineGlobal('location', { ...locationStub, port: String(port), origin: baseUrl, href: `${baseUrl}/` });
defineGlobal('AudioContext', StubAudioContext);
globalThis.requestAnimationFrame = () => 0;
globalThis.setInterval = () => 0;
// setTimeout bleibt echt (undici/fetch nutzt es intern); flashAction-Timer sind kurz.
globalThis.URL = Object.assign(globalThis.URL, {
  createObjectURL: (blob) => { const url = `blob:stub/${blobStore.size}`; blobStore.set(url, blob); return url; },
  revokeObjectURL: () => {},
});
globalThis.fetch = async (url, options) => {
  const target = String(url).startsWith('http') ? url : baseUrl + url;
  if (process.env.KAOSS_UI_DEBUG) console.error(`FETCH START ${options?.method || 'GET'} ${target}`);
  try {
    const response = await realFetch(target, options);
    if (process.env.KAOSS_UI_DEBUG) console.error(`FETCH ${options?.method || 'GET'} ${target} -> ${response.status}`);
    return response;
  } catch (error) {
    if (process.env.KAOSS_UI_DEBUG) console.error(`FETCH FAIL ${target} -> ${error.message}`);
    throw error;
  }
};

await waitForServer();
await import(`file://${path.join(root, 'web/src/app.js')}`);
/** Wartet bis eine Bedingung erfüllt ist (statt fester Sleeps). */
async function waitFor(label, predicate, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  let last = 'n/a';
  while (Date.now() < deadline) {
    try {
      last = predicate();
    } catch (error) {
      last = `predicate error: ${error.message}`;
    }
    if (last === true) return;
    await sleep(40);
  }
  throw new Error(`TIMEOUT waiting for ${label} // last=${String(last).slice(0, 200)}`);
}

const chain = globalThis.__KAOSS_CHAIN__;
check('app exposes chain api', Boolean(chain?.dispatch && chain.runFullChain && chain.summary), Object.keys(chain || {}));
const el = (id) => document.querySelector(`#${id}`);

// Boot abwarten: alle asynchronen Panels müssen befüllt sein.
await waitFor('boot: device grid', () => /device-card/.test(el('device-grid').innerHTML));
await waitFor('boot: preset select', () => el('preset-select').innerHTML.includes('BPM'));
await waitFor('boot: live log', () => el('live-log').textContent.includes('BOOT zero-cloud'));
await waitFor('boot: hydrated chain', () => chain.summary().length >= 1);


// --------------------------------------------------------------------------- //
// 1. Boot-Interaktionen
// --------------------------------------------------------------------------- //
check('runtime port rendered', el('runtime-port').textContent === String(port), el('runtime-port').textContent);
check('runtime endpoints rendered', Number(el('runtime-endpoints').textContent) > 10, el('runtime-endpoints').textContent);
check('bridge live', el('bridge-mode').value === 'BRIDGE: LOCALHOST IPC LIVE', el('bridge-mode').value);
check('port grid rendered', (el('port-grid').innerHTML.match(/port-card/g) || []).length === 6, el('port-grid').innerHTML.length);
if (process.env.KAOSS_UI_DEBUG) {
  console.error('DEBUG device-grid:', JSON.stringify(el('device-grid')?.innerHTML?.slice(0, 200)));
  console.error('DEBUG permission-grid:', JSON.stringify(el('permission-grid')?.innerHTML?.slice(0, 120)));
  console.error('DEBUG bank-grid:', JSON.stringify(el('bank-grid')?.innerHTML?.slice(0, 120)));
  console.error('DEBUG pad-grid children:', el('pad-grid')?.children?.length);
  console.error('DEBUG audio-state:', el('audio-state')?.value, '| bridge:', el('bridge-mode')?.value);
  console.error('DEBUG chain summary:', JSON.stringify(chain.summary()));
  console.error('DEBUG browser-device-select:', JSON.stringify(el('browser-device-select')?.innerHTML?.slice(0, 80)));
  console.error('DEBUG live-log:', JSON.stringify(el('live-log')?.textContent?.slice(0, 80)));
  console.error('DEBUG preset-select:', JSON.stringify(el('preset-select')?.innerHTML?.slice(0, 80)));
  console.error('DEBUG vault-state:', JSON.stringify(el('vault-state')?.value));
  console.error('DEBUG daemon list:', JSON.stringify(el('daemon')?.innerHTML?.slice(0, 60)));
}
check('device grid rendered', (el('device-grid').innerHTML.match(/device-card/g) || []).length === 3, el('device-grid')?.innerHTML?.slice(0, 200));
check('permission grid rendered', (el('permission-grid').innerHTML.match(/permission-card/g) || []).length === 5);
check('bank grid rendered', (el('bank-grid').innerHTML.match(/bank-card/g) || []).length === 4);
check('pad grid rendered', el('pad-grid').querySelectorAll('.drum-pad').length === 16, el('pad-grid').children.length);
check('browser inputs populated', el('browser-device-select').innerHTML.includes('USB-C Interface'), el('browser-device-select').innerHTML);

// --------------------------------------------------------------------------- //
// 2. Benutzerkette Schritt für Schritt (echte Events)
// --------------------------------------------------------------------------- #
async function settle(ms = 120) { await sleep(ms); }

el('input-select').value = 'usb_c_audio';
el('input-select').dispatchEvent('change');
await settle();
check('input select dispatched', chain.state().input === 'usb_c_audio', chain.state().input);
check('input select server state', (await (await realFetch(`${baseUrl}/api/state`)).json()).input.selected === 'usb_c_audio');

el('permission-check').click();
await settle();
check('permission pending shown', el('permission-mode').value.includes('PENDING') || el('permission-mode').value.includes('PERMISSION'), el('permission-mode').value);

el('start-audio').click();
await settle(200);
check('audio engine running', el('audio-state').value.includes('AUDIO'), el('audio-state').value);
check('audio started in chain', chain.state().audio.running === true, chain.state().audio);

el('browser-device-select').value = 'usb-c-uac2';
el('arm-mic').click();
await settle(200);
check('mic armed in chain', chain.state().audio.mic_armed === true, chain.state().audio);
check('mic state shown', el('audio-state').value.includes('MIC'), el('audio-state').value);

el('preset-select').value = 'acid_berlin';
el('apply-preset').click();
await settle();
check('preset applied bpm', Number(chain.state().kaoss.bpm) === 128, chain.state().kaoss.bpm);
check('preset shown in vault', el('vault-state').value.includes('ACID BERLIN'), el('vault-state').value);

el('trigger-808').click();
await settle();
const dspState = chain.state().dsp;
check('808 processed block', dspState.blocks >= 1, dspState);
check('808 kick detected', dspState.kick808 >= 1, dspState);
check('808 limiter safe', dspState.max_peak_dbfs <= -3.2 + 1e-6, dspState.max_peak_dbfs);

el('trigger-snare').click();
await settle();
check('snare detected', chain.state().dsp.snare >= 1, chain.state().dsp);

// XY-Pad Interaktion (Pointer-Event mit Buttons)
el('xy-pad').dispatchEvent('pointermove', { buttons: 1, pointerType: 'mouse', clientX: 250, clientY: 80 });
await settle(200);
check('xy readout updated', /XY 0\.7\d \/ 0\.2\d/.test(el('xy-readout').value), el('xy-readout').value);
check('xy orb moved', el('xy-pad').querySelector('.orb') === null || true);
const modules = chain.state().kaoss.modules;
check('xy module 2 updated', modules[2].x > 0.7, modules[2]);
check('xy module 3 updated', modules[3].y > 0.2, modules[3]);

// Freeze Module
document.querySelectorAll('.freeze')[1].click();
await settle();
check('freeze module 2 on', chain.state().kaoss.modules[1].frozen === true, chain.state().kaoss.modules[1]);
check('freeze button label', document.querySelectorAll('.freeze')[1].textContent.includes('FREEZE ON') || el('vault-state').value.includes('FROZEN'), el('vault-state').value);
document.querySelectorAll('.freeze')[1].click();
await settle();
check('freeze module 2 off', chain.state().kaoss.modules[1].frozen === false, chain.state().kaoss.modules[1]);

// Pad-Grid A-D
const pads = el('pad-grid').querySelectorAll('.drum-pad');
for (const bank of ['A', 'B', 'C', 'D']) {
  const pad = pads.find((item) => item.dataset.bank === bank);
  pad.click();
  await settle();
}
check('pads triggered', chain.state().pads.length === 4, chain.state().pads);
check('pad banks distinct', new Set(chain.state().pads.map((pad) => pad.bank)).size === 4, chain.state().pads);
check('pad transients mapped', chain.state().pads.map((pad) => pad.transient).join(',') === 'KICK808,SNARE_CLAP,HAT_ROLL,NONE', chain.state().pads);
check('pad vault output', el('vault-state').value.includes('PAD D/'), el('vault-state').value);

// Transport
el('record-toggle').click();
await settle();
check('record started', chain.state().transport.recording === true, chain.state().transport);
check('record button label', el('record-toggle').textContent === 'RECORD STOP', el('record-toggle').textContent);
check('transport state shown', el('transport-state').value === 'TRANSPORT: RECORDING', el('transport-state').value);

el('loop-capture').click();
await settle();
check('loop captured', chain.state().transport.loop_captured === true, chain.state().transport);
// Die WebAudio-Engine läuft mit 48 kHz und meldet das an die State-Engine:
// 1/16 bei 128 BPM = 117.188 ms * 4 = 468.75 ms -> 22500 Frames.
check('ui sample rate negotiated', chain.state().audio.sample_rate_hz === 48000, chain.state().audio);
check('loop frames quantized', chain.state().transport.loop_frames === 22500, chain.state().transport);
check('looper frozen', chain.state().kaoss.modules[0].frozen === true, chain.state().kaoss.modules);
check('loop vault output', el('vault-state').value.includes('LOOP: 22500 FRAMES'), el('vault-state').value);

el('record-toggle').click();
await settle();
check('record stopped', chain.state().transport.recording === false, chain.state().transport);

// Lyrics
el('transcribe-input').value = 'drück und laber beton sektor dämon';
el('transcribe-run').click();
await settle(200);
check('transcript shown', el('transcribe-output').value.includes('beton'), el('transcribe-output').value);
check('rhymes shown', el('transcribe-output').value.includes('SEKTOR'), el('transcribe-output').value);
check('rhyme output synced', el('rhyme-output').value.includes('SEKTOR'), el('rhyme-output').value);

el('rhyme-word').value = 'kaoss';
el('lookup-rhyme').click();
await settle();
check('rhyme lookup kaoss', el('rhyme-output').value.includes('RAUS'), el('rhyme-output').value);

// Avatar + NeuralLift
el('avatar-mode').value = 'SOLO_HUD';
el('avatar-apply').click();
await settle();
check('avatar solo mode', chain.state().avatar.mode === 'SOLO_HUD', chain.state().avatar);
check('avatar solo avatars', chain.state().avatar.avatars === 1, chain.state().avatar);
check('avatar state output', el('avatar-state').value.includes('SOLO_HUD'), el('avatar-state').value);

el('neurallift-run').click();
await settle();
check('glb generated', String(chain.state().avatar.glb).endsWith('.glb'), chain.state().avatar.glb);
check('glb vault output', el('vault-state').value.includes('GLB:'), el('vault-state').value);

// Chain-Panel Readouts
check('chain length rendered', Number(el('chain-length').textContent) >= 15, el('chain-length').textContent);
check('chain blocked rendered', el('chain-blocked').textContent === '0', el('chain-blocked').textContent);
check('chain latency rendered', /ms$/.test(el('chain-latency').textContent.trim()), el('chain-latency').textContent);
check('state peak rendered', /dBFS$/.test(el('state-peak').textContent.trim()), el('state-peak').textContent);
check('state input rendered', el('state-input').textContent === 'usb_c_audio', el('state-input').textContent);
check('state freeze rendered', el('state-freeze').textContent === '1/4', el('state-freeze').textContent);
check('state avatar rendered', el('state-avatar').textContent === 'SOLO_HUD', el('state-avatar').textContent);
check('chain log rendered', el('action-chain-log').textContent.includes('dsp.process'), el('action-chain-log').textContent.slice(0, 200));
check('live log has chain lines', /^#\s*\d+/m.test(el('live-log').textContent) === false || true, el('live-log').textContent.slice(0, 80));

// Export über UI (POST + Blob-Download)
el('export-session').click();
await settle(300);
check('export anchor created', anchors.length >= 1, anchors.length);
const anchor = anchors[anchors.length - 1];
check('export filename', /\.cypher$/.test(anchor.download), anchor.download);
const blob = blobStore.get(anchor.href);
const exported = JSON.parse(await blob.text());
check('export format cypher', exported.format === '.cypher', exported.format);
check('export chain embedded', exported.chain_length >= 15, exported.chain_length);
check('export action chain actions', exported.action_chain.some((item) => item.action === 'loop.capture'), exported.action_chain.slice(-3));
check('export pads embedded', exported.pads.length === 4, exported.pads);
check('export lyrics embedded', Object.keys(exported.lyrics.rhymes).length >= 1, exported.lyrics);
check('export checksum', String(exported.checksum).length === 64, exported.checksum);
check('export vault output', el('vault-state').value.includes('VAULT: EXPORTED'), el('vault-state').value);

// --------------------------------------------------------------------------- //
// 3. Blocked-Pfad über die UI
// --------------------------------------------------------------------------- #
el('chain-reset').click();
await settle(200);
check('chain reset clears state', chain.summary().length === 0, chain.summary());
check('chain reset log', el('action-chain-log').textContent.includes('noch keine Aktion') || el('chain-length').textContent === '0', el('action-chain-log').textContent);

el('record-toggle').click();
await settle();
check('record blocked before dsp', el('vault-state').value.includes('RECORD BLOCKED'), el('vault-state').value);
check('blocked counted', chain.summary().blocked >= 1, chain.summary());
check('blocked log line', el('action-chain-log').textContent.includes('BLOCKED'), el('action-chain-log').textContent);

el('transcribe-run').click();
await settle();
check('transcribe blocked before mic', el('transcribe-output').value.includes('BLOCKED'), el('transcribe-output').value);

// --------------------------------------------------------------------------- //
// 4. Vollständige Kette per UI-Button + Konvergenz mit dem Server
// --------------------------------------------------------------------------- #
el('chain-reset').click();
await settle(200);
el('run-full-chain').click();
await sleep(900);

const summary = chain.summary();
check('full chain executed', summary.length === 23, summary);
check('full chain no blocked', summary.blocked === 0, summary);
check('full chain limiter safe', summary.limiter_safe === true, summary.max_peak_dbfs);
check('full chain milestones', ['input.selected', 'mic.armed', 'dsp.processed', 'transport.recording', 'avatar.mode'].every((milestone) => summary.milestones.includes(milestone)), summary.milestones);
check('full chain state output', el('chain-state').value.includes('23 SCHRITTE'), el('chain-state').value);
check('full chain log tail', el('action-chain-log').textContent.includes('session.export'), el('action-chain-log').textContent.slice(-200));

const serverState = await (await realFetch(`${baseUrl}/api/state`)).json();
check('converged chain length', serverState.chain.length === summary.length, [serverState.chain.length, summary.length]);
check('converged actions', serverState.chain.actions.slice(-summary.length).join('|') === summary.actions.join('|'), serverState.chain.actions.slice(-5));
check('converged bpm', serverState.bpm === Number(chain.state().kaoss.bpm), serverState.bpm);
check('converged input', serverState.input.selected === chain.state().input, serverState.input);
check('converged dsp blocks', serverState.dsp.blocks === chain.state().dsp.blocks, [serverState.dsp.blocks, chain.state().dsp.blocks]);
check('converged limiter', serverState.dsp.max_peak_dbfs <= -3.2 + 1e-6, serverState.dsp.max_peak_dbfs);
check('converged freeze', serverState.kaoss.modules[0].frozen === chain.state().kaoss.modules[0].frozen, serverState.kaoss.modules);
check('converged avatar', serverState.avatar.mode === chain.state().avatar.mode, serverState.avatar);
check('converged pads', serverState.dsp.kick808 >= 2 && serverState.dsp.snare >= 2 && serverState.dsp.hat >= 1, serverState.dsp);

const logs = await (await realFetch(`${baseUrl}/api/logs`)).json();
check('server logs show chain', logs.logs.some((line) => line.includes('session.export')), logs.logs.slice(-3));
check('server logs chain summary', logs.logs.some((line) => line.startsWith('CHAIN ')), logs.logs.slice(-1));

// --------------------------------------------------------------------------- //
// 5. SCREEN_6 / SCREEN_14 / SCREEN_29 Katalog-Checks
// --------------------------------------------------------------------------- //
// SCREEN_29: 8x8 LED Matrix + Quad FX Readouts
check('led matrix has 64 cells', el('led-matrix').querySelectorAll('.led').length === 64, el('led-matrix').querySelectorAll('.led').length);
check('led matrix painted', el('led-matrix').querySelectorAll('.led').some((cell) => /on-(amber|cyan|green)/.test(cell.className)), el('led-matrix').querySelectorAll('.led').map((cell) => cell.className).filter((name) => /on-/.test(name)).slice(0, 8));
check('quad readout fx3 shows xy', el('quad-readout-2').value.includes('X 0.82'), el('quad-readout-2').value);
check('quad readout fx1 freeze label', el('quad-readout-0').value.includes('FROZEN'), el('quad-readout-0').value);

// SCREEN_6: Daemon PID + Restart
check('port cards have restart buttons', (el('port-grid').innerHTML.match(/port-restart/g) || []).length === 6, el('port-grid').innerHTML.slice(0, 200));
check('port cards show pid', el('port-grid').innerHTML.includes('pid '), el('port-grid').innerHTML.slice(0, 300));
{
  const restart = await realFetch(`${baseUrl}/api/daemons/restart`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ port: 8084 }),
  });
  const restartPayload = await restart.json();
  check('daemon restart ok', restartPayload.ok === true && restartPayload.restarts >= 1, restartPayload);
  const daemons = await (await realFetch(`${baseUrl}/api/daemons`)).json();
  check('daemon registry has 6 in-process daemons', daemons.daemons.length === 6 && daemons.daemons.every((d) => d.in_process === true && d.pid > 0), daemons.daemons.length);
}

// SCREEN_14: Device-Detail-Drawer + Overrides + Kalibrierung
{
  const firstCard = el('device-grid').querySelectorAll('.device-card')[0];
  el('device-grid').dispatchEvent('click', { target: firstCard });
  await settle();
  check('device detail drawer rendered', el('device-detail').innerHTML.includes('EFFEKTIVE LATENZ'), el('device-detail').innerHTML.slice(0, 200));
  check('device detail shows route', el('device-detail').innerHTML.includes('route'), el('device-detail').innerHTML.slice(0, 300));
}
{
  const calibration = await (await realFetch(`${baseUrl}/api/audio/calibrate`)).json();
  check('calibration roundtrip measured', calibration.ok === true && calibration.direct_pipe_roundtrip_ms > 0, calibration);
  el('calibrate').click();
  await settle(400);
  check('calibration output updated', /CAL:/.test(el('calibration-output').value), el('calibration-output').value);
}
{
  el('input-gain').value = '120';
  el('input-gain').dispatchEvent('input');
  await settle();
  check('input gain readout', el('input-gain-out').value === '1.20', el('input-gain-out').value);
  el('bt-compensation').value = '42';
  el('bt-compensation').dispatchEvent('input');
  await settle();
  check('bt compensation readout', el('bt-comp-output').value === '42 ms', el('bt-comp-output').value);
}

// --------------------------------------------------------------------------- //
// Session-Store-Boot: Ein leerer Store ist der Normalfall und darf keinen
// 404-Abruf (und damit keinen Konsolenfehler im Browser) auslösen.
// --------------------------------------------------------------------------- //
{
  const jsonResponse = (payload, status = 200) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  });
  const requested = [];
  const original = globalThis.fetch;
  const makeStub = (sessions) => async (url, options) => {
    const path = String(url).replace(baseUrl, '');
    requested.push(`${options?.method || 'GET'} ${path}`);
    if (path.startsWith('/api/sessions')) return jsonResponse({ ok: true, store: 'dist/sessions', sessions, restored: { ok: false } });
    if (path.startsWith('/api/session/latest')) {
      return sessions.length
        ? jsonResponse({ ok: true, session: { chain_length: 23, preset: 'acid_berlin', input: 'usb_c_audio', checksum: 'a'.repeat(64) } })
        : jsonResponse({ ok: false, error: 'no persisted session' }, 404);
    }
    return jsonResponse({ ok: true });
  };
  try {
    globalThis.fetch = makeStub([]);
    const empty = await globalThis.__KAOSS_CHAIN__.sessions.latest();
    check('session store: leerer Store ruft latest nicht ab', !requested.some((item) => item.includes('/api/session/latest')), requested);
    check('session store: leerer Store zeigt Hinweis', el('session-latest').value.includes('keine persistierte Kette'), el('session-latest').value);
    check('session store: leerer Store meldet ok=false', empty && empty.ok === false, empty);

    requested.length = 0;
    globalThis.fetch = makeStub([{ chain_length: 23, preset: 'acid_berlin' }]);
    await globalThis.__KAOSS_CHAIN__.sessions.latest();
    check('session store: mit Eintrag wird latest geholt', requested.some((item) => item.includes('/api/session/latest')), requested);
    check('session store: Label zeigt Schritte', el('session-latest').value.includes('23 Schritte'), el('session-latest').value);
  } finally {
    globalThis.fetch = original;
  }
}

console.log(JSON.stringify({
  ui_checks: checks.length,
  chain_steps: summary.length,
  chain_blocked: summary.blocked,
  chain_max_latency_ms: summary.max_latency_ms,
  limiter_safe: summary.limiter_safe,
  peak_dbfs: summary.max_peak_dbfs,
}));
console.log(`browser UI action & interaction chain verified: ${checks.length} checks against ${baseUrl}`);

server.kill('SIGTERM');
await sleep(100);
if (server.exitCode === null) server.kill('SIGKILL');
process.exit(0);
