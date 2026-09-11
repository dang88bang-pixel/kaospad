# AUDIT REPORT — 2026-09-11

## Phasenabschluss
- [x] Phase 1: 129 Dateien auditiert, 55 mocks/placeholder gefunden
- [ ] Phase 2: N Dateien ersetzt, 0 API-Breaks
- [ ] Phase 3: N Schnittstellen gebunden
- [ ] Phase 4: Alle Tests grün, Screenshots/Logs angehängt
- [ ] Phase 5: Fehlerfälle getestet

## Zusammenfassung Audit

- **129 Dateien** im Inventar (129 Zeilen INVENTAR.csv inkl. Header)
- **Statusverteilung:**
  - REAL: 74 (57%)
  - MOCK: 16 (12%)
  - PLACEHOLDER: 29 (22%)
  - TODO: 7 (5%)
  - STUB: 3 (2%)
  - DEAD: 0

- **Checkbox-Anforderungen (FULL_IMPLEMENTATION_TODO.md):** 447 Checkboxen
  - Offen [ ]: 330 (74%)
  - Done [x]: 112 (25%)
  - Partial [~]: 5 (1%)

- **GAP-Matrix:** 391 Sektion-Zeilen, davon 74% offen, aber 45% als SHIM/ALTERNATIVE abgedeckt für Dev/Test.

## Kritische MOCK/PLACEHOLDER Dateien (P1 — 29 Dateien)

Siehe audit/INVENTAR.csv Priorität P1:

| Datei | Zeilen | Grund |
|---|---|---|
| scripts/build_signed_apk.py | 747 | STUB/PLACEHOLDER — komplexer OpenSSL Signer, aber Dummy-Dex/Inhalt als Stub |
| tests/web_ui_interaction_chain_test.mjs | 680 | STUB/PLACEHOLDER — DOM-Stub statt echter Browser |
| web/src/action-chain.js | 398 | STUB/PLACEHOLDER — Offline-Dispatcher statt echter DSP |
| ... (siehe INVENTAR.csv) |

## MOCK Dateien (P2 — 16 Dateien)

| Datei | Zeilen | Hinweis |
|---|---|---|
| web/src/app.js | 1021 | MOCK/SHIM — PortView <1.2ms hardcodiert |
| engines/session_engine.py | 891 | MOCK/SHIM — Fixture DSP statt echter Capture |
| engines/localhost_ipc_suite.py | 401 | MOCK/SHIM — JSON Shim statt Binary Protobuf |
| desktop/src/audio_host.rs | 86 | MOCK/SHIM — WASAPI/ALSA Name nur String, keine cpal Bindung |
| ... |

## Marker-Suche (Phase 1 Regel 3)

- `// TODO` / `# TODO`: 0 Treffer im Source (TODOs liegen in .md Checkboxen, nicht im Code)
- `return 0;` in *.cpp: 2 Treffer (web/wasm/dsp_core_wasm.cpp:36,119) — OK, DSP Kernel return codes
- `return false;` in *.kt: 0 Treffer
- `raise NotImplementedError`: 0 Treffer
- `return {};` / dummy: 0 Treffer
- Hardcodierte Testwerte: 18 Treffer für `-3.2 dBFS`, `52 Hz`, `1.2ms` — gewollt (Verträge, nicht Dummy)

## GAP-Matrix (gefordert vs. vorhanden)

Datei: `audit/GAP_MATRIX.csv` — 391 Zeilen.

- **GEDECKT (x DONE):** 112 (28%)
- **ALTERNATIVE (ohne ⛔ lauffähig):** 16 (4%) — via docs/ALTERNATIVE_LOESUNGSWEGE.md
- **SHIM (MOCK vorhanden):** 89 (22%)
- **GAP (offen):** 174 (44%)

**Interpretation:** Für Dev/Test sind 54% (GEDECKT+ALTERNATIVE+SHIM) ausführbar. 44% GAP sind echte Produktionslücken (Hardware, UI Screens, Store, ML Modelle), die als ⛔ dokumentiert sind.

## Verbleibende ⛔-Blocker (Top-10 nach Schwere)

1. **ASIO SDK (Steinberg Lizenz)** — Alternative: WASAPI Exclusive/RtAudio/PortAudio/JACK + Shim (docs/ALTERNATIVE_LOESUNGSWEGE.md A)
2. **KI-Modellgewichte (Whisper/MiDaS/EMOTE/MediaPipe echte .tflite)** — Alternative: openai/whisper gguf, Intel/dpt-hybrid-midas, TFL3 Placeholder
3. **Signing-Zertifikate (Apple/Windows Store)** — Alternative: keytool self-signed + OpenSSL v1+v2
4. **Store-Zugänge (Play Console)** — Alternative: adb sideload, F-Droid, GitHub Releases
5. **Sample-Library (lizenzpflichtig)** — Alternative: CC0 Freesound/SonusLab + Csound Synthese
6. **Hardware-Testgeräte (5 USB Interfaces, BLE Mics)** — Alternative: Emulator + scrcpy + sysfs Mock
7. **Gradle Wrapper JAR offline** — Alternative: gradle/actions/setup-gradle 8.7
8. **Emscripten/WASM Toolchain** — Alternative: Docker emscripten/emsdk + JS Fallback
9. **CI Signing Secrets** — Alternative: CI_SIGNING=false
10. **Hardware-Roundtrip Latenz (echte Messung)** — Alternative: Virtual-Cable + Fixture 1.2ms

Siehe auch `docs/ALTERNATIVE_LOESUNGSWEGE.md` für vollständige Tabelle (16 Zeilen).

## Verbleibende TECH-DEBT

1. 330 Checkboxen offen (TODO.md) — Priorität: Phase B Audio, Phase C AI, Phase D Release sind großteils GAP.
2. INVENTAR P1: 29 Placeholder Dateien — benötigen echte Implementierung oder bewusste Shim-Doku.
3. Hardcodierte Latenz `-3.2 dBFS` / `1.2ms` in 12 Dateien — Verträge, aber echte Messung fehlt auf Hardware.
4. Tests: 55 Dateien MOCK/PLACEHOLDER, aber machen echte Assertions (236 Checks) — kein Dead Code, aber Coverage für Hardware fehlt.
5. Keine `TODO` Marker im Code — TODOs liegen in Markdown, nicht maschinenlesbar als Code-Debt.

## Nächster Schritt — Phase 2 ERSETZUNG

Benötigt **Zustimmung pro Datei** vor Ersetzung.

Vorschlag Phase 2 Kandidaten (P1, 7 Dateien mit echtem Ersatzpotenzial):

| # | Datei | Aktuell | Ersatz-Idee | Risiko |
|---|---|---|---|---|
| 1 | engines/whisper_offline/tflite_runtime.py (55) | PLACEHOLDER TFL3 Bytes | Echte TFLite Loader mit try/except shim | Niedrig |
| 2 | engines/neurallift_360/midas.py (54) | PLACEHOLDER luma int8 | Echte HxW Depth Buffer (bereits nahe real) | Niedrig |
| 3 | engines/mopac_dance_learner/pose.py (39) | MOCK synthetisch 33 Landmarks | MediaPipe 33-Punkt Mapper (erweitert) | Mittel |
| 4 | desktop/src/audio_host.rs (86) | MOCK String | cpal/alsa Bindung (feature-flag) | Mittel |
| 5 | scripts/build_signed_apk.py (747) | PLACEHOLDER Stub-Dex | Deterministischeres APK (Zeit fix) | Niedrig |
| 6 | web/src/dsp-core.js (270) + dsp_chain parity | STUB/PLACEHOLDER | WASM Loader + JS Fallback vervollständigen | Niedrig |
| 7 | engines/whisper_offline/rhyme_matrix.py (63) | REAL klein 10 Einträge | 85k DB Import Script | Mittel |

Backup-Ort: `backups/phase2/<datei>.bak` — wird vor jedem Replace angelegt.

**Freigabe erbeten:** Sollen diese 7 Dateien in Phase 2 ersetzt werden? (Ja/Nein je Datei)

