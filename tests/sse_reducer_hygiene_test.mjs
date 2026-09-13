// Regression: SSE-Events tragen nur eine Detail-Zusammenfassung, in der
// verschachtelte Sammlungen als "<4 items>" stehen. Diese Platzhalter durften
// den State-Reducer nicht erreichen – sonst wurde `kaoss.modules` zum String
// und die UI starb mit "chainState.kaoss.modules.filter is not a function"
// (echter Befund aus dem Chromium-Lauf in CI).
import { chainReducer, defaultState, isKaossState, summarize } from '../web/src/action-chain.js';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const appSource = readFileSync(path.join(root, 'web/src/app.js'), 'utf8');

let checks = 0;
function check(label, condition, info) {
  checks += 1;
  if (!condition) {
    console.error(`CHECK FAILED: ${label} // ${JSON.stringify(info)}`);
    process.exitCode = 1;
  }
}

const SUMMARY = '<4 items>';

// 1) preset.apply mit zusammengefasstem preset/kaoss
let state = defaultState();
state = chainReducer(state, {
  seq: 1, action: 'preset.apply', status: 'OK', ok: true, latency_ms: 1.2,
  detail: { preset: '<3 items>', kaoss: '<3 items>', bpm: '<2 items>' },
});
check('preset.apply: kaoss bleibt gültig', isKaossState(state.kaoss), state.kaoss);
check('preset.apply: modules bleibt Array', Array.isArray(state.kaoss.modules), typeof state.kaoss.modules);
check('preset.apply: modules.filter läuft', state.kaoss.modules.filter((m) => m.frozen).length === 0);

// 2) kaoss.xy / kaoss.freeze mit zusammengefasstem Detail
state = chainReducer(state, { seq: 2, action: 'kaoss.xy', ok: true, latency_ms: 1, detail: { module: 2, x: 0.7, y: 0.3 } });
check('kaoss.xy mit echtem Detail wirkt', state.kaoss.modules[2].x === 0.7, state.kaoss.modules[2]);
state = chainReducer(state, { seq: 3, action: 'kaoss.freeze', ok: true, latency_ms: 1, detail: { modules: SUMMARY } });
check('kaoss.freeze mit Summary korrumpiert nicht', isKaossState(state.kaoss), state.kaoss);

// 3) loop.capture mit zusammengefasstem looper
state = chainReducer(state, { seq: 4, action: 'loop.capture', ok: true, latency_ms: 1, detail: { looper: SUMMARY, loop_frames: '<2 items>' } });
check('loop.capture mit Summary korrumpiert nicht', isKaossState(state.kaoss), state.kaoss);

// 4) pad.trigger mit zusammengefasstem pad
state = chainReducer(state, { seq: 5, action: 'pad.trigger', ok: true, latency_ms: 1, detail: { pad: '<8 items>' } });
check('pad.trigger mit Summary legt kein Fake-Pad an', state.pads.length === 0, state.pads);
state = chainReducer(state, {
  seq: 6, action: 'pad.trigger', ok: true, latency_ms: 1,
  detail: { pad: { bank: 'A', slot: 0, transient: 'KICK808', peak_dbfs: -3.2 } },
});
check('pad.trigger mit echtem Detail zählt', state.pads.length === 1 && state.dsp.kick808 === 1, state.pads);

// 5) transcribe / rhyme.lookup mit zusammengefassten Reimen
state = chainReducer(state, { seq: 7, action: 'transcribe', ok: true, latency_ms: 1, detail: { transcript: 'drück und laber', rhymes: SUMMARY } });
check('transcribe: Transcript übernommen', state.lyrics.transcripts.at(-1) === 'drück und laber');
check('transcribe: Reim-Summary erzeugt kein Objekt-Geröll', Object.keys(state.lyrics.rhymes).length === 0, state.lyrics.rhymes);
state = chainReducer(state, { seq: 8, action: 'rhyme.lookup', ok: true, latency_ms: 1, detail: { word: 'Beton', rhymes: SUMMARY } });
check('rhyme.lookup: Summary wird zu leerer Liste', Array.isArray(state.lyrics.rhymes.beton) && state.lyrics.rhymes.beton.length === 0);

// 6) summarize() bleibt nach allen Summary-Events aufrufbar (UI-Polling-Pfad)
const summary = summarize(state);
check('summarize() nach Summary-Events', summary.length === 8 && summary.blocked === 0, summary);

// 7) Die UI entfernt Summary-Platzhalter, bevor sie reduziert
check('app.js filtert "<N items>" vor dem Reduzieren', /\/\^<\\d\+ items\?>\$\/\.test\(value\)/.test(appSource), 'scalarDetail fehlt');
check('SSE-Listener nutzt scalarDetail', /detail: scalarDetail\(payload\.detail_summary\)/.test(appSource), 'SSE-Pfad ungefiltert');

console.log(JSON.stringify({ checks, events: summary.length, kaoss_ok: isKaossState(state.kaoss) }));
console.log(`sse reducer hygiene verified: ${checks} checks`);
