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
- [x] **Phase 2 — Ersetzung:** **2 Dateien ersetzt** (P2-1 `glb.py`-Docstring, P2-2 `engine_service.py` als echter Mesh-Daemon) — nur die freigegebenen, API-kompatibel, mit `-- REAL-IMPLEMENTATION 2026-09-12` und Original in `backups/phase2/`. Folgekorrektur der davon abhängigen Zahlen in `session_engine.py`, `localhost_ipc_suite.py`, `app.py`. P2-3/P2-4/P2-5 bleiben ⛔ und sind unangetastet.
- [x] **Phase 3 — Integration & Binding:** IPC, Persistenz und Timeouts waren bereits real; neu sind (a) `engines/resilience.py` — **Retry mit exponentiellem Backoff + Jitter, Circuit Breaker (CLOSED/OPEN/HALF_OPEN), harte Deadline** — verdrahtet an drei realen Grenzen (ALSA-Probe, Capture-Backends, jede `/api/action`), Beleg `resilience verified: 65 checks`; und (b) **FlatBuffers für die PCM-Pfade** — Schema `proto/kaoss_pcm.fbs`, abhängigkeitfreier Codec `engines/kpcm_flatbuffers.py`, Rahmen `b"KPCF"` auf der Unix-Pipe und auf TCP 8081, Beleg `flatbuffers pcm verified: 60 checks` (inkl. Kreuzdecodierung gegen den offiziellen `flatc`-Codec in beide Richtungen); und (c) **Error-Handling an den restlichen Grenzen** — `dsp_chain.process_block()` meldet kaputte Abtastrate/Samples als vollständigen Report mit `ok=false`, `event_stream.py` verwirft fehlerhafte Events und zählt sie, Beleg `dsp/event error handling verified: 30 checks`.
- [x] **Phase 4 — Funktionstest:** `make test` **exit 0** lokal, **28 Ergebniszeilen** (7 neue Suiten: resilience, watchdog, log-rotation, bug-report, engine-service, flatbuffers-pcm, dsp-error-handling). CI-Run `34713717145`: **4/4 Jobs grün**, Playwright **7 von 7 Specs** im echten Chromium.
- [x] **Phase 5 — Fehlerresistenz:** alle drei Bausteine gebaut, jeder mit eigenem Test — **Watchdog** (`watchdog verified: 28 checks`, Neustart bei ≥ 5 s Stille, Restart-Limit → `degraded`), **Log-Rotation** (`log rotation verified: 25 checks`, harte Grenze `max_bytes × (backups+1)`), **Bug-Report-File** (`bug report verified: 42 checks`, Secret-Redaktion + deutsche Meldung ohne Stack). Graceful Degradation zusätzlich belegt (2 Pfade).

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

## Phase 2 — Ersetzung (P2-1 und P2-2 freigegeben und erledigt)

Regel eingehalten: ersetzt wurde **nur** nach Freigabe pro Datei, mit Backup in
`backups/phase2/<datei>.bak` und dem Marker `-- REAL-IMPLEMENTATION 2026-09-12`.

| # | Datei | Status | Was jetzt wirklich passiert |
|---|---|---|---|
| P2-1 | `engines/neurallift_360/glb.py` | ✅ ersetzt | Veralteter „stub"-Docstring korrigiert; neue Landmark-Mesh-API `build_landmark_glb()` + `glb_stats()` (liest Vertices/Triangles/Bones/Größe **aus den GLB-Bytes**). `build_capsule_glb` unverändert: `kaoss` → 2676 B, Magic `glTF`. |
| P2-2 | `engines/neurallift_360/engine_service.py` | ✅ ersetzt | Echter Daemon: erzeugt pro Anfrage ein glTF-2.0-Mesh aus 33 Pose-Landmarks (Röhren über die MediaPipe-Bone-Topologie), schreibt es nach `dist/avatars/`, liest die Kennzahlen aus der Datei zurück und meldet ehrlich `inference: false`. API-kompatibel (`/health`, `/mesh/default`) plus `POST /mesh`; 400 bei ungültigen Landmarks; bindet nur Loopback. |
| — | `engines/session_engine.py` | ✅ nachgezogen | Fallback-Avatar meldet die echten Kapsel-Kennzahlen (`rig_bones: 0`, `rigged: false`) statt der erfundenen `45000/18000/24`; `neurallift.generate` delegiert auf `mesh_payload()` und misst `generate_ms` (vorher hartcodiert `1800.0`). |
| — | `engines/localhost_ipc_suite.py`, `app.py` | ✅ nachgezogen | Port 8082 und `/mesh/default` liefern dieselbe echte Payload wie der Daemon. |
| P2-3 | `scripts/build_signed_apk.py` | ⛔ nicht angetastet | echtes DEX ohne JDK/`d8` nicht machbar |
| P2-4 | `download_weights.py` | ⛔ nicht angetastet | echte `.tflite`-Gewichte lizenzpflichtig |
| P2-5 | `audio_flinger_hook.cpp` | ⛔ nicht angetastet | echter AAudio-HAL braucht Gerät |

**Messbare Invarianten nach der Ersetzung** (`tests/neurallift_engine_service_test.py`, 33 Checks):
780 Vertices / 1248 Triangles / 27.080 B, identische SHA-256 bei gleicher Pose
(`a6bd3e40f45c…`), andere Pose → andere SHA-256, HTTP 200/400/404-Vertrag,
Nicht-Loopback-Bind wird verweigert.

---

## Phase 3 — Integration & Binding

| Forderung | Status | Beleg |
|---|---|---|
| IPC 8080–8085 mit echten Sockets | ✅ REAL | `zero-cloud localhost IPC gate passed for ports 8080-8085`; zusätzlich Unix-Datagram-Pipes `KPCM/KCTL` für Capture-Clients (`live capture dsp ok: 40 checks // real blocks=1`) |
| Protobuf/FlatBuffers für PCM | ✅ REAL | Schema `proto/kaoss_pcm.fbs` (`Kaoss.Ipc.PcmBlock`), Codec `engines/kpcm_flatbuffers.py` **ohne externe Abhängigkeit**, Rahmen `b"KPCF"` + FlatBuffer. Akzeptiert auf der Unix-Datagram-Pipe (`audio_capture._drain`) und auf TCP 8081 (`PCMHandler`); JSON bleibt Steuerkanal (`KCTL`, `/api/*`). Test `flatbuffers pcm verified: 60 checks`: Roundtrip, Determinismus, 6 Fehlerfälle als `FlatBufferError`, echte Pipe (KPCF **und** KPCM, kaputte Frames zählen statt zu blockieren), SHA-256-Parität raw == FlatBuffers, plus `flatc`-Kreuzdecodierung in beide Richtungen. Ohne `flatc` meldet der Test die Referenzprüfung ehrlich als übersprungen (54 Checks) |
| JNI/USB/BT/Audio-Callback mit Error-Handling + Timeout | ✅ REAL | `engines/resilience.py` schützt die lokalen Grenzen: `local_audio_probe.py` (vorher 0 Timeouts, 0 `except`) läuft jetzt hinter Retry + Breaker `alsa_probe`; `audio_capture.py` öffnet Backends hinter `capture:open:<name>` und fängt `read_block`-Ausnahmen (`capture:read:<name>`), der Audio-Callback wirft nicht mehr durch. Nachgezogen: `dsp_chain.process_block()` prüft Abtastrate/Samples und liefert bei kaputten Eingaben einen vollständigen Report mit `ok=false` statt `ZeroDivisionError`; `event_stream.py` verwirft fehlerhafte Events und meldet `errors`/`last_error` in `stats()`. Test: `dsp/event error handling verified: 30 checks` |
| State-Machine persistent (kein In-Memory-Only) | ✅ REAL | `session persist + replay ok: 71 checks // store=dist/sessions checksum=0027d4f4a84c chain=23`; Reim-Matrix in SQLite |
| Retry-Logik + Circuit-Breaker | ✅ REAL | `engines/resilience.py`: `RetryPolicy` (exponentieller Backoff, Jitter, absolute Deadline), `CircuitBreaker` (CLOSED → OPEN → HALF_OPEN, `failure_threshold`, `reset_timeout_s`, `half_open_max`), `call_with_timeout`, `ResilienceRegistry`. Verdrahtet: ALSA-Probe, Capture-Open/-Read, jede `/api/action` (`action:<name>`, sonst 500/503 statt hängender Verbindung), sichtbar über `GET /resilience` (8080). Test: `resilience verified: 65 checks` |

---

## Phase 4 — Funktionstest

`make test` → **exit 0** (letzter lokaler Lauf, 28 Ergebniszeilen). Auszug:

```text
Limiter peak=-3.2 dBFS threshold=-3.2 dBFS · Transient kind=1 freq=52 latency_ms=1
audio input processor + engine fixture verified: 19 checks
resilience verified: 65 checks // retry+backoff // circuit breaker CLOSED/OPEN/HALF_OPEN // deadline
watchdog verified: 28 checks // Neustart nach >5 s Stille // Restart-Limit + degraded // Hintergrundschleufe
log rotation verified: 25 checks // Grenze max_bytes*(backups+1) // JSON Lines // Schreibfehler ohne Crash
bug report verified: 42 checks // JSON in dist/bug-reports // Secrets redigiert // sys+thread excepthook
flatbuffers pcm verified: 60 checks // Schema proto/kaoss_pcm.fbs // KPCF-Frame auf echter Pipe // SHA-256-Parität raw==flatbuffers
dsp/event error handling verified: 30 checks // ok=False statt Exception // Event-Fehler gezählt
neurallift engine service verified: 33 checks // mesh 780v/1248t // 27080 B // inference=false
zero-cloud localhost IPC gate passed for ports 8080-8085 (shared action chain)
kaoss one-app e2e contract passed
vollständige Aktions- und Interaktionskette verifiziert: 239 Checks, 23 Ketten-Schritte, max 7.527 ms, peak -3.2 dBFS
funktionale Ausführung aller Aktionen: 40 Checks, catalogue=19
browser UI action & interaction chain verified: 112 checks
chain attributes verified: 23 steps, 22 state keys, glb=27076B, peak=-3.2 dBFS
session persist + replay ok: 71 checks // store=dist/sessions checksum=0027d4f4a84c chain=23
live capture dsp ok: 40 checks // real blocks=1 fixture blocks=0
sse events stream ok: 24 checks // push_latency=708.0ms   +  sse reducer hygiene verified: 14 checks
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

**Status: 7 von 7 Specs grün in CI** (Run `34713717145`, Commit `7d1a736`: `✓ Native C++ DSP` · `✓ Offline Action & Interaction Chain` · `✓ WASM DSP Core == Native == Python Mirror` · `✓ Playwright Browser UI in 2m4s`).

5. Zuletzt scheiterte nur noch Spec 1 an genau einer Konsolenmeldung `Failed to load resource: 404`. Ursache: `loadSessionStore()` holte beim Boot immer `/api/session/latest`, und der Server antwortet bei leerem Store **bewusst** mit 404 (getesteter Vertrag, `session_persist_replay_test.py:257`) — auf einer frischen Installation ist der Store aber immer leer. Fix im Client: erst `/api/sessions` (immer 200) abfragen, `/api/session/latest` nur bei vorhandenem Eintrag. Regression: `web_ui_interaction_chain_test.mjs` prüft beide Fälle (112 Checks); Negativtest mit deaktiviertem Guard schlägt erwartungsgemäß fehl mit `["GET /api/sessions","GET /api/session/latest"]`.

---

## Phase 5 — Fehlerresistenz

| Forderung | Status | Beleg |
|---|---|---|
| Graceful Degradation: fehlendes Modell → Shim mit Hinweis, kein Crash | ✅ belegt | WASM fehlt → JS-Kern (`createDspCore -> JS-Kern ok`); Capture ohne Hardware → `real_capture: false` + `fixture` (`live capture dsp ok`); Paritätstest prüft beide Pfade (274 Checks) |
| Watchdog: hängender Prozess nach 5 s neu starten | ✅ REAL | `engines/watchdog.py`: Heartbeat-Überwachung, Neustart bei **≥ 5 s** Stille (`DEFAULT_TIMEOUT_S = 5.0`), `max_restarts` → Zustand `degraded` (kein Restart-Sturm), Fehler in der Restart-Funktion werden protokolliert statt geworfen, Hintergrundschleife. In `app.py` für alle 6 logischen Engine-Rollen aktiv, sichtbar über `GET /api/watchdog`. Test: `watchdog verified: 28 checks` |
| Log-Rotation | ✅ REAL | `engines/log_rotation.py`: JSON-Zeilen, vorausschauende Rotation, harte Obergrenze `max_bytes × (backups+1)`, Umlaute als UTF-8, Schreib-/`mkdir`-Fehler crashen nie. In `app.py` als `dist/logs/one-app.log` (256 KiB × 4), Zustand in `GET /api/logs` unter `rotation`. Test: `log rotation verified: 25 checks` |
| Alle Exceptions gefangen + Bug-Report-File | ✅ REAL | `engines/bug_report.py`: schreibt `dist/bug-reports/bug-<stempel>-<sha8>.json` (Traceback, Kontext, Umgebung), redigiert `token`/`api_key`/`password`/`secret` zu `[REDACTED]`, liefert eine deutsche Meldung ohne Stack, installiert `sys.excepthook` **und** `threading.excepthook`. `do_GET`/`do_POST` in `app.py` antworten mit 500 + Meldung statt Traceback; Liste über `GET /api/bug-reports`. Kein Upload (Zero-Cloud). Test: `bug report verified: 42 checks` |

---

## Verbleibende ⛔-Blocker

1. ~~**GitHub-Zugang**~~ — **behoben:** Der Token wurde in Arena erneuert; `gh auth status` meldet wieder `✓ Logged in`, und die Commits `d9308cb…7d1a736` sind gepusht. CI-Run `34713717145` lief dadurch erstmals vollständig durch (4/4 Jobs grün).
2. **Playwright-Browser in der Sandbox:** `cdn.playwright.dev` gesperrt, apt hat kein Chromium (`Unable to locate package`). **Workaround:** `make test-ui-list` prüft die Specs (7/7 discoverbar), `make test-ui` meldet SKIP mit Grund, CI-Job `ui-browser` führt sie mit Chromium aus.
3. **Log-/Artefakt-Download von CI:** `results-receiver.actions.githubusercontent.com` und `*.blob.core.windows.net` liefern `EOF`. **Workaround:** der Job postet seine Fehler selbst als PR-Kommentar (`permissions: pull-requests: write`).
4. **Echte Modellgewichte** (Whisper/MiDaS int8): lizenzpflichtig → `offline-placeholder:`-Shim.
5. **Echter AAudio/Oboe-HAL und BLE-LC3plus-Decoder:** brauchen Gerät bzw. Plattform-Codec; Loopback-Pipes übernehmen decodierte PCM-Blöcke.
6. **Emscripten (`emcc`)** für `web/wasm/dsp_core.mjs`: nicht installierbar (`apt-get` findet es nicht). **Workaround:** ABI-Modul `dist/wasm/kaoss_dsp.wasm` wird mit `ziglang` gebaut und ist paritätsgeprüft; UI nutzt sonst den JS-Kern.
7. **Echtes DEX in der signierten APK:** kein JDK/`d8` → Stub-DEX (PLACEHOLDER-Marker in `build_signed_apk.py`).
8. **Gradle-Wrapper-Jar:** fehlt lokal (kein JDK/Netz) → `scripts/fetch_gradle_wrapper.sh`, CI stellt Gradle 8.7.

## Verbleibende TECH-DEBT

1. `.github/workflows/multiplatform-ci-cd.yml` scheitert seit jeher in 0 s mit „workflow file issue" — **repo-weit und vorbestehend** (identisch auf `arena/01a090e3-kaospad`), nicht durch diese Arbeit verursacht.
2. Zwei WASM-Bauwege (`dist/wasm/kaoss_dsp.wasm` via zig/ABI, `web/wasm/dsp_core.mjs` via emcc) — zusammenführen, sobald emcc verfügbar ist.
3. `make test` bricht, wenn gleichzeitig ein Server auf `0.0.0.0` läuft (Zero-Cloud-Gate `offline_ipc_socket_test` verlangt Loopback-Bindung) — korrektes Verhalten, aber als Hinweis dokumentieren.
4. 371 offene Checkboxen in `docs/FULL_IMPLEMENTATION_TODO.md` (siehe `docs/audit/GAP-MATRIX.csv`).
5. Watchdog-Restarts sind in der One-App **logisch** (Rolle wird neu initialisiert, `logical_restart: true`), weil alle sechs Rollen in einem Prozess laufen. Echte Prozess-Respawns liefert `engines/watchdog.py` über den `restart`-Callback — im Multi-Daemon-Modus muss er noch mit `Popen` verdrahtet werden.
6. `backups/phase2/` und `backups/phase3/` enthalten die Originale der ersetzten Dateien (Regel des Auftrags). Vor einem Release können sie aus dem Artefakt-Pfad ausgeschlossen werden.
7. `flatc` und das `flatbuffers`-Paket sind nur in der Sandbox/CI per `pip` verfügbar und werden dort **nicht** persistiert. Der Produkt-Codec (`engines/kpcm_flatbuffers.py`) ist deshalb bewusst abhängigkeitsfrei; die Referenz-Kreuzdecodierung läuft nur, wo beide Werkzeuge installiert sind (Workflow-Schritt „FlatBuffers reference toolchain").
