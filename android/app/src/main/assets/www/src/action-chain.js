/**
 * Kaoss Aktions- & Interaktionskette (client mirror).
 *
 * DOM-freies ES-Modul: es beschreibt die komplette Benutzerkette
 * (Input wählen -> Permission -> Audio starten -> Mic armen -> Preset ->
 *  XY-Pad -> Freeze -> Pads -> Record -> Loop -> Transkript -> Reime ->
 *  Avatar -> NeuralLift -> Export) und kann deshalb sowohl im Browser
 * (web/src/app.js) als auch headless in Node (tests/action_chain_ui_test.mjs)
 * ausgeführt werden.
 *
 * Alle Aktionen sind offline/localhost-only; es wird niemals eine externe
 * Ressource geladen.
 */

export const LIMITER_DBFS = -3.2;

export const ENGINES = {
  orchestrator: { port: 8080, name: 'master-system-orchestrator' },
  audio: { port: 8081, name: 'audio-loopback-daemon' },
  neurallift: { port: 8082, name: 'neurallift-engine' },
  avatar: { port: 8083, name: 'avatar-orchestrator' },
  dsp: { port: 8084, name: 'dsp-transient-bridge' },
  whisper: { port: 8085, name: 'offline-whisper-daemon' },
};

export const ACTION_CATALOGUE = [
  { action: 'boot', engine: 'orchestrator', label: 'BOOT / RESET', requires: [] },
  { action: 'input.select', engine: 'orchestrator', label: 'INPUT WÄHLEN', requires: [], milestone: 'input.selected' },
  { action: 'permission.check', engine: 'orchestrator', label: 'PERMISSIONS PRÜFEN', requires: ['input.selected'], milestone: 'permission.checked' },
  { action: 'permission.grant', engine: 'orchestrator', label: 'MIC PERMISSION', requires: ['permission.checked'], milestone: 'permission.granted' },
  { action: 'audio.start', engine: 'audio', label: 'AUDIO STARTEN', requires: ['input.selected', 'permission.granted'], milestone: 'audio.started' },
  { action: 'mic.arm', engine: 'audio', label: 'MIC ARMEN', requires: ['audio.started'], milestone: 'mic.armed' },
  { action: 'preset.apply', engine: 'dsp', label: 'PRESET LADEN', requires: ['audio.started'] },
  { action: 'kaoss.xy', engine: 'dsp', label: 'XY PAD', requires: ['audio.started'] },
  { action: 'kaoss.freeze', engine: 'dsp', label: 'FX FREEZE', requires: ['audio.started'] },
  { action: 'dsp.process', engine: 'dsp', label: 'DSP BLOCK', requires: ['mic.armed'], milestone: 'dsp.processed' },
  { action: 'pad.trigger', engine: 'dsp', label: 'PAD TRIGGER', requires: ['mic.armed'] },
  { action: 'transport.record', engine: 'orchestrator', label: 'RECORD', requires: ['dsp.processed'], milestone: 'transport.recording' },
  { action: 'loop.capture', engine: 'dsp', label: 'LOOP CAPTURE', requires: ['transport.recording'] },
  { action: 'transcribe', engine: 'whisper', label: 'TRANSKRIBIEREN', requires: ['mic.armed'] },
  { action: 'rhyme.lookup', engine: 'whisper', label: 'REIME', requires: ['permission.checked'] },
  { action: 'avatar.mode', engine: 'avatar', label: 'AVATAR MODUS', requires: ['audio.started'], milestone: 'avatar.mode' },
  { action: 'neurallift.generate', engine: 'neurallift', label: 'NEURALLIFT GLB', requires: ['avatar.mode'] },
  { action: 'session.export', engine: 'orchestrator', label: '.CYPHER EXPORT', requires: ['mic.armed'] },
  { action: 'chain.reset', engine: 'orchestrator', label: 'KETTE RESET', requires: [] },
];

export const ACTION_BY_NAME = Object.fromEntries(ACTION_CATALOGUE.map((spec) => [spec.action, spec]));

/** Kanonische vollständige Aktions- und Interaktionskette (identisch zum Server). */
export const FULL_CHAIN_SCRIPT = [
  { action: 'boot' },
  { action: 'input.select', input: 'usb_c_audio' },
  { action: 'permission.check' },
  { action: 'permission.grant', key: 'record_audio', granted: true },
  { action: 'audio.start', sample_rate_hz: 96000, frames_per_buffer: 128 },
  { action: 'mic.arm', device_id: 'usb-c-uac2' },
  { action: 'preset.apply', preset: 'acid_berlin' },
  { action: 'kaoss.xy', module: 2, x: 0.82, y: 0.46 },
  { action: 'kaoss.xy', module: 3, x: 0.35, y: 0.55 },
  { action: 'dsp.process', signal: 'mouth_bass', frames: 128 },
  { action: 'pad.trigger', bank: 'A', slot: 'MOUTH 808' },
  { action: 'dsp.process', signal: 'snare', frames: 128 },
  { action: 'pad.trigger', bank: 'B', slot: 'CLAP' },
  { action: 'dsp.process', signal: 'hat', frames: 128 },
  { action: 'transport.record', running: true },
  { action: 'loop.capture', subdivision: 16 },
  { action: 'kaoss.freeze', module: 0, frozen: true },
  { action: 'transcribe', text: 'drück und laber beton sektor dämon' },
  { action: 'rhyme.lookup', word: 'beton' },
  { action: 'avatar.mode', mode: 'CYPHER_CIRCLE' },
  { action: 'neurallift.generate', source: 'camera_frame_0001.jpg' },
  { action: 'transport.record', running: false },
  { action: 'session.export' },
];

export const SAMPLE_BANKS = [
  { bank: 'A', label: 'Kick / 808', slots: ['SUB DROP', 'BOOM', 'TAPE KICK', 'MOUTH 808'], signal: 'mouth_bass' },
  { bank: 'B', label: 'Snare / Clap', slots: ['MPC SNARE', 'CLAP', 'RIM', 'NOISE SNAP'], signal: 'snare' },
  { bank: 'C', label: 'Hat / Perc', slots: ['TS HAT', 'SHAKER', 'ROLL 16', 'ROLL 32'], signal: 'hat' },
  { bank: 'D', label: 'Vocal FX', slots: ['DUB', 'FORMANT', 'FREEZE', 'REVERSE'], signal: 'vocal' },
];

export function defaultState() {
  return {
    input: 'internal_mic',
    permissions: { record_audio: false },
    audio: { running: false, mic_armed: false, sample_rate_hz: 96000, frames_per_buffer: 128, roundtrip_ms: 1.2 },
    preset: { id: '90s_tape', bpm: 92.4 },
    kaoss: { modules: [0, 1, 2, 3].map((index) => ({ index, x: 0, y: 0, frozen: false })), bpm: 92.4 },
    transport: { recording: false, loop_captured: false, loop_frames: 0 },
    dsp: { blocks: 0, kick808: 0, snare: 0, hat: 0, max_peak_dbfs: -120, last: null },
    pads: [],
    lyrics: { transcripts: [], rhymes: {} },
    avatar: { mode: 'CYPHER_CIRCLE', fps: 60, avatars: 8, bones: 33 },
    milestones: new Set(),
    events: [],
    seq: 0,
    blocked: 0,
    maxLatencyMs: 0,
    totalLatencyMs: 0,
    offlineFallback: false,
  };
}

export function createAction(action, params = {}) {
  const spec = ACTION_BY_NAME[action];
  if (!spec) throw new Error(`unknown action: ${action}`);
  return { action, engine: spec.engine, port: ENGINES[spec.engine].port, params: { ...params }, label: spec.label };
}

/** Client-Vorprüfung: welche Meilensteine fehlen, bevor diese Aktion erlaubt ist? */
export function missingMilestones(state, action) {
  const spec = ACTION_BY_NAME[action];
  if (!spec) return [`unknown:${action}`];
  return spec.requires.filter((milestone) => !state.milestones.has(milestone));
}

export function isActionReady(state, action) {
  return missingMilestones(state, action).length === 0;
}

/**
 * Reduziert ein Server-Event (oder ein Offline-Fallback-Event) auf den
 * Client-State. Enthält die gleiche Kettenlogik wie der Server, damit die UI
 * auch ohne Backend (file://-Preview) korrekt reagiert.
 */
export { isKaossState };

export function chainReducer(state, event) {
  const next = state;
  const detail = event.detail || {};
  next.seq = event.seq ?? next.seq + 1;
  next.maxLatencyMs = Math.max(next.maxLatencyMs, event.latency_ms ?? 0);
  next.totalLatencyMs += event.latency_ms ?? 0;
  if (event.status === 'BLOCKED') next.blocked += 1;
  next.events = [...next.events, event].slice(-256);

  if (event.ok) {
    const spec = ACTION_BY_NAME[event.action];
    if (spec?.milestone) next.milestones.add(spec.milestone);
    switch (event.action) {
      case 'boot': {
        // Boot setzt die Session zurück, das Boot-Event bleibt aber sichtbar.
        // (state.events enthält das Event bereits – der Reducer hängt es oben an.)
        const fresh = defaultState();
        fresh.events = state.events;
        fresh.seq = event.seq ?? state.seq;
        fresh.blocked = state.blocked;
        fresh.maxLatencyMs = state.maxLatencyMs;
        fresh.totalLatencyMs = state.totalLatencyMs;
        fresh.offlineFallback = state.offlineFallback;
        return fresh;
      }
      case 'chain.reset':
        // Serverseitig wird die Kette inklusive Reset-Event gelöscht.
        return defaultState();
      case 'input.select':
        next.input = detail.selected || next.input;
        break;
      case 'permission.check':
        (detail.required || []).forEach((key) => {
          if (!(key in next.permissions)) next.permissions[key] = (detail.granted || []).includes(key);
        });
        break;
      case 'permission.grant':
        next.permissions[detail.key] = Boolean(detail.granted);
        if (detail.key === 'record_audio' && !detail.granted) {
          next.audio.mic_armed = false;
          next.milestones.delete('mic.armed');
        }
        break;
      case 'audio.start':
        next.audio = { ...next.audio, ...pick(detail, ['running', 'sample_rate_hz', 'frames_per_buffer', 'roundtrip_ms', 'route_locked']) };
        break;
      case 'mic.arm':
        next.audio.mic_armed = Boolean(detail.armed);
        next.audio.mic_device = detail.device_id || '';
        break;
      case 'preset.apply':
        // SSE-Events tragen nur eine Detail-Zusammenfassung; verschachtelte
        // Sammlungen stehen dort als "<3 items>". Solche Platzhalter dürfen den
        // State nie ersetzen (kaoss.modules wurde sonst zum String).
        if (detail.preset && typeof detail.preset === 'object') next.preset = detail.preset;
        if (isKaossState(detail.kaoss)) next.kaoss = detail.kaoss;
        break;
      case 'kaoss.xy':
      case 'kaoss.freeze':
        next.kaoss = applyKaoss(next.kaoss, detail);
        break;
      case 'dsp.process': {
        const report = detail.report || {};
        next.dsp.blocks += 1;
        next.dsp.kick808 += report.kick808 ? 1 : 0;
        next.dsp.snare += report.snare ? 1 : 0;
        next.dsp.hat += report.hat ? 1 : 0;
        next.dsp.max_peak_dbfs = Math.max(next.dsp.max_peak_dbfs, report.output_peak_dbfs ?? -120);
        next.dsp.last = report;
        break;
      }
      case 'pad.trigger': {
        // Serverseitig läuft jeder Pad-Trigger als voller DSP-Block – der
        // Client-Spiegel muss dieselben Zähler führen (Konvergenz-Check).
        const pad = detail.pad && typeof detail.pad === 'object' ? detail.pad : null;
        if (!pad) break;  // zusammengefasster Payload: Server bleibt Quelle der Wahrheit
        next.pads = [...next.pads, pad].slice(-64);
        next.dsp.blocks += 1;
        next.dsp.kick808 += pad.transient === 'KICK808' ? 1 : 0;
        next.dsp.snare += pad.transient === 'SNARE_CLAP' ? 1 : 0;
        next.dsp.hat += pad.transient === 'HAT_ROLL' ? 1 : 0;
        next.dsp.max_peak_dbfs = Math.max(next.dsp.max_peak_dbfs, pad.peak_dbfs ?? -120);
        break;
      }
      case 'transport.record':
        next.transport.recording = Boolean(detail.recording);
        break;
      case 'loop.capture':
        next.transport.loop_captured = true;
        next.transport.loop_frames = detail.loop_frames ?? 0;
        // Loop-Capture friert serverseitig das Looper-Modul (FX1) ein.
        if (detail.looper) next.kaoss = applyKaoss(next.kaoss, detail.looper);
        break;
      case 'transcribe':
        if (typeof detail.transcript === 'string') {
          next.lyrics.transcripts = [...next.lyrics.transcripts, detail.transcript].slice(-32);
        }
        if (detail.rhymes && typeof detail.rhymes === 'object' && !Array.isArray(detail.rhymes)) {
          next.lyrics.rhymes = { ...next.lyrics.rhymes, ...detail.rhymes };
        }
        break;
      case 'rhyme.lookup':
        next.lyrics.rhymes = {
          ...next.lyrics.rhymes,
          [String(detail.word || '').toLowerCase()]: Array.isArray(detail.rhymes) ? detail.rhymes : [],
        };
        break;
      case 'avatar.mode':
        next.avatar = { ...next.avatar, ...pick(detail, ['mode', 'fps', 'avatars', 'bones']) };
        break;
      case 'neurallift.generate':
        next.avatar.glb = detail.glb;
        break;
      default:
        break;
    }
  }
  return next;
}

function pick(source, keys) {
  const out = {};
  keys.forEach((key) => {
    if (source[key] !== undefined) out[key] = source[key];
  });
  return out;
}

function isKaossState(value) {
  return Boolean(value) && typeof value === 'object' && Array.isArray(value.modules);
}

function applyKaoss(kaoss, detail) {
  if (!isKaossState(kaoss) || !detail || typeof detail !== 'object') return kaoss;
  const modules = kaoss.modules.map((module) => ({ ...module }));
  const index = Number(detail.module ?? 0);
  if (modules[index]) {
    modules[index].x = detail.x ?? modules[index].x;
    modules[index].y = detail.y ?? modules[index].y;
    modules[index].frozen = detail.frozen ?? modules[index].frozen;
  }
  return { ...kaoss, modules, bpm: detail.bpm ?? kaoss.bpm };
}

export function formatChainLine(event) {
  const detail = event.detail || {};
  const highlight =
    detail.report?.transient?.kind ||
    detail.pad?.slot ||
    detail.selected ||
    detail.preset?.id ||
    detail.mode ||
    detail.word ||
    detail.key ||
    (detail.frozen === undefined ? '' : detail.frozen ? 'FROZEN' : 'LIVE');
  const seq = String(event.seq ?? 0).padStart(3, ' ');
  const action = String(event.action || '?').padEnd(19, ' ');
  const status = String(event.status || (event.ok ? 'OK' : 'FAIL')).padEnd(7, ' ');
  const latency = `${(event.latency_ms ?? 0).toFixed(3)}ms`.padStart(9, ' ');
  const port = `:${event.port ?? ENGINES[event.engine]?.port ?? 8080}`;
  return `#${seq} ${action} ${status} ${latency} ${port} ${highlight}`.trimEnd();
}

export function summarize(state) {
  return {
    length: state.events.length,
    blocked: state.blocked,
    seq: state.seq,
    max_latency_ms: Number(state.maxLatencyMs.toFixed(3)),
    total_latency_ms: Number(state.totalLatencyMs.toFixed(3)),
    actions: state.events.map((event) => event.action),
    limiter_safe: state.dsp.max_peak_dbfs <= LIMITER_DBFS + 1e-6,
    max_peak_dbfs: Number(state.dsp.max_peak_dbfs.toFixed(3)),
    milestones: [...state.milestones].sort(),
  };
}

/**
 * Führt eine Aktionsliste sequentiell aus. `dispatch(action, params)` muss ein
 * Event-Objekt (seq/action/status/ok/detail/latency_ms) zurückgeben – im Browser
 * der POST gegen den One-App-Server, im Test ein Stub.
 */
export async function runChain(dispatch, script = FULL_CHAIN_SCRIPT, { state = defaultState(), onEvent = () => {} } = {}) {
  let current = state;
  const results = [];
  for (const step of script) {
    const { action, ...params } = step;
    const event = await dispatch(action, params, current);
    current = chainReducer(current, event);
    results.push(event);
    onEvent(event, current);
  }
  return { ok: results.every((event) => event.ok), steps: results.length, results, state: current, summary: summarize(current) };
}

/**
 * Offline-Fallback-Dispatcher: erzeugt deterministische Events ohne Backend,
 * damit die PWA auch als statische Datei (file://) die komplette Kette zeigt.
 */
export function offlineDispatcher(startSeq = 0) {
  let seq = startSeq;
  return function dispatch(action, params = {}) {
    seq += 1;
    const spec = ACTION_BY_NAME[action];
    const base = {
      seq,
      t_ms: seq * 1.5,
      action,
      engine: spec?.engine || 'orchestrator',
      port: spec ? ENGINES[spec.engine].port : 8080,
      latency_ms: 0.4 + (seq % 5) * 0.1,
      status: 'OK',
      ok: true,
      detail: offlineDetail(action, params),
      offline: true,
    };
    return base;
  };
}

function offlineDetail(action, params) {
  switch (action) {
    case 'input.select':
      return { selected: params.input || 'internal_mic' };
    case 'permission.check':
      return { required: ['record_audio', 'modify_audio'], granted: ['record_audio'], all_granted: true };
    case 'permission.grant':
      return { key: params.key || 'record_audio', granted: params.granted !== false };
    case 'audio.start':
      return { running: true, sample_rate_hz: params.sample_rate_hz || 96000, frames_per_buffer: params.frames_per_buffer || 128, roundtrip_ms: 1.2, route_locked: true };
    case 'mic.arm':
      return { armed: true, device_id: params.device_id || 'offline-default' };
    case 'preset.apply':
      return { preset: { id: params.preset || 'acid_berlin', bpm: 128 }, kaoss: { modules: [0, 1, 2, 3].map((index) => ({ index, x: 0.4, y: 0.5, frozen: false })), bpm: 128 } };
    case 'kaoss.xy':
      return { module: params.module ?? 0, x: params.x ?? 0, y: params.y ?? 0, frozen: false };
    case 'kaoss.freeze':
      return { module: params.module ?? 0, frozen: params.frozen !== false };
    case 'dsp.process': {
      const kind = { mouth_bass: 'KICK808', snare: 'SNARE_CLAP', hat: 'HAT_ROLL' }[params.signal] || 'NONE';
      return {
        signal: params.signal || 'mouth_bass',
        blocks: 1,
        limiter_safe: true,
        report: {
          frames: params.frames || 128,
          transient: { kind },
          kick808: kind === 'KICK808',
          snare: kind === 'SNARE_CLAP',
          hat: kind === 'HAT_ROLL',
          output_peak_dbfs: -3.2,
          input_peak_dbfs: -4.4,
          latency_ms: 1.2,
          checksum: 'offline0000000',
        },
      };
    }
    case 'pad.trigger': {
      const bank = params.bank || 'A';
      const transient = { A: 'KICK808', B: 'SNARE_CLAP', C: 'HAT_ROLL', D: 'NONE' }[bank] || 'NONE';
      const slot = params.slot || (SAMPLE_BANKS.find((item) => item.bank === bank)?.slots[0] ?? 'BOOM');
      return { pad: { bank, slot, transient, peak_dbfs: -3.2, voice_frames: bank === 'A' ? 5760 : 0 } };
    }
    case 'transport.record':
      return { recording: params.running !== false };
    case 'loop.capture':
      return {
        loop_frames: 24000,
        loop_ms: 500,
        step_ms: 162.3,
        subdivision: params.subdivision || 16,
        looper: { module: 0, name: 'LOOPER', frozen: true, loop_frames: 0 },
      };
    case 'transcribe':
      return { transcript: { text: params.text || 'offline cypher take', language: 'de', offline: true }, rhymes: {} };
    case 'rhyme.lookup':
      return { word: params.word || 'beton', rhymes: ['BETON', 'SEKTOR', 'DÄMON', 'NEON', 'PHONON'] };
    case 'avatar.mode':
      return { mode: params.mode || 'CYPHER_CIRCLE', fps: 60, avatars: 8, bones: 33 };
    case 'neurallift.generate':
      return { glb: 'neurallift_offline.glb', fallback: true };
    case 'session.export':
      return { session: { format: '.cypher', chain_length: 0 }, checksum: 'offline' };
    default:
      return { ok: true };
  }
}
