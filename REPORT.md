# AUDIT REPORT — 2026-09-12

Repo: `dang88bang-pixel/kaospad` · Branch: `arena/01a08bf1-kaospad` · Clone: vollständig (nicht shallow), 9 Remote-Branches, 42 Commits.

Werkzeuge (reproduzierbar, keine Einmal-Greps):

| Zweck | Befehl |
|---|---|
| Inventar + GAP-Matrix | `python3 scripts/audit_inventory.py` |
| Gesamtsuite | `make test` |
| UI im echten Browser | `make test-ui` (Chromium) / `make test-ui-list` (Discovery) |

---

## Phasenabschluss

- [x] **Phase 1 — Audit:** 113 Dateien / 19.889 Zeilen inventarisiert. Ergebnis: **1 PLACEHOLDER, 3 STUB, 109 REAL**, 0 TODO/FIXME-Kommentarmarker (klassische `// TODO`-Marker: **null** im Repo), 41 Prosa-Marker in 20 Dateien, 77 Dummy-Rückgaben, 0 `NotImplementedError`, 0 unauflösbare lokale Imports. Artefakte: `docs/audit/INVENTAR.csv` (Zeile pro Datei mit Beleg), `docs/audit/GAP-MATRIX.csv` (462 Forderungen).
- [ ] **Phase 2 — Ersetzung:** **0 Dateien ersetzt.** Regel „nur mit Zustimmung pro Datei" — Kandidatenliste unten, Freigabe ausstehend.
- [~] **Phase 3 — Integration & Binding:** IPC, Persistenz und Error-Handling sind real und getestet; **Retry/Circuit-Breaker fehlen komplett** (Beleg unten). Protobuf/FlatBuffers bewusst nicht eingeführt (Loopback-JSON, begründet).
- [~] **Phase 4 — Funktionstest:** `make test` **exit 0** lokal (22 Ergebniszeilen). CI: Native DSP, Offline-Kette und WASM-Parität **grün**; Playwright nach 2 Root-Cause-Fixes **noch nicht im Browser nachverifiziert** (GitHub-Zugang ausgefallen, siehe Blocker).
- [ ] **Phase 5 — Fehlerresistenz:** Graceful Degradation belegt (2 Pfade). **Watchdog, Log-Rotation und Bug-Report-File existieren nicht** (grep: 0 Treffer).

---

## Phase 1 — Detail

### Nicht-REAL-Dateien (vollständige Liste, mit Beleg)

| Status | Datei | Beleg (Originalzeile) | Bewertung |
|---|---|---|---|
| PLACEHOLDER | `engines/neurallift_360/scripts/download_weights.py` | `"whisper-tiny-multilingual-int8.tflite": "offline-placeholder:whisper:5.0.0"` | ⛔ echte Modellgewichte sind lizenzpflichtig; Shim schreibt Platzhalter-Dateien und sagt das |
| STUB | `engines/neurallift_360/engine_service.py` | `"""Offline NeuralLift-360 daemon stub.` | 🧪 HTTP-Facade ohne Inferenz |
| STUB | `engines/neurallift_360/glb.py` | `file instead of a filename stub. No cloud, no ML weights.` | **Marker veraltet** — die Datei schreibt ein reales GLB (gemessen: `glb=2684B` in `full_chain_attributes_test`) |
| STUB | `android/app/src/main/cpp/audio_flinger_hook.cpp` | `// Portable deterministic HAL simulator: native Android builds replace this shim` | ⛔ echter HAL braucht Gerät/NDK |

### Teilbereiche mit Ersatz-Implementierung (Datei selbst REAL)

`engines/session_engine.py` (Whisper-Shim für `transcribe`), `engines/localhost_ipc_suite.py` (`0.4ms shim`-Latenzangaben), `web/src/app.js` + `web/index.html` (UI-Labels `24-bit capture shim`, `LC3plus shim`), `scripts/build_signed_apk.py` (Stub-DEX, PLACEHOLDER-Marker Zeile 654/675), `tests/audio_latency_e2e_test.cpp` (Simulator), `.github/workflows/*.yml`. Vollständig mit Zeilennummern in `docs/audit/INVENTAR.csv`, Spalte `Marker`/`Beleg`.

### Methodik (warum nicht einfach `grep TODO`)

`grep -rnE "//(TODO|FIXME|MOCK|SHIM|STUB|PLACEHOLDER|HACK)"` liefert in diesem Repo **0 Treffer** — Ersatz-Implementierungen stehen hier in Prosa, Docstrings und UI-Strings (`daemon stub`, `HAL simulator`, `offline-placeholder:`, `0.4ms shim`). Der Klassifikator wertet deshalb die **Kopfzone** (erste 20 Zeilen = Selbstbeschreibung der Datei) für den Status aus und führt Treffer tief im Code als „Ersatz-Implementierung nur in Teilbereich". Test- und Build/CI-Dateien werden nicht über Marker abgewertet (sie werden ausgeführt bzw. vom Tooling referenziert). Eine Datei, die das Wort „Stub" nur *erwähnt* (z. B. die Playwright-Spec „Ergänzt den DOM-Stub-Harness"), bleibt REAL.

### GAP-Matrix (Auszug, Quelle `docs/FULL_IMPLEMENTATION_TODO.md`)

462 Forderungen: **371 offene Checkboxen**, 7 mit 🧪 SHIM, 2 mit ⛔ BLOCKED.

| Forderung | Doku-Status | Pfade vorhanden | Code-Status |
|---|---|---|---|
| AAudio-Stream + Fixture-Facade | ✅ DONE / ⛔ Gerät | `aaudio_input_engine.cpp`, `audio_input_engine.*` | REAL (19 Checks in `audio_input_processor_test`) |
| WASM-DSP-Einstieg + JS-Spiegel | ✅ DONE / ⛔ emcc | `web/wasm/dsp_core_wasm.cpp`, `web/src/dsp-core.js` | REAL für ABI-Modul; Emscripten-Modul braucht emcc |
| Localhost IPC Suite | ✅ DONE / 🧪 SHIM | `engines/localhost_ipc_suite.py` | REAL (Sockel), Latenzwerte sind Shim |
| Device Matrix USB/Mic/BT | ✅ DONE / 🧪 SHIM | `engines/device_matrix.py` | REAL (statische IDs + Live-Probe) |
| Offline Reim-Matrix | ✅ DONE / 🧪 SHIM | `engines/whisper_offline/rhyme_matrix.py` | REAL (SQLite), kein echtes Whisper |
| NeuralLift HTTP Fallback | ✅ DONE / 🧪 SHIM | `engines/neurallift_360/engine_service.py` | STUB |
| Android Scaffold Build | 🧪 SHIM | `android/gradlew` | Gradle-Wrapper-Jar fehlt lokal |
| Desktop Rust Host Scaffold | 🧪 SHIM | `desktop/`, `desktop/src-tauri/` | Scaffold |

---

## Phase 2 — Ersetzung (wartet auf Freigabe)

Keine Datei wurde ohne Zustimmung geändert. Kandidaten mit Aufwand und Risiko:

| # | Datei | Was ersetzt würde | Aufwand | Risiko |
|---|---|---|---|---|
| P2-1 | `engines/neurallift_360/glb.py` | **nur Docstring** — „stub" ist veraltet, die Datei erzeugt ein reales GLB | 2 min | keines |
| P2-2 | `engines/neurallift_360/engine_service.py` | echte Offline-Inferenz-Facade: Mesh aus Pose-Landmarks statt Fixtures, API-kompatibel | ~1 h | mittel (Tests anpassen) |
| P2-3 | `scripts/build_signed_apk.py` | echtes DEX statt Stub-DEX | ⛔ ohne JDK/`d8` nicht machbar | — |
| P2-4 | `download_weights.py` | echte `.tflite`-Gewichte | ⛔ lizenzpflichtig | — |
| P2-5 | `audio_flinger_hook.cpp` | echter AAudio-HAL | ⛔ braucht Gerät | — |

Regelkonform werden vor jeder Ersetzung Backup (`backups/phase2/<datei>.bak`) und der Kommentar `-- REAL-IMPLEMENTATION <datum>` angelegt.

---

## Phase 3 — Integration & Binding

| Forderung | Status | Beleg |
|---|---|---|
| IPC 8080–8085 mit echten Sockets | ✅ REAL | `zero-cloud localhost IPC gate passed for ports 8080-8085`; zusätzlich Unix-Datagram-Pipes `KPCM/KCTL` für Capture-Clients (`live capture dsp ok: 40 checks // real blocks=1`) |
| Protobuf/FlatBuffers | 🧩 bewusst nicht | Loopback-only, JSON/Text; Schema-Serialisierung würde Binary-Abhängigkeit ohne Nutzen bringen (keine externen Peers). Entscheidung dokumentiert, nicht verschwiegen |
| JNI/USB/BT/Audio-Callback mit Error-Handling + Timeout | 🟡 teilweise | Timeouts: `audio_capture.py` 12, `event_stream.py` 6, `app.py` 4, **`local_audio_probe.py` 0**; `except`-Blöcke: `audio_capture.py` 10, `localhost_ipc_suite.py` 1, `dsp_chain.py` 0, `event_stream.py` 0 |
| State-Machine persistent (kein In-Memory-Only) | ✅ REAL | `session persist + replay ok: 71 checks // store=dist/sessions checksum=0027d4f4a84c chain=23`; Reim-Matrix in SQLite |
| Retry-Logik + Circuit-Breaker | ❌ fehlt | `grep -rniE "retry|circuit|backoff"` über `engines/ app.py scripts/` → einziger Treffer ist das SSE-Feld `retry: 2000`. Es gibt **keine** externen Calls (Zero-Cloud-Gate blockiert sie), aber auch keine Retry-Politik für lokale Sockets/Prozesse |

---

## Phase 4 — Funktionstest

`make test` → **exit 0** (letzter lokaler Lauf). Auszug:

```text
Limiter peak=-3.2 dBFS threshold=-3.2 dBFS · Transient kind=1 freq=52 latency_ms=1
audio input processor + engine fixture verified: 19 checks
zero-cloud localhost IPC gate passed for ports 8080-8085 (shared action chain)
kaoss one-app e2e contract passed
vollständige Aktions- und Interaktionskette verifiziert: 236 Checks, 23 Ketten-Schritte, max 9.443 ms, peak -3.2 dBFS
funktionale Ausführung aller Aktionen: 40 Checks, catalogue=19
browser action & interaction chain verified: 89 checks
browser UI action & interaction chain verified: 107 checks
zero-cloud socket guard passed: 24 chain steps, 3 loopback connections, 2 external attempts blocked
session persist + replay ok: 71 checks
live capture dsp ok: 40 checks // real blocks=1 fixture blocks=0
sse events stream ok: 24 checks // push_latency=709.5ms   +  sse reducer hygiene verified: 14 checks
dsp parity ok: 274 checks // cases=7 // implementations=wasm+js+python+native
signed apk verified · native audio bridge contract verified: 39 checks
release artifact guard verified: 13 checks · gradle wrapper contract verified: 4 checks
```

### Playwright (echter Browser, Chromium in CI)

Letzter **lesbarer** CI-Lauf: 5 von 7 Specs grün. Zwei Fehler, beide als echte Produktfehler root-cause-analysiert und behoben:

1. `#chain-state` zeigte `45 SCHRITTE` statt 23 → dasselbe Event wurde über fetch-Antwort **und** SSE-Push reduziert. Seq-Wache reicht nicht (nach `chain.reset` zählt die Seq bei 1 neu, BLOCKED-Events erhöhen sie nicht — belegt: `reset seq=1, blocked seq=1`). Fix: `applyChainEvent()` mit Dedup über `seq:action:t_ms`. Simulation der Browser-Reduktion gegen den Server: **23 angewendet / 19 Duplikate übersprungen**.
2. Danach `7 SCHRITTE` → `hydrateFromServer()` setzte den Zustand mitten in der laufenden Kette mit `defaultState()` zurück. Fix: Hydration ergänzt nur fehlende Events, `runFullChain()` awaitet `hydrationPromise`.
3. `TypeError: chainState.kaoss.modules.filter is not a function` → SSE liefert `detail_summary`, in dem Sammlungen als `"<4 items>"` stehen; der Reducer übernahm sie (`next.kaoss = detail.kaoss`). Fix: `isKaossState()`/`usableDetail()`-Wachen + `scalarDetail()` im SSE-Pfad. Regression: `tests/sse_reducer_hygiene_test.mjs` (14 Checks, läuft in `make test-sse`).
4. `404` in der Konsole → `createDspCore()` importierte blind `../wasm/dsp_core.mjs` (ohne emcc nicht gebaut). Fix: `/api/wasm` meldet `emscripten_module`, der Client fragt nach; `send_wasm_asset()` liefert jetzt auch `web/wasm/*` aus.

**Offen:** die Browser-Nachverifikation dieser Fixes — GitHub-Zugang (Token) ist ausgefallen, CI-Status und Push sind blockiert.

---

## Phase 5 — Fehlerresistenz

| Forderung | Status | Beleg |
|---|---|---|
| Graceful Degradation: fehlendes Modell → Shim mit Hinweis, kein Crash | ✅ belegt | WASM fehlt → JS-Kern (`createDspCore -> JS-Kern ok`); Capture ohne Hardware → `real_capture: false` + `fixture` (`live capture dsp ok`); Paritätstest prüft beide Pfade (274 Checks) |
| Watchdog: hängender Prozess nach 5 s neu starten | ❌ fehlt | `grep -rniE "watchdog"` → 0 Treffer |
| Log-Rotation | ❌ fehlt | `grep -rniE "rotat"` → 0 Treffer |
| Alle Exceptions gefangen + Bug-Report-File | ❌ fehlt | `grep -rniE "bug.?report"` → 0 Treffer; `engines/event_stream.py`, `dsp_chain.py`, `local_audio_probe.py` haben 0 `except`-Blöcke |

---

## Verbleibende ⛔-Blocker

1. **GitHub-Zugang:** `GH_TOKEN` ungültig (`gh auth status` → `Bad credentials`). Push und CI-Status blockiert; 3 lokale Commits warten (`bed27f6`, `a28389a`, `f9fef47`). **Workaround:** Arbeit ist lokal committed und im Workspace gesichert; nach Reconnect in Arena: `git push origin arena/01a08bf1-kaospad`.
2. **Playwright-Browser in der Sandbox:** `cdn.playwright.dev` gesperrt, apt hat kein Chromium (`Unable to locate package`). **Workaround:** `make test-ui-list` prüft die Specs (7/7 discoverbar), `make test-ui` meldet SKIP mit Grund, CI-Job `ui-browser` führt sie mit Chromium aus.
3. **Log-/Artefakt-Download von CI:** `results-receiver.actions.githubusercontent.com` und `*.blob.core.windows.net` liefern `EOF`. **Workaround:** der Job postet seine Fehler selbst als PR-Kommentar (`permissions: pull-requests: write`).
4. **Echte Modellgewichte** (Whisper/MiDaS int8): lizenzpflichtig → `offline-placeholder:`-Shim.
5. **Echter AAudio/Oboe-HAL und BLE-LC3plus-Decoder:** brauchen Gerät bzw. Plattform-Codec; Loopback-Pipes übernehmen decodierte PCM-Blöcke.
6. **Emscripten (`emcc`)** für `web/wasm/dsp_core.mjs`: nicht installierbar (`apt-get` findet es nicht). **Workaround:** ABI-Modul `dist/wasm/kaoss_dsp.wasm` wird mit `ziglang` gebaut und ist paritätsgeprüft; UI nutzt sonst den JS-Kern.
7. **Echtes DEX in der signierten APK:** kein JDK/`d8` → Stub-DEX (PLACEHOLDER-Marker in `build_signed_apk.py`).
8. **Gradle-Wrapper-Jar:** fehlt lokal (kein JDK/Netz) → `scripts/fetch_gradle_wrapper.sh`, CI stellt Gradle 8.7.

## Verbleibende TECH-DEBT

1. Retry-Logik + Circuit-Breaker für lokale Socket-/Prozessaufrufe (Phase 3, fehlt komplett).
2. Watchdog (5 s), Log-Rotation, Bug-Report-File (Phase 5, fehlt komplett).
3. `engines/local_audio_probe.py`, `event_stream.py`, `dsp_chain.py`: keine `except`-Blöcke — Fehler laufen unkontrolliert nach oben.
4. Veralteter „stub"-Marker in `engines/neurallift_360/glb.py` (funktional real, 2684 B GLB).
5. `.github/workflows/multiplatform-ci-cd.yml` scheitert seit jeher in 0 s mit „workflow file issue" — **repo-weit und vorbestehend** (identisch auf `arena/01a090e3-kaospad`), nicht durch diese Arbeit verursacht.
6. Zwei WASM-Bauwege (`dist/wasm/kaoss_dsp.wasm` via zig/ABI, `web/wasm/dsp_core.mjs` via emcc) — zusammenführen, sobald emcc verfügbar ist.
7. `make test` bricht, wenn gleichzeitig ein Server auf `0.0.0.0` läuft (Zero-Cloud-Gate `offline_ipc_socket_test` verlangt Loopback-Bindung) — korrektes Verhalten, aber als Hinweis dokumentieren.
8. 371 offene Checkboxen in `docs/FULL_IMPLEMENTATION_TODO.md` (siehe `docs/audit/GAP-MATRIX.csv`).
