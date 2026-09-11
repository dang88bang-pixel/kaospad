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

const dbfsToLinear = (dbfs) => 10 ** (dbfs / 20);

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
