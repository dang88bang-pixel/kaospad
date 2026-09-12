/**
 * Kaoss DSP-Kern für den Browser – WebAssembly aus dem C++-Quelltext, mit
 * exakt rechnendem JS-Fallback.
 *
 *   make wasm  ->  dist/wasm/kaoss_dsp.wasm  ( served under /wasm/kaoss_dsp.wasm )
 *
 * Beide Pfade implementieren dieselbe ABI (`kaoss_dsp_abi.cpp`):
 * Brickwall-Limiter (-3.2 dBFS), Mouth-Bass-Transient, 808-Synthese und die
 * Kaoss-Quad-Stufe (Drive/Filter/Ambience). `tests/dsp_wasm_parity_test.mjs`
 * beweist: WASM == nativer C++-Build == Python-Spiegel == dieses JS-Fallback.
 *
 * Keine Abhängigkeiten, läuft als ES-Modul im Browser *und* in Node (Tests).
 */

export const LIMITER_DBFS = -3.2;
export const SILENCE_DBFS = -120;
export const TRANSIENT_KINDS = ['NONE', 'KICK808', 'SNARE_CLAP', 'HAT_ROLL'];
export const WASM_URL = '/wasm/kaoss_dsp.wasm';

// --------------------------------------------------------------------------- //
// JS-Spiegel des C++-Kerns (Fallback, wenn kein .wasm gebaut wurde)
// --------------------------------------------------------------------------- //
export function dbfsToLinear(dbfs) {
  return Math.pow(10, dbfs / 20);
}

export function jsBrickwallSample(sample, thresholdDbfs = LIMITER_DBFS) {
  const threshold = dbfsToLinear(thresholdDbfs);
  const sign = sample < 0 ? -1 : 1;
  const abs = Math.abs(sample);
  if (abs <= threshold) return sample;
  const over = abs - threshold;
  const compressed = threshold + (1 - threshold) * Math.tanh(over / Math.max(1e-6, 1 - threshold));
  return sign * Math.min(threshold, compressed);
}

export function jsBrickwallBuffer(pcm, thresholdDbfs = LIMITER_DBFS) {
  const out = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i += 1) out[i] = Math.fround(jsBrickwallSample(pcm[i], thresholdDbfs));
  return out;
}

export function jsPeakDbfs(pcm) {
  let peak = 0;
  for (let i = 0; i < pcm.length; i += 1) peak = Math.max(peak, Math.abs(pcm[i]));
  return peak <= 0 ? SILENCE_DBFS : 20 * Math.log10(peak);
}

export function jsDetectTransient(pcm, sampleRateHz = 96000) {
  if (!pcm.length || sampleRateHz <= 0) {
    return { kindId: 0, kind: 'NONE', frequencyHz: 0, detectionLatencyMs: 0 };
  }
  let low = 0;
  let high = 0;
  let prev = pcm[0];
  for (let i = 1; i < pcm.length; i += 1) {
    const sample = pcm[i];
    low += Math.abs(sample);
    high += Math.abs(sample - prev);
    prev = sample;
  }
  low /= pcm.length;
  high /= pcm.length;
  const latencyMs = Math.min(1.1, (pcm.length / sampleRateHz) * 1000);
  if (low > 0.12 && high < 0.035) return { kindId: 1, kind: 'KICK808', frequencyHz: 52, detectionLatencyMs: latencyMs, low, high };
  if (high > 0.18) return { kindId: 2, kind: 'SNARE_CLAP', frequencyHz: 4200, detectionLatencyMs: latencyMs, low, high };
  if (high > 0.055) return { kindId: 3, kind: 'HAT_ROLL', frequencyHz: 11000, detectionLatencyMs: latencyMs, low, high };
  return { kindId: 0, kind: 'NONE', frequencyHz: 0, detectionLatencyMs: latencyMs, low, high };
}

export function jsSynthesize808(sampleRateHz = 96000, durationMs = 180, triggered = true) {
  const frames = Math.floor((durationMs / 1000) * sampleRateHz);
  const out = new Float32Array(frames);
  if (!triggered || frames === 0) return out;
  let phase = 0;
  for (let i = 0; i < frames; i += 1) {
    const t = i / sampleRateHz;
    const glide = 38 + (140 - 38) * Math.exp(-t / 0.045);
    phase += (2 * Math.PI * glide) / sampleRateHz;
    const env = Math.exp(-t / 0.18);
    const sample = Math.sin(phase) + 0.22 * Math.sin(2 * phase) + 0.08 * Math.sin(3 * phase);
    out[i] = Math.fround(jsBrickwallSample(sample * env * 0.65));
  }
  return out;
}

/** Kaoss-Quad-Stufe: identisch zu KaossQuadEngine::process (ohne Vinyl/Looper). */
export function jsProcess(input, { x = [0, 0, 0, 0], y = [0, 0, 0, 0] } = {}) {
  const out = new Float32Array(input.length);
  const drive = 1 + x[0] * 0.35;
  const filter = 1 - y[2] * 0.42;
  const ambience = x[3] * y[3] * 0.08;
  let previous = 0;
  for (let i = 0; i < input.length; i += 1) {
    const sample = input[i];
    const delayed = previous * ambience;
    previous = sample;
    out[i] = Math.fround(jsBrickwallSample(sample * drive * filter + delayed));
  }
  return out;
}

export function fnv1aFloat32(pcm) {
  const view = pcm instanceof Float32Array ? pcm : Float32Array.from(pcm);
  let hash = 0xcbf29ce484222325n;
  const bytes = new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
  for (let i = 0; i < bytes.length; i += 1) {
    hash ^= BigInt(bytes[i]);
    hash = (hash * 0x100000001b3n) & 0xffffffffffffffffn;
  }
  return hash.toString(16).padStart(16, '0');
}

// --------------------------------------------------------------------------- //
// WASM-Instanz
// --------------------------------------------------------------------------- //
export function wasiStubImports() {
  const handler = {
    get(target, prop) {
      if (typeof prop !== 'string') return undefined;
      if (prop === 'proc_exit') return () => { throw new Error('kaoss_dsp.wasm called proc_exit'); };
      return () => 0;
    },
  };
  return { wasi_snapshot_preview1: new Proxy({}, handler), env: new Proxy({}, handler) };
}

export class KaossDspWasm {
  constructor(instance) {
    this.engine = 'wasm';
    this.instance = instance;
    this.exports = instance.exports;
    this.abi = this.exports.kaoss_dsp_abi_version();
    this.limiterDbfs = this.exports.kaoss_dsp_limiter_dbfs();
    this.quad = this.exports.kaoss_quad_create();
  }

  get memory() {
    return this.exports.memory;
  }

  /** Scratch-Puffer im linearen Speicher; Views immer frisch (Memory kann wachsen). */
  withBuffer(floats, run) {
    const count = floats.length;
    const ptr = this.exports.malloc(count * 4);
    if (!ptr) throw new Error('kaoss_dsp.wasm malloc failed');
    try {
      new Float32Array(this.memory.buffer, ptr, count).set(floats);
      return run(ptr, count);
    } finally {
      this.exports.free(ptr);
    }
  }

  alloc(count) {
    const ptr = this.exports.malloc(count * 4);
    if (!ptr) throw new Error('kaoss_dsp.wasm malloc failed');
    return ptr;
  }

  read(ptr, count) {
    return new Float32Array(this.memory.buffer, ptr, count).slice();
  }

  brickwallSample(sample, thresholdDbfs = LIMITER_DBFS) {
    return this.exports.kaoss_dsp_brickwall_sample(Math.fround(sample), Math.fround(thresholdDbfs));
  }

  brickwallBuffer(pcm, thresholdDbfs = LIMITER_DBFS) {
    const input = pcm instanceof Float32Array ? pcm : Float32Array.from(pcm);
    return this.withBuffer(input, (ptr, count) => {
      const out = this.alloc(count);
      try {
        this.exports.kaoss_dsp_brickwall_buffer(ptr, out, count, Math.fround(thresholdDbfs));
        return this.read(out, count);
      } finally {
        this.exports.free(out);
      }
    });
  }

  peakDbfs(pcm) {
    const input = pcm instanceof Float32Array ? pcm : Float32Array.from(pcm);
    return this.withBuffer(input, (ptr, count) => this.exports.kaoss_dsp_peak_dbfs(ptr, count));
  }

  detectTransient(pcm, sampleRateHz = 96000) {
    const input = pcm instanceof Float32Array ? pcm : Float32Array.from(pcm);
    return this.withBuffer(input, (ptr, count) => {
      const out = this.exports.malloc(3 * 8);
      try {
        this.exports.kaoss_dsp_detect_transient(ptr, count, sampleRateHz, out);
        const view = new Float64Array(this.memory.buffer, out, 3).slice();
        const kindId = Math.round(view[0]);
        return {
          kindId,
          kind: TRANSIENT_KINDS[kindId] || 'NONE',
          frequencyHz: view[1],
          detectionLatencyMs: view[2],
        };
      } finally {
        this.exports.free(out);
      }
    });
  }

  synthesize808(sampleRateHz = 96000, durationMs = 180, triggered = true) {
    const frames = Math.floor((durationMs / 1000) * sampleRateHz);
    const out = this.alloc(Math.max(1, frames));
    try {
      const written = this.exports.kaoss_dsp_synthesize_808(out, frames, sampleRateHz, durationMs, triggered ? 1 : 0);
      return this.read(out, frames).slice(0, Math.max(written, 0));
    } finally {
      this.exports.free(out);
    }
  }

  setXy(module, x, y) {
    return this.exports.kaoss_quad_set_xy(this.quad, module, Math.fround(x), Math.fround(y)) === 1;
  }

  freeze(module, enabled) {
    return this.exports.kaoss_quad_freeze(this.quad, module, enabled ? 1 : 0) === 1;
  }

  state() {
    const xyPtr = this.exports.malloc(8 * 4);
    const frozenPtr = this.exports.malloc(4);
    const bpmPtr = this.exports.malloc(4);
    try {
      this.exports.kaoss_quad_read_state(this.quad, xyPtr, frozenPtr, bpmPtr);
      const xy = new Float32Array(this.memory.buffer, xyPtr, 8).slice();
      const frozen = new Uint8Array(this.memory.buffer, frozenPtr, 4).slice();
      const bpm = new Float32Array(this.memory.buffer, bpmPtr, 1)[0];
      return { xy: Array.from(xy), frozen: Array.from(frozen), bpm };
    } finally {
      this.exports.free(xyPtr);
      this.exports.free(frozenPtr);
      this.exports.free(bpmPtr);
    }
  }

  process(pcm) {
    const input = pcm instanceof Float32Array ? pcm : Float32Array.from(pcm);
    return this.withBuffer(input, (ptr, count) => {
      const out = this.alloc(count);
      try {
        this.exports.kaoss_quad_process(this.quad, ptr, out, count);
        return this.read(out, count);
      } finally {
        this.exports.free(out);
      }
    });
  }

  checksum(pcm) {
    const input = pcm instanceof Float32Array ? pcm : Float32Array.from(pcm);
    return this.withBuffer(input, (ptr, count) => {
      // wasm i64 kommt als (ggf. negatives) BigInt zurück -> unsigned normalisieren.
      const digest = BigInt.asUintN(64, BigInt(this.exports.kaoss_dsp_checksum(ptr, count)));
      return digest.toString(16).padStart(16, '0');
    });
  }

  destroy() {
    if (this.quad) this.exports.kaoss_quad_destroy(this.quad);
    this.quad = 0;
  }
}

/** JS-Fallback mit identischer API (rechnet dieselbe Mathematik wie der Kern). */
export class KaossDspJs {
  constructor() {
    this.engine = 'js';
    this.abi = 1;
    this.limiterDbfs = LIMITER_DBFS;
    this.x = [0, 0, 0, 0];
    this.y = [0, 0, 0, 0];
    this.frozen = [0, 0, 0, 0];
    this.bpm = 92.4;
  }

  brickwallSample(sample, thresholdDbfs = LIMITER_DBFS) {
    return Math.fround(jsBrickwallSample(sample, thresholdDbfs));
  }

  brickwallBuffer(pcm, thresholdDbfs = LIMITER_DBFS) {
    return jsBrickwallBuffer(pcm, thresholdDbfs);
  }

  peakDbfs(pcm) {
    return jsPeakDbfs(pcm);
  }

  detectTransient(pcm, sampleRateHz = 96000) {
    return jsDetectTransient(pcm, sampleRateHz);
  }

  synthesize808(sampleRateHz = 96000, durationMs = 180, triggered = true) {
    return jsSynthesize808(sampleRateHz, durationMs, triggered);
  }

  setXy(module, x, y) {
    if (module < 0 || module > 3 || this.frozen[module]) return false;
    this.x[module] = Math.fround(Math.min(1, Math.max(0, x)));
    this.y[module] = Math.fround(Math.min(1, Math.max(0, y)));
    return true;
  }

  freeze(module, enabled) {
    if (module < 0 || module > 3) return false;
    this.frozen[module] = enabled ? 1 : 0;
    return true;
  }

  state() {
    return { xy: [...this.x, ...this.y], frozen: [...this.frozen], bpm: this.bpm };
  }

  process(pcm) {
    return jsProcess(pcm, { x: this.x, y: this.y });
  }

  checksum(pcm) {
    const limited = pcm instanceof Float32Array ? pcm : Float32Array.from(pcm);
    return fnv1aFloat32(limited);
  }

  destroy() {}
}

async function readWasmBytes({ url = WASM_URL, bytes = null, fetchImpl = null } = {}) {
  if (bytes) return bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const doFetch = fetchImpl || (typeof fetch === 'function' ? fetch : null);
  if (!doFetch) throw new Error('no fetch implementation and no bytes provided');
  const response = await doFetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`wasm fetch failed: ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}

/**
 * Lädt den WASM-Kern; fällt auf den JS-Spiegel zurück, wenn das Modul nicht
 * gebaut wurde (`make wasm`) oder der Browser WebAssembly verweigert.
 */
export async function loadKaossDsp(options = {}) {
  const allowFallback = options.allowFallback !== false;
  try {
    const wasmBytes = await readWasmBytes(options);
    const { instance } = await WebAssembly.instantiate(wasmBytes, wasiStubImports());
    return new KaossDspWasm(instance);
  } catch (error) {
    if (!allowFallback) throw error;
    const fallback = new KaossDspJs();
    fallback.loadError = String(error?.message || error);
    return fallback;
  }
}

export default loadKaossDsp;

/* ---------------------------------------------------------------------------
 * Zweiter Kern (aus main / PR #4): WebAudio-Engine-Pfad.
 *
 * `createDspCore()` lädt das Emscripten-Modul `web/wasm/dsp_core.mjs`
 * (Exports `kaoss_wasm_*`, gebaut von scripts/build_wasm.sh, nur mit emcc)
 * und fällt auf den JS-Mirror `createJsDspCore()` zurück. Benutzt von
 * `web/src/audio-engine.js` und `tests/native_audio_bridge_test.py`.
 *
 * Teil 1 oben ist der ABI-Kern (`dist/wasm/kaoss_dsp.wasm` aus
 * `kaoss_dsp_abi.cpp`, Toolchain-unabhängig, 4-Wege-Parität gemessen) mit
 * `loadKaossDsp()` für das UI-Badge und `tests/dsp_wasm_parity_test.mjs`.
 * Beide Kerne rechnen denselben Limiter/Transient/Quad-Mathematik.
 * ------------------------------------------------------------------------- */

// Kaoss DSP core for the browser: WASM (C++ portable core) with a pure-JS
// mirror as zero-cloud fallback.
//
// The JS mirror reproduces the exact same math as the C++ core
// (android/app/src/main/cpp/kaoss_audio_processor.cpp + kaoss_quad_engine.cpp
// + dsp_transient_splitter.cpp) and the Python mirror (engines/dsp_chain.py),
// so the meter, transient splitter and Kaoss Quad agree on numbers across
// native, browser and CI. When web/wasm/dsp_core.mjs is present (built by
// scripts/build_wasm.sh) the WASM module is preferred.

const LIMITER_THRESHOLD_DBFS = -3.2;
const PI = Math.PI;

function brickwallSoftKneeSample(sample, thresholdDb = LIMITER_THRESHOLD_DBFS) {
  const threshold = dbfsToLinear(thresholdDb);
  const sign = sample < 0 ? -1 : 1;
  const abs = Math.abs(sample);
  if (abs <= threshold) return sample;
  const over = abs - threshold;
  const compressed = threshold + (1 - threshold) * Math.tanh(over / Math.max(1e-6, 1 - threshold));
  return sign * Math.min(threshold, compressed);
}

function brickwallSoftKneeBuffer(input, thresholdDb = LIMITER_THRESHOLD_DBFS) {
  const out = new Float32Array(input.length);
  for (let i = 0; i < input.length; i += 1) out[i] = brickwallSoftKneeSample(input[i], thresholdDb);
  return out;
}

function peakDbfs(buffer) {
  let peak = 0;
  for (let i = 0; i < buffer.length; i += 1) peak = Math.max(peak, Math.abs(buffer[i]));
  return peak > 0 ? 20 * Math.log10(peak) : -120;
}

// Mirrors kaoss::detect_mouth_transient (mean-abs + delta-energy envelope).
function detectMouthTransient(pcm, sampleRate) {
  if (!pcm || pcm.length === 0 || !sampleRate) {
    return { kind: 0, kind_name: 'NONE', frequency_hz: 0, latency_ms: 0 };
  }
  let lowEnergy = 0;
  let highEnergy = 0;
  let prev = pcm[0];
  for (let i = 1; i < pcm.length; i += 1) {
    const sample = pcm[i];
    lowEnergy += Math.abs(sample);
    highEnergy += Math.abs(sample - prev);
    prev = sample;
  }
  lowEnergy /= pcm.length;
  highEnergy /= pcm.length;
  const latency = Math.min(1.1, (pcm.length / sampleRate) * 1000);
  if (lowEnergy > 0.12 && highEnergy < 0.035) return { kind: 1, kind_name: 'KICK808', frequency_hz: 52, latency_ms: latency };
  if (highEnergy > 0.18) return { kind: 2, kind_name: 'SNARE_CLAP', frequency_hz: 4200, latency_ms: latency };
  if (highEnergy > 0.055) return { kind: 3, kind_name: 'HAT_ROLL', frequency_hz: 11000, latency_ms: latency };
  return { kind: 0, kind_name: 'NONE', frequency_hz: 0, latency_ms: latency };
}

// Mirrors kaoss::synthesize_808 (pitch glide + decay + limiter).
function synth808(sampleRate = 48000, durationMs = 180) {
  const frames = Math.floor((durationMs / 1000) * sampleRate);
  const out = new Float32Array(frames);
  let phase = 0;
  for (let i = 0; i < frames; i += 1) {
    const t = i / sampleRate;
    const glide = 38 + (140 - 38) * Math.exp(-t / 0.045);
    phase += (2 * PI * glide) / sampleRate;
    const env = Math.exp(-t / 0.18);
    const sample = Math.sin(phase) + 0.22 * Math.sin(2 * phase) + 0.08 * Math.sin(3 * phase);
    out[i] = sample * env * 0.65;
  }
  return brickwallSoftKneeBuffer(out);
}

// Mirrors kaoss::KaossQuadEngine::process + limiter.
function kaossQuadProcess(input, quad) {
  const drive = 1 + quad.x[0] * 0.35;
  const filter = 1 - quad.y[2] * 0.42;
  const ambience = quad.x[3] * quad.y[3] * 0.08;
  const out = new Float32Array(input.length);
  let previous = 0;
  for (let i = 0; i < input.length; i += 1) {
    const delayed = previous * ambience;
    previous = input[i];
    out[i] = brickwallSoftKneeSample(input[i] * drive * filter + delayed);
  }
  return out;
}

function makeQuadState() {
  return {
    x: [0.5, 0.5, 0.5, 0.5],
    y: [0.5, 0.5, 0.5, 0.5],
    frozen: [false, false, false, false],
  };
}

// ------------------------------------------------------------------------- //
// Pure-JS mirror core (always available, zero-cloud).
// ------------------------------------------------------------------------- //
function createJsCore() {
  const quad = makeQuadState();
  let blocks = 0;
  return {
    backend: 'js',
    limiterPeak(data) {
      return peakDbfs(brickwallSoftKneeBuffer(data));
    },
    detectTransient(data, sampleRate) {
      return detectMouthTransient(data, sampleRate);
    },
    processBlock(data, sampleRate) {
      const transient = detectMouthTransient(data, sampleRate);
      const processed = kaossQuadProcess(data, quad);
      let rmsSum = 0;
      let inputPeak = 0;
      for (let i = 0; i < data.length; i += 1) {
        inputPeak = Math.max(inputPeak, Math.abs(data[i]));
        rmsSum += data[i] * data[i];
      }
      blocks += 1;
      return {
        peak_dbfs: peakDbfs(processed),
        input_peak_dbfs: inputPeak > 0 ? 20 * Math.log10(inputPeak) : -120,
        rms_dbfs: rmsSum > 0 ? 10 * Math.log10(rmsSum / data.length) : -120,
        transient: transient.kind_name,
        kind: transient.kind,
        transient_frequency_hz: transient.frequency_hz,
        transient_latency_ms: transient.latency_ms,
        limiter_active: (inputPeak > 0 ? 20 * Math.log10(inputPeak) : -120) > LIMITER_THRESHOLD_DBFS + 1e-4,
        frames: data.length,
        blocks,
      };
    },
    setXY(module, x, y) {
      if (module < 0 || module > 3) return;
      if (!quad.frozen[module]) {
        quad.x[module] = Math.max(0, Math.min(1, x));
        quad.y[module] = Math.max(0, Math.min(1, y));
      }
    },
    freeze(module, enabled) {
      if (module >= 0 && module <= 3) quad.frozen[module] = Boolean(enabled);
    },
    synth808,
    quadState: () => quad,
  };
}

// ------------------------------------------------------------------------- //
// WASM core (preferred when built + loadable).
// ------------------------------------------------------------------------- //
async function createWasmCore() {
  let factory;
  const module = await import('../wasm/dsp_core.mjs');
  factory = module.default || module.KaossDspCore;
  if (!factory) throw new Error('wasm module exports no factory');
  const mod = await factory();
  const HEAPF32 = mod.HEAPF32;
  const HEAPF64 = mod.HEAPF64;
  const HEAP32 = mod.HEAP32;
  const malloc = mod._malloc;
  const free = mod._free;
  const processBlockWasm = mod.cwrap('kaoss_wasm_process_block', 'number', ['number', 'number', 'number', 'number']);
  const detectTransientWasm = mod.cwrap('kaoss_wasm_detect_transient', null, ['number', 'number', 'number', 'number', 'number', 'number']);
  const setXyWasm = mod.cwrap('kaoss_wasm_set_xy', null, ['number', 'number', 'number']);
  const freezeWasm = mod.cwrap('kaoss_wasm_freeze', null, ['number', 'number']);
  const synthWasm = mod.cwrap('kaoss_wasm_synth_808', 'number', ['number', 'number', 'number', 'number']);
  const limiterWasm = mod.cwrap('kaoss_wasm_limiter_peak', 'number', ['number', 'number']);

  const withBuffer = (data, fn) => {
    const bytes = data.length * Float32Array.BYTES_PER_ELEMENT;
    const ptr = malloc(bytes);
    HEAPF32.set(data, ptr / Float32Array.BYTES_PER_ELEMENT);
    try {
      return fn(ptr, data.length);
    } finally {
      free(ptr);
    }
  };

  return {
    backend: 'wasm',
    limiterPeak(data) {
      return withBuffer(data, (ptr, len) => limiterWasm(ptr, len));
    },
    detectTransient(data, sampleRate) {
      return withBuffer(data, (ptr, len) => {
        const kindPtr = malloc(4);
        const freqPtr = malloc(8);
        const latPtr = malloc(8);
        try {
          detectTransientWasm(ptr, len, sampleRate, kindPtr, freqPtr, latPtr);
          const kind = HEAP32[kindPtr / 4];
          const names = ['NONE', 'KICK808', 'SNARE_CLAP', 'HAT_ROLL'];
          return {
            kind,
            kind_name: names[kind] || 'NONE',
            frequency_hz: HEAPF64[freqPtr / 8],
            latency_ms: HEAPF64[latPtr / 8],
          };
        } finally {
          free(kindPtr);
          free(freqPtr);
          free(latPtr);
        }
      });
    },
    processBlock(data, sampleRate) {
      const transient = this.detectTransient(data, sampleRate);
      return withBuffer(data, (ptr, len) => {
        const kindPtr = malloc(4);
        let peak = -120;
        try {
          peak = processBlockWasm(ptr, len, sampleRate, kindPtr);
        } finally {
          free(kindPtr);
        }
        return {
          peak_dbfs: peak,
          input_peak_dbfs: -120,
          rms_dbfs: -120,
          transient: transient.kind_name,
          kind: transient.kind,
          transient_frequency_hz: transient.frequency_hz,
          transient_latency_ms: transient.latency_ms,
          limiter_active: peak <= -3.2 + 1e-4,
          frames: len,
          blocks: 0,
        };
      });
    },
    setXY(module, x, y) {
      setXyWasm(module, x, y);
    },
    freeze(module, enabled) {
      freezeWasm(module, enabled ? 1 : 0);
    },
    synth808(sampleRate = 48000, durationMs = 180) {
      const frames = Math.floor((durationMs / 1000) * sampleRate);
      const bytes = frames * Float32Array.BYTES_PER_ELEMENT;
      const ptr = malloc(bytes);
      try {
        const written = synthWasm(sampleRate, durationMs, ptr, frames);
        return new Float32Array(HEAPF32.buffer, ptr, written).slice();
      } finally {
        free(ptr);
      }
    },
  };
}

// Factory: prefer WASM, fall back to the JS mirror (zero-cloud safe).
export async function createDspCore() {
  try {
    const core = await createWasmCore();
    return core;
  } catch {
    return createJsCore();
  }
}

// Synchronous JS mirror for tests and instant metering (no async boundary).
export function createJsDspCore() {
  return createJsCore();
}

export const DSP_LIMITER_THRESHOLD_DBFS = LIMITER_THRESHOLD_DBFS;
