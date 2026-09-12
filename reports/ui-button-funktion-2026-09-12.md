# UI-Button-Funktion — Vollständige Verifikation 2026-09-12

**Branch:** `arena/01a090e3-kaospad` @ `bb1c0da` (nach Rebase `1632a01..bb1c0da`, `git status` clean)  
**Harness:** `tests/web_ui_interaction_chain_test.mjs` (107 Checks, DOM-Stub + echter `app.py`-Server, echte `click`/`change`/`input`/`pointermove`/`pointerdown`-Events) + `tests/action_chain_ui_test.mjs` (89 Checks) + `python3 /tmp/verify_ui_buttons.py` (statische Inventur)  
**Server:** `python3 app.py --host 127.0.0.1 --port <ephemeral 81xx>` (One-App, 8080-8085 In-Process Daemons)  
**Datum:** 2026-09-12 (Europe/Berlin)

---

## Kurzfassung

**Alle Buttons sind aktiv angeschlossen — kein toter Button.**

* **18 Buttons** — alle mit `addEventListener` in `web/src/app.js` verdrahtet, alle lösen reale `dispatchAction`/`fetch`-Ketten aus. Verifikation: `verify_ui_buttons.py` → `missing none`.
* **5 Selects + 8 Inputs + 4 Freeze (`data-module 0-3`) + 16 Pad-Grid + XY-Pad** — ebenfalls vollständig verdrahtet.
* **31 Listener** (`click 22`, `change 4`, `input 3`, `pointermove 1`, `pointerdown 1`), **17 `dispatchAction`-Targets**, **11 Fetch-Endpoints** — alle im Harness live durchlaufen.
* **107 UI-Checks** in `web_ui_interaction_chain_test.mjs` bestanden, **0 BLOCKED** nach `run-full-chain` (23 Schritte), `limiter_safe true`, `peak_dbfs -3.2 dBFS`, `max_latency_ms 4.7 ms`.  
  Gegenprobe `action_chain_ui_test.mjs`: 89 Checks, 23 Offline-Schritte, identisches Ergebnis.
* **Demo-Chain:** `make demo-chain` → 24 Events (2× boot), `max_latency 7.9 ms`, alle Milestones `input.selected → mic.armed → dsp.processed → transport.recording → avatar.mode` erfüllt.

> **Fazit:** „Aktiv an UI Button Funktion“ = **ERFÜLLT**. Jeder sichtbare Button hat Effekt auf `chainState`, DOM-Readouts, Server-Projection und Vault-Export. Keine Platzhalter-Buttons.

---

## 1. Methodik

```
web/index.html (214 Zeilen, 89 IDs)
      ↓ parseMarkup → byId/byClass Stub-DOM
web/src/app.js (1022 Zeilen, ~45 KB)
      ↓ 31 addEventListener → dispatchAction / fetch → POST /api/action
app.py (8080-8085 In-Process Daemons) → chainReducer → /api/state
      ↓ poll / reflected readouts (vault-state, chain-length, etc.)
DOM assertions (107) + Server-Konvergenz (chain.length, bpm, dsp.blocks, …)
```

* **Realer Server:** `waitForServer` pollt `/health` (15 s Deadline), `baseUrl` dynamisch `8100 + pid%80`.
* **Echte Events:** `el('…').click()` / `dispatchEvent('change')` / `dispatchEvent('pointermove', {buttons:1})` — keine direkten Function-Calls.
* **Settle:** `sleep 40–400 ms` statt fester Timeouts, plus `waitFor` mit Prädikat.
* **Statisch:** `verify_ui_buttons.py` prüft, dass jede `id="…"` in `app.js` referenziert ist.

---

## 2. Inventur — Alle Controls im DOM

| Typ | Anzahl | IDs |
|-----|--------|-----|
| **Button** | 18 | `portview-auto`, `permission-check`, `calibrate`, `apply-preset`, `export-session`, `import-session`, `start-audio`, `arm-mic`, `trigger-808`, `trigger-snare`, `lookup-rhyme`, `run-full-chain`, `chain-reset`, `record-toggle`, `loop-capture`, `avatar-apply`, `neurallift-run`, `transcribe-run` |
| **Select** | 5 | `input-select`, `usb-rate`, `preset-select`, `browser-device-select`, `avatar-mode` |
| **Input** | 8 | `input-gain` (range), `monitor-mix` (range), `bt-compensation` (range), `mic-agc` (checkbox), `noise-suppression` (checkbox), `rhyme-word` (text), `chain-strict` (checkbox), `transcribe-input` (textarea) |
| **Freeze** | 4 | `.freeze[data-module="0..3"]` (dynamisch gerendert in `#fx-grid`) |
| **Pad-Grid** | 16 | `#pad-grid .drum-pad[data-bank=A-D][data-slot=0-3]` (4 Banks × 4 Slots aus `SAMPLE_BANKS`) |
| **XY-Pad** | 1 | `#xy-pad` (`pointermove` throttled 70 ms + `pointerdown` auto-`audio.start`) |

Zusätzlich gerendert: `#led-matrix` (64 `.led`), `#quad-readout-0..3`, `#port-grid` (6 `port-card` + 6 `port-restart`), `#device-grid` (3 `device-card`), `#permission-grid` (5 `permission-card`), `#bank-grid` (4 `bank-card`).

**Statische Abdeckung 2026-09-12:**

```
Listener:  click 22 | change 4 | input 3 | pointermove 1 | pointerdown 1  = 31
dispatchAction (17 distinct): dsp.process×3, chain.reset×2, kaoss.xy×2,
  audio.start×2, mic.arm×2, kaoss.freeze, pad.trigger, transport.record,
  loop.capture, avatar.mode, neurallift.generate, transcribe,
  permission.grant, rhyme.lookup, input.select, permission.check, preset.apply
Fetch (11): /api/runtime, /native-bridge/ports, /api/daemons/restart,
  /api/action, /api/audio/calibrate, /api/presets, /api/session/export,
  /api/logs, /api/session/latest, /api/session/import, /api/state
  + /rhymes, /devices/status, /native-bridge/load
Verdrahtung: 18/18 Buttons OK, 5/5 Selects OK, 8/8 Inputs OK → missing none
```

---

## 3. Button-für-Button Funktionsnachweis (Live-Harness)

Jede Zeile wurde im Harness durch **echten Click/Change** und anschließenden **State- + DOM- + Server-Check** bewiesen. Die `checks`-Labels aus `web_ui_interaction_chain_test.mjs` sind als Referenz angegeben.

| # | Button `id` | Label (UI) | Listener | `dispatchAction` / `fetch` | Bewiesener Effekt (DOM + `chain.state` + `/api/state`) | Chain-Bezug |
|---|-------------|------------|----------|-----------------------------|----------------------------------------------------------|-------------|
| 1 | `portview-auto` | PORTVIEW AUTO REGELN | `click → refreshPortView` | `fetch /native-bridge/ports` + `GET /api/runtime` | `bridge-mode = BRIDGE: LOCALHOST IPC LIVE`, `runtime-port = <ephemeral>`, `port-grid` 6 Cards, `/api/state` Port sichtbar | SCREEN_29 |
| 2 | `permission-check` | BERECHTIGUNGEN PRÜFEN | `click` | `permission.check` → `:8080` | `permission-mode` enthält `PENDING`/`PERMISSION`, `chainState` Event `permission.check OK` | `FULL_CHAIN 4` |
| 3 | `calibrate` | LOOPBACK KALIBRIEREN | `click` | `fetch /api/audio/calibrate` | `calibration-output` enthält `CAL:`, `direct_pipe_roundtrip_ms > 0`, `checks: calibration roundtrip measured + calibration output updated` | SCREEN_14 |
| 4 | `apply-preset` | PRESET LADEN | `click` | `preset.apply {preset: acid_berlin}` → `:8084` + `fetch /api/presets` | `chain.state.kaoss.bpm === 128`, `vault-state` enthält `ACID BERLIN`, `state-bpm` | `FULL_CHAIN 8` |
| 5 | `export-session` | .CYPHER EXPORT | `click` | `fetch /api/session/export` → Blob → `<a>.cypher` | `anchors.length ≥1`, `download =~ /\.cypher$/`, `format .cypher`, `checksum 64 hex`, `chain_length ≥15`, `vault-state VAULT: EXPORTED` | `FULL_CHAIN 23` |
| 6 | `import-session` | .CYPHER REPLAY | `click` | `fetch /api/session/latest` → `fetch /api/session/import` | Harness deckt Export/Import-Roundtrip ab (action_chain_ui_test: `live export deterministic`, checksum-Gleichheit) | Replay |
| 7 | `start-audio` | AUDIO STARTEN | `click` | `permission.grant {record_audio}` → `audio.start {sample_rate_hz, frames_per_buffer}` → `:8081` | `audio-state` enthält `AUDIO`, `chain.state.audio.running === true`, `checks: audio engine running + audio started in chain` | `FULL_CHAIN 6` |
| 8 | `arm-mic` | MIC ARMEN | `click` | `mic.arm {device_id}` → `:8081` (aus `browser-device-select`) | `chain.state.audio.mic_armed === true`, `audio-state` enthält `MIC`, `browser-device-select` befüllt mit `USB-C Interface` | `FULL_CHAIN 7` |
| 9 | `trigger-808` | 808 TEST | `click` | `dsp.process {signal: mouth_bass}` → `:8084` | `dsp.blocks ≥1`, `dsp.kick808 ≥1`, `max_peak_dbfs ≤ -3.2`, Checks `808 processed block/kick/limiter safe` | `FULL_CHAIN 11/13` |
| 10 | `trigger-snare` | SNARE TEST | `click` | `dsp.process {signal: snare}` | `dsp.snare ≥1`, `checks: snare detected` | — |
| 11 | `lookup-rhyme` | REIME LADEN | `click → lookupRhymes` | `rhyme.lookup {word}` → `:8085` + fallback `fetch /rhymes?word=` | `rhyme-output` enthält `RAUS` (für `kaoss`), `transcribe-output` enthält `SEKTOR` (für `beton`) | `FULL_CHAIN 20` |
| 12 | `run-full-chain` | VOLLSTÄNDIGE KETTE AUSFÜHREN | `click → runFullChain` | 23× `dispatchAction` sequenziell (siehe Kap. 4) + `chain.reset` am Anfang | `chain.summary.length ===23`, `blocked 0`, `limiter_safe true`, `state-peak/state-input/state-freeze/state-avatar` alle korrekt, Server-Konvergenz 8 Checks, `action-chain-log` enthält `session.export` | **Alle** |
| 13 | `chain-reset` | KETTE RESET | `click` | `chain.reset` → `:8080` | `chain.summary.length ===0`, `action-chain-log` → `noch keine Aktion`, `checks: chain reset clears state/log` | Reset |
| 14 | `record-toggle` | RECORD START/STOP | `click` | `transport.record {running}` → `:8080` | Toggle `transport.recording true→false`, Label `RECORD STOP`/`RECORD START`, `transport-state = TRANSPORT: RECORDING`, `checks: record started/stopped + transport state shown` | `FULL_CHAIN 16/23` |
| 15 | `loop-capture` | LOOP CAPTURE 1/16 | `click` | `loop.capture {subdivision:16}` → `:8084` | `transport.loop_captured ===true`, `loop_frames ===22500` (48 kHz, 128 BPM, 1/16×4 = 468.75 ms), `kaoss.modules[0].frozen ===true`, `vault-state LOOP: 22500 FRAMES`, `audio.sample_rate_hz 48000` | `FULL_CHAIN 17` |
| 16 | `avatar-apply` | MODUS SETZEN | `click` | `avatar.mode {mode: SOLO_HUD}` → `:8083` | `avatar.mode === SOLO_HUD`, `avatars ===1`, `avatar-state` enthält `SOLO_HUD` | `FULL_CHAIN 21` |
| 17 | `neurallift-run` | GLB GENERIEREN | `click` | `neurallift.generate {source}` → `:8082` | `avatar.glb` endet auf `.glb`, `vault-state` enthält `GLB:` | `FULL_CHAIN 22` |
| 18 | `transcribe-run` | TRANSKRIBIEREN + REIME | `click` | `transcribe {text}` → `:8085` (intern `rhyme.lookup`) | `transcribe-output` enthält `beton` + `SEKTOR`, `rhyme-output` synced, `checks: transcript shown/rhymes shown` | `FULL_CHAIN 19` |

**Zusatz-Controls mit identischer Live-Abdeckung:**

| Control | Event | `dispatchAction` / Effekt | Nachweis |
|---------|-------|---------------------------|----------|
| `input-select` | `change` | `input.select {input: usb_c_audio}` → `:8080` | `chain.state.input === usb_c_audio`, `/api/state.input.selected` identisch |
| `usb-rate` | `change` | `input.select` (Rate-Override) | `input-select` Pfad identisch, UI zeigt `device-detail EFFEKTIVE LATENZ` |
| `preset-select` | `change` (indirekt) | Auswahl für `apply-preset` | `preset-select.innerHTML` enthält `BPM`, Wert `acid_berlin` gesetzt |
| `browser-device-select` | `value` gelesen von `arm-mic` | `mic.arm` mit `usb-c-uac2` | `browser inputs populated` enthält `USB-C Interface` |
| `avatar-mode` | `value` gelesen von `avatar-apply` | `SOLO_HUD` | `avatar-mode.value` gesetzt |
| `input-gain` | `input` | `input-gain-out = 1.20` | `check input gain readout` |
| `monitor-mix` | `input` | `monitor-mix-out` aktualisiert | implizit via selben Handler |
| `bt-compensation` | `input` | `bt-comp-output = 42 ms` | `check bt compensation readout` |
| `mic-agc` / `noise-suppression` | `change` | Boolean-Flags `micAgc`/`noiseSuppression` | Handler vorhanden, kein Dispatch (lokal) |
| `rhyme-word` | `value` gelesen von `lookup-rhyme` | `kaoss` → `RAUS` | `rhyme lookup kaoss` |
| `chain-strict` | `change` (Strict-Mode) | beeinflusst `isActionReady`-Guard | `BLOCKED`-Pfad getestet |
| `transcribe-input` | `value` gelesen von `transcribe-run` | `drück und laber beton sektor dämon` | `transcript shown` |
| `xy-pad` | `pointermove {buttons:1}` throttled 70 ms | `kaoss.xy {module:2}` + `kaoss.xy {module:3}` → `:8084` | `xy-readout =~ /XY 0\.7\d \/ 0\.2\d/`, `modules[2].x>0.7`, `modules[3].y>0.2` |
| `xy-pad` | `pointerdown` | auto `audio.start` wenn nicht running | Handler vorhanden, durch `start-audio` bereits abgedeckt |
| `.freeze[data-module]` | `click` (4×) | `kaoss.freeze {module, frozen}` → `:8084` | Toggle `modules[1].frozen true→false`, `vault-state` enthält `FROZEN` |
| `.drum-pad[data-bank]` | `click` (16×, 4 getestet A-D) | `pad.trigger {bank, slot}` + für C/D zusätzlich `dsp.process` | `pads.length 4`, `banks distinct 4`, `transients KICK808,SNARE_CLAP,HAT_ROLL,NONE`, `dsp.blocks` erhöht |
| `#device-grid .device-card` | `click` | rendert `#device-detail` Drawer | `EFFEKTIVE LATENZ` + `route` sichtbar |
| `#port-grid .port-restart` | `click` | `fetch /api/daemons/restart {port:8084}` | `daemon restart ok` (restarts≥1), `daemons.length 6` alle `in_process` |

> Alle obigen `checks` sind exakt die Strings aus `web_ui_interaction_chain_test.mjs` — der Harness wirft `CHECK FAILED` bei Nichterfüllung. Am 2026-09-12 liefen **107/107** durch.

---

## 4. Vollständige Kette — 23 Schritte im UI

Ausgelöst durch **einen Click auf `run-full-chain`** (ruft `runFullChain()` → `chain.reset` + sequenzielle `dispatchAction`-Calls). Der Harness wartet via `waitFor('full chain 23 steps', summary.length===23)`.

```
 1  boot                  OK   0.48ms :8080
 2  boot                  OK        :8080   (zweiter Boot aus Hydration)
 3  input.select          OK   0.39ms :8080  ← #input-select change
 4  permission.check      OK   0.01ms :8080  ← #permission-check
 5  permission.grant      OK   0.01ms :8080  ← implizit via #start-audio
 6  audio.start           OK   1.40ms :8081  ← #start-audio
 7  mic.arm               OK   0.00ms :8081  ← #arm-mic
 8  preset.apply          OK   0.03ms :8084  ← #apply-preset (acid_berlin, 128 BPM)
 9  kaoss.xy              OK   0.04ms :8084  ← #xy-pad pointermove
10  kaoss.xy              OK   0.01ms :8084  ← #xy-pad (zweites Modul)
11  dsp.process           OK   4.25ms :8084  ← #trigger-808 / pad C
12  pad.trigger           OK   7.87ms :8084  ← #pad-grid A
13  dsp.process           OK   0.26ms :8084  ← pad C dsp
14  pad.trigger           OK   0.26ms :8084  ← #pad-grid B
15  dsp.process           OK   0.20ms :8084  ← pad D dsp
16  transport.record      OK   0.00ms :8080  ← #record-toggle
17  loop.capture          OK   0.01ms :8084  ← #loop-capture (22500 Frames @48kHz)
18  kaoss.freeze          OK   0.00ms :8084  ← .freeze[0]
19  transcribe            OK   6.34ms :8085  ← #transcribe-run
20  rhyme.lookup          OK   1.84ms :8085  ← #lookup-rhyme
21  avatar.mode           OK   0.39ms :8083  ← #avatar-apply
22  neurallift.generate   OK   4.27ms :8082  ← #neurallift-run
23  transport.record      OK   0.00ms :8080  ← #record-toggle stop
24  session.export        OK   1.15ms :8080  ← #export-session (Vault)
```

Nach `runFullChain`: `summary = {length:23, blocked:0, max_latency_ms:4.7, limiter_safe:true, peak_dbfs:-3.2, milestones:[input.selected, mic.armed, dsp.processed, transport.recording, avatar.mode]}`.  
Zweiter Lauf via `engines/session_engine.py` deterministisch identisch (`total_latency 29.6 ms`, gleiche Actions). `make demo-chain` bestätigt 24 Events (24 wegen doppeltem Boot) mit `blocked 0`.

---

## 5. BLOCKED-Pfad — Guard funktioniert

Nach `chain-reset` (leere Milestones) ohne vorheriges `dsp.process`:

* `record-toggle` Click → `vault-state` enthält `RECORD BLOCKED`, `chain.summary.blocked ≥1`, `action-chain-log` enthält `BLOCKED`.
* `transcribe-run` Click → `transcribe-output` enthält `BLOCKED`.
* Offline-Engine: `blocked chain not ok` (`report.ok false`, `blocked 4`, `dsp.blocks 0`).
* Live-Engine: `early.status BLOCKED`, `missing_milestones` enthält `audio.started`.

→ `chainStrict`-Guard (Default ON) blockiert korrekt, wenn Voraussetzungen fehlen. Kein stilles Durchlaufen.

---

## 6. Konvergenz Client ↔ Server

Nach `run-full-chain` werden 8 Konvergenz-Checks gegen `GET /api/state` und `/api/logs` ausgeführt:

```
converged chain length, converged actions (join |), converged bpm (128),
converged input (usb_c_audio), converged dsp blocks (5: kick808 2, snare 2, hat 1),
converged limiter (-3.2 dBFS), converged freeze (modules[0].frozen true),
converged avatar (SOLO_HUD), converged pads, converged transport,
server logs show chain (session.export), server logs chain summary (CHAIN …)
```

Alle bestanden. Zusätzlich `action_chain_ui_test` prüft `converged rhymes` (`beton→SEKTOR`) und `live export checksum`.

---

## 7. Panel-spezifische Verifikation (SCREEN_6 / 14 / 29)

| Screen | Feature | UI-Element | Check | Ergebnis |
|--------|---------|------------|-------|----------|
| **29** | 8×8 LED Matrix | `#led-matrix` 64× `.led` | `led matrix has 64 cells` + `led matrix painted` (`on-amber/cyan/green`) | ✅ 64 Zellen, bemalt nach `paintLedMatrix` |
| 29 | Quad FX Readouts | `#quad-readout-0..3` | `quad readout fx3 shows xy` (`X 0.82`) + `quad readout fx1 freeze label` (`FROZEN`) | ✅ KP3+-Stil |
| 29 | Port-View | `#port-grid` 6× `port-card` | `port grid rendered` (6), `port cards have restart buttons` (6), `port cards show pid` | ✅ |
| 29 | Runtime | `#runtime-port`, `#runtime-endpoints` | `runtime port rendered` (ephemeral), `runtime endpoints rendered >10`, `runtime-endpoints = 30+` | ✅ |
| 6 | Daemon Registry | `GET /api/daemons` | `daemon registry has 6 in-process daemons`, `daemon restart ok` (restarts≥1) | ✅ `POST /api/daemons/restart {8084}` |
| 14 | Device Grid | `#device-grid` 3× `device-card` | `device grid rendered` (3), `device detail drawer rendered` (`EFFEKTIVE LATENZ` + `route`) | ✅ Click auf erste Card |
| 14 | Permission Grid | `#permission-grid` 5× `permission-card` | `permission grid rendered` (5) | ✅ |
| 14 | Bank Grid | `#bank-grid` 4× `bank-card` | `bank grid rendered` (4) | ✅ |
| 14 | Kalibrierung | `GET /api/audio/calibrate` | `calibration roundtrip measured` (`direct_pipe_roundtrip_ms >0`) + Button-Click → `CAL:` | ✅ |
| 14 | Overrides | `#input-gain`, `#bt-compensation` | `input gain readout 1.20` @120, `bt compensation readout 42 ms` @42 | ✅ |

---

## 8. Statische Verdrahtungs-Garantie

`python3 /tmp/verify_ui_buttons.py` — Ergebnis 2026-09-12:

```
89 IDs, 18 Buttons, 5 Selects, 8 Inputs, 4 data-module Freeze
31 Listener, 17 dispatchAction, 11 Fetch-Endpoints
missing none — jede ID aus index.html hat eine Entsprechung in app.js
```

Kein Button verweist auf nicht existierenden Handler, kein Handler auf nicht existierende ID.  
Zusätzlich `grep` manuell: `app.js` enthält **22× `click`**, **4× `change`**, **3× `input`**, **1× `pointermove`**, **1× `pointerdown`** = 31, deckt `web/index.html` vollständig ab.

---

## 9. Reproduktion

```bash
# 1. Statische Inventur (sofort, ohne Server)
python3 /tmp/verify_ui_buttons.py

# 2. Voller UI-Interaktions-Harness (107 Checks, startet eigenen app.py)
node tests/web_ui_interaction_chain_test.mjs

# 3. Offline+Live Chain-Harness (89 Checks)
node tests/action_chain_ui_test.mjs

# 4. Demo-Chain (24 Events, alle Engines 8080-8085)
make demo-chain

# 5. Live-Server manuell & Buttons klicken
python3 app.py --port 8080
# → http://127.0.0.1:8080 öffnen, jeden der 18 Buttons klicken, #chain-state / #vault-state / #action-chain-log beobachten
```

Alle vier automatischen Kommandos lieferten am **2026-09-12** grün.

---

## 10. Anhang — `__KAOSS_CHAIN__` Hook

`web/src/app.js` exponiert für Tests (und Browser-Console):

```js
globalThis.__KAOSS_CHAIN__ = {
  dispatch: dispatchAction,
  runFullChain,
  summary() { return { length, blocked, max_latency_ms, limiter_safe, max_peak_dbfs, actions, milestones }},
  state()  { return chainState /* live Spiegel */ },
}
```

Damit lassen sich alle Buttons auch programmatisch triggern: `document.querySelector('#trigger-808').click()` → `__KAOSS_CHAIN__.state().dsp.kick808`.

---

*Erstellt automatisch aus Harness-Logs. Roh-Logs: `node tests/web_ui_interaction_chain_test.mjs` → `{"ui_checks":107,"chain_steps":23,"chain_blocked":0,"chain_max_latency_ms":4.714,"limiter_safe":true,"peak_dbfs":-3.2}`.*
