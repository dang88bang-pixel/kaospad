#!/usr/bin/env node
/**
 * 3-Wege-Parität des DSP-Kerns: WebAssembly <-> natives C++-Binary <-> Python-Spiegel.
 *
 *   scripts/dsp_parity_vectors.py  -> dist/parity/vectors.bin + python.json
 *   tests/dsp_parity_harness.cpp   -> build/dsp_parity_native (g++/clang)
 *   dist/wasm/kaoss_dsp.wasm       -> scripts/build_wasm.sh (make wasm)
 *   web/src/dsp-core.js            -> JS-Fallback des Browsers
 *
 * Alle vier Läufe lesen dieselben Vektoren und müssen dasselbe rechnen
 * (Limiter, Transient, 808, Kaoss-Quad). Damit ist belegt, dass Browser und
 * Native aus demselben C++-Quelltext identisch rechnen – und der JS-Fallback
 * nicht auseinanderläuft.
 */
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { KaossDspJs, KaossDspWasm, fnv1aFloat32, wasiStubImports } from '../web/src/dsp-core.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const dist = path.join(root, 'dist', 'parity');
const vectorsPath = path.join(dist, 'vectors.bin');
const pythonPath = path.join(dist, 'python.json');
const wasmPath = path.join(root, 'dist', 'wasm', 'kaoss_dsp.wasm');
const nativeBin = path.join(root, 'build', 'dsp_parity_native');
const harnessSrc = path.join(root, 'tests', 'dsp_parity_harness.cpp');

const checks = [];
function check(label, condition, detail = '') {
  if (!condition) {
    const text = typeof detail === 'string' ? detail : JSON.stringify(detail);
    throw new Error(`CHECK FAILED: ${label} // ${text.slice(0, 600)}`);
  }
  checks.push(label);
}

function run(cmd, args, options = {}) {
  const result = spawnSync(cmd, args, { cwd: root, encoding: 'utf8', ...options });
  if (result.error) throw result.error;
  return result;
}

function readFloats(view, offset, count) {
  const out = new Float32Array(count);
  for (let i = 0; i < count; i += 1) out[i] = view.getFloat32(offset + i * 4, true);
  return out;
}

function readVectors() {
  const raw = readFileSync(vectorsPath);
  if (raw.subarray(0, 4).toString('latin1') !== 'KVEC') throw new Error('bad vector magic');
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const cases = view.getUint32(8, true);
  let offset = 12;
  const vectors = [];
  for (let i = 0; i < cases; i += 1) {
    const nameLen = view.getUint32(offset, true);
    offset += 4;
    const name = raw.subarray(offset, offset + nameLen).toString('utf8');
    offset += nameLen;
    const rate = Number(view.getFloat64(offset, true));
    offset += 8;
    const frames = view.getUint32(offset, true);
    offset += 4;
    const pcm = readFloats(view, offset, frames);
    offset += frames * 4;
    const xy = Array.from(readFloats(view, offset, 8));
    offset += 32;
    const s808Frames = view.getUint32(offset, true);
    offset += 4;
    const s808Ms = Number(view.getFloat64(offset, true));
    offset += 8;
    vectors.push({ name, rate, frames, pcm, xy, s808Frames, s808Ms });
  }
  return vectors;
}

function round(value) {
  return Number(Number(value).toPrecision(9));
}

function jsonNumbers(values) {
  return Array.from(values).map((value) => round(value));
}

async function wasmResults(vectors) {
  const bytes = readFileSync(wasmPath);
  const module = await WebAssembly.compile(bytes);
  const cases = [];
  for (const vector of vectors) {
    // Module-Form der API: instantiate() liefert hier die Instance selbst.
    const instance = await WebAssembly.instantiate(module, wasiStubImports());
    const core = new KaossDspWasm(instance);
    for (let m = 0; m < 4; m += 1) core.setXy(m, vector.xy[m], vector.xy[4 + m]);
    const limited = core.brickwallBuffer(vector.pcm);
    const transient = core.detectTransient(vector.pcm, vector.rate);
    // Der native Harness kapselt die 808-Länge auf s808Frames – hier identisch.
    const synth = core.synthesize808(vector.rate, vector.s808Ms, true).subarray(0, vector.s808Frames);
    const processed = core.process(vector.pcm);
    const state = core.state();
    cases.push({
      name: vector.name,
      frames: vector.frames,
      sample_rate_hz: vector.rate,
      peak_dbfs: round(core.peakDbfs(vector.pcm)),
      limited_peak_dbfs: round(core.peakDbfs(limited)),
      sample: round(core.brickwallSample(1.0)),
      checksum: core.checksum(limited),
      abi: core.abi,
      transient: {
        kind_id: transient.kindId,
        frequency_hz: round(transient.frequencyHz),
        detection_latency_ms: round(transient.detectionLatencyMs),
      },
      limited: jsonNumbers(limited),
      processed: jsonNumbers(processed),
      s808: jsonNumbers(synth),
      state: { xy: jsonNumbers(state.xy), frozen: state.frozen, bpm: round(state.bpm) },
    });
    core.destroy();
  }
  return { impl: 'wasm', abi: 1, limiter_dbfs: -3.2, cases };
}

function jsResults(vectors) {
  const cases = [];
  for (const vector of vectors) {
    const core = new KaossDspJs();
    for (let m = 0; m < 4; m += 1) core.setXy(m, vector.xy[m], vector.xy[4 + m]);
    const limited = core.brickwallBuffer(vector.pcm);
    const transient = core.detectTransient(vector.pcm, vector.rate);
    const synth = core.synthesize808(vector.rate, vector.s808Ms, true).subarray(0, vector.s808Frames);
    const processed = core.process(vector.pcm);
    const state = core.state();
    cases.push({
      name: vector.name,
      frames: vector.frames,
      sample_rate_hz: vector.rate,
      peak_dbfs: round(core.peakDbfs(vector.pcm)),
      limited_peak_dbfs: round(core.peakDbfs(limited)),
      sample: round(core.brickwallSample(1.0)),
      checksum: core.checksum(limited),
      transient: {
        kind_id: transient.kindId,
        frequency_hz: round(transient.frequencyHz),
        detection_latency_ms: round(transient.detectionLatencyMs),
      },
      limited: jsonNumbers(limited),
      processed: jsonNumbers(processed),
      s808: jsonNumbers(synth),
      state: { xy: jsonNumbers(state.xy), frozen: state.frozen, bpm: round(state.bpm) },
    });
  }
  return { impl: 'js', abi: 1, limiter_dbfs: -3.2, cases };
}

function nativeResults(vectors) {
  if (!existsSync(nativeBin)) {
    const compiler = ['g++', 'clang++'].find((tool) => spawnSync(tool, ['--version'], { cwd: root }).status === 0);
    if (!compiler) return null;
    const core = [
      'audio_flinger_hook.cpp',
      'dsp_transient_splitter.cpp',
      'kaoss_quad_engine.cpp',
      'kaoss_dsp_abi.cpp',
    ].map((file) => path.join('android', 'app', 'src', 'main', 'cpp', file));
    const built = run(compiler, [
      '-std=c++17', '-O2', '-Wall', '-Wextra', '-Wpedantic',
      `-I${path.join('android', 'app', 'src', 'main', 'cpp')}`,
      harnessSrc, ...core, '-o', nativeBin,
    ]);
    if (built.status !== 0) {
      throw new Error(`native harness build failed:\n${built.stderr?.slice(0, 1200)}`);
    }
  }
  const result = run(nativeBin, [vectorsPath, 'native']);
  if (result.status !== 0) throw new Error(`native harness failed: ${result.stderr?.slice(0, 600)}`);
  return JSON.parse(result.stdout);
}

function maxDeviation(a, b) {
  let worst = 0;
  const length = Math.min(a.length, b.length);
  for (let i = 0; i < length; i += 1) worst = Math.max(worst, Math.abs(a[i] - b[i]));
  if (a.length !== b.length) return Number.POSITIVE_INFINITY;
  return worst;
}

function compare(label, reference, candidate, { tolerance, compareChecksum = true, compareKinds = true }) {
  check(`${label}: case count`, reference.cases.length === candidate.cases.length, {
    reference: reference.cases.length,
    candidate: candidate.cases.length,
  });
  let worst = 0;
  for (let index = 0; index < reference.cases.length; index += 1) {
    const expected = reference.cases[index];
    const actual = candidate.cases[index];
    check(`${label}: case name ${index}`, expected.name === actual.name, { expected: expected.name, actual: actual.name });
    for (const key of ['peak_dbfs', 'limited_peak_dbfs', 'sample']) {
      const deviation = Math.abs(expected[key] - actual[key]);
      worst = Math.max(worst, deviation);
      check(`${label}: ${expected.name}.${key}`, deviation <= tolerance, { expected: expected[key], actual: actual[key], deviation, tolerance });
    }
    for (const buffer of ['limited', 'processed', 's808']) {
      const deviation = maxDeviation(expected[buffer], actual[buffer]);
      worst = Math.max(worst, deviation);
      check(`${label}: ${expected.name}.${buffer}`, deviation <= tolerance, { deviation, tolerance, buffer });
    }
    for (const key of ['frequency_hz', 'detection_latency_ms']) {
      const deviation = Math.abs(expected.transient[key] - actual.transient[key]);
      worst = Math.max(worst, deviation);
      check(`${label}: ${expected.name}.transient.${key}`, deviation <= tolerance, { deviation, tolerance });
    }
    if (compareKinds) {
      check(`${label}: ${expected.name}.transient.kind`, expected.transient.kind_id === actual.transient.kind_id, {
        expected: expected.transient.kind_id,
        actual: actual.transient.kind_id,
      });
    }
    const xyDeviation = maxDeviation(expected.state.xy, actual.state.xy);
    worst = Math.max(worst, xyDeviation);
    check(`${label}: ${expected.name}.state.xy`, xyDeviation <= tolerance, { xyDeviation, tolerance });
    if (compareChecksum) {
      check(`${label}: ${expected.name}.checksum`, expected.checksum === actual.checksum, {
        expected: expected.checksum,
        actual: actual.checksum,
      });
    }
  }
  return worst;
}

async function main() {
  mkdirSync(dist, { recursive: true });

  const vectors = run('python3', [path.join('scripts', 'dsp_parity_vectors.py'), '--vectors', vectorsPath, '--out', pythonPath]);
  if (vectors.status !== 0) throw new Error(`vector generation failed:\n${vectors.stderr}`);
  check('vectors generated', existsSync(vectorsPath) && existsSync(pythonPath), vectors.stdout);

  const cases = readVectors();
  check('vector cases', cases.length >= 5, cases.map((item) => item.name));

  if (!existsSync(wasmPath)) {
    const built = run('bash', [path.join('scripts', 'build_wasm.sh')]);
    if (built.status !== 0) {
      if (process.env.KAOSS_ALLOW_MISSING_WASM === '1') {
        console.log(`SKIP wasm parity: kein Modul und kein Toolchain\n${built.stderr?.slice(0, 300)}`);
        return 0;
      }
      throw new Error(`wasm build failed (make wasm):\n${built.stdout}\n${built.stderr}`);
    }
  }
  check('wasm module present', existsSync(wasmPath), wasmPath);

  const wasm = await wasmResults(cases);
  const js = jsResults(cases);
  const python = JSON.parse(readFileSync(pythonPath, 'utf8'));
  const native = nativeResults(cases);
  writeFileSync(path.join(dist, 'wasm.json'), JSON.stringify(wasm));
  writeFileSync(path.join(dist, 'js.json'), JSON.stringify(js));
  if (native) writeFileSync(path.join(dist, 'native.json'), JSON.stringify(native));

  check('wasm abi', wasm.abi === 1 && wasm.cases[0].abi === 1, wasm.cases[0].abi);

  // 1) WASM == nativer C++-Build (derselber Quelltext, andere Zielplattform).
  //    Beide rechnen in float32 durch dieselben Funktionen -> bit-identisch,
  //    deshalb wird hier zusätzlich der FNV-1a-Hash über die Float-Bits verglichen.
  if (native) {
    const wasmVsNative = compare('wasm==native', native, wasm, { tolerance: 1e-6 });
    console.log(`wasm == native: max deviation ${wasmVsNative.toExponential(3)} über ${wasm.cases.length} cases`);
  } else {
    console.log('native Referenz übersprungen (kein g++/clang++ gefunden)');
  }

  // 2) WASM == JS-Fallback des Browsers. JS rechnet die Zwischenwerte in double
  //    (tanhf ist nicht bit-nachbildbar), darum Toleranz statt Bit-Hash.
  const wasmVsJs = compare('wasm==js', wasm, js, { tolerance: 1e-6, compareChecksum: false });
  console.log(`wasm == browser js fallback: max deviation ${wasmVsJs.toExponential(3)}`);

  // 3) WASM == Python-Spiegel (engines/dsp_chain.py)
  const wasmVsPython = compare('wasm==python', python, wasm, { tolerance: 1e-5, compareChecksum: false });
  console.log(`wasm == python mirror: max deviation ${wasmVsPython.toExponential(3)}`);

  // 4) Limiter-Vertrag muss in allen Implementierungen halten
  for (const impl of [wasm, js, python, native].filter(Boolean)) {
    for (const item of impl.cases) {
      check(`limiter ${impl.impl}/${item.name}`, item.limited_peak_dbfs <= -3.2 + 1e-5, {
        peak: item.limited_peak_dbfs,
      });
    }
  }
  const kicks = wasm.cases.filter((item) => item.transient.kind_id === 1).length;
  check('transient detection live', kicks >= 2, wasm.cases.map((item) => [item.name, item.transient.kind_id]));

  console.log(
    `dsp parity ok: ${checks.length} checks // cases=${wasm.cases.length} // ` +
      `implementations=${[wasm, js, python, native].filter(Boolean).map((item) => item.impl).join('+')}`,
  );
  return 0;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(error?.stack || error);
    process.exit(1);
  },
);
