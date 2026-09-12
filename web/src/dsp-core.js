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
