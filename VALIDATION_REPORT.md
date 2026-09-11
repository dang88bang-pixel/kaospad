# Bereitstellungs- und Validierungsbericht – Kaoss Pad & AI Beatbox Studio

Datum: 2026-09-09 (Update 2026-09-11)  
Branch: `arena/01a083de-kaospad` (Update: `arena/01a08ebf-kaospad`)

## Phase A – Ehrliche Beta lauffähig machen (Update 2026-09-11)

Arbeitspakete aus `docs/FULL_IMPLEMENTATION_TODO.md` §15 wurden abgearbeitet:

| # | Paket | Ergebnis |
|---|---|---|
| 2 | Android JNI-Bridge | Signatur-Parität JNI↔Kotlin in `tests/native_audio_bridge_test.py` (39 Checks) |
| 3 | Runtime-Permissions UI | `onRequestPermissionsResult` + USB-Permission-Intent-Flow + `ContextCompat.registerReceiver` |
| 4 | AudioRecord/AAudio → DSP | portabler Kern `kaoss_audio_processor.{hpp,cpp}`, `aaudio_input_engine.cpp` (Exclusive→Shared/LowLatency/Float32, xrun+disconnect), `audio_input_engine.cpp` (Fixture-Facade), AudioRecord-Fallback `AudioInputController.kt`; Host-Test `audio_input_processor_test` 19 Checks grün. Geräte-/NDK-Verifikation offen (Sandbox ohne JDK/NDK/Gerät). |
| 5 | WebAudio/WASM-Fallback | `web/wasm/dsp_core_wasm.cpp` + `scripts/build_wasm.sh` (Emscripten) + `web/src/dsp-core.js` (WASM-first, reiner JS-Spiegel, Zahlen 1:1 zu C++/Python); Transient-Events im Live-Meter. WASM-Build offen (kein emcc), JS-Spiegel getestet. |
| 6 | SCREEN_6/14/29 | SCREEN_14 (Detail-Drawer, Gain/Monitor/BT-Komp/USB-Rate/AGC/NS, Loopback-Kalibrierung), SCREEN_29 (8×8 LED-Matrix + Quad-Readouts), SCREEN_6 (PID/Health + RESTART). Neue Endpunkte `/api/daemons`, `/api/daemons/restart`, `/api/audio/calibrate`, `/api/audio/capture`. UI-Katalog-Checks im Headless-Harness: 107 Checks. |
| 7 | Release ohne Platzhalter | `scripts/verify_release_artifacts.py` (lehnt Stub-APK ohne `lib/*/libkaoss_native.so` ab), `scripts/generate_sbom.py`, `tests/release_artifact_guard_test.py` (13 Checks, Stub-APK als Negativ-Fixture), Workflow baut Android via Gradle (APK+AAB) + Publish-Job mit SHA256SUMS+SBOM+Guard. |
| 1 | Gradle-Wrapper | `scripts/verify_gradle_wrapper.py` + `scripts/fetch_gradle_wrapper.sh`; Jar bleibt offline (kein Netz/JDK), CI nutzt `gradle/actions/setup-gradle` 8.7. |

Neue/geänderte Testausgabe (`make test`):

```text
audio input processor + engine fixture verified: 19 checks
browser UI action & interaction chain verified: 107 checks (inkl. SCREEN_6/14/29)
native audio bridge contract verified: 39 checks
release artifact guard verified: 13 checks
```

Ehrliche Abgrenzung (unverändert): echte AAudio/AudioRecord-Capture, echte
USB/BLE-Pairing, WASM-Build und Geräte-Latenz brauchen Hardware bzw. NDK/Emscripten,
die in dieser Sandbox nicht verfügbar sind. Der portable DSP-Kern, die JS-Spiegel-
Parität, die Server-Endpunkte, die UI-Screens und der Release-Guard sind hier
ausführbar und getestet.

## Ergebnis

Die lokal ausführbare Offline-Suite ist jetzt zusätzlich als **eine Anwendung** bereitgestellt: `app.py` startet Web UI und alle aktuellen APIs in einem Prozess auf `127.0.0.1:8080`.

Die lokal ausführbare Offline-Suite ist bereitgestellt und erweitert um **Plug-&-Play Audio Input Adaption** für:

- USB-C Audio Interface
- internes Mikrofon
- Bluetooth/BLE Client-Mikrofon

Die Auswahl ist in der Web-Ansicht konfigurierbar, zeigt Status/Latenz/Route an und prüft bzw. listet die notwendigen Berechtigungen. Android-Manifest-Berechtigungen und Features werden per Test validiert.

## Starten als eine Anwendung

```bash
make run-app
```

Danach läuft alles über einen Prozess und eine Web-App auf:

```text
http://127.0.0.1:8080/
```

## Alternative: Multi-Port IPC Suite

```bash
make run-localhost-ipc
```

Danach lokal verfügbar:

```text
http://127.0.0.1:8080/                         Web UI
http://127.0.0.1:8080/native-bridge/ports      PortView Status
http://127.0.0.1:8080/devices/status           USB/Mic/Bluetooth Status
http://127.0.0.1:8080/devices/select?input=usb_c_audio
http://127.0.0.1:8080/devices/select?input=internal_mic
http://127.0.0.1:8080/devices/select?input=bluetooth_client
http://127.0.0.1:8080/permissions/check        Berechtigungsstatus
http://127.0.0.1:8082/mesh/default             NeuralLift Default Avatar
http://127.0.0.1:8085/rhymes?word=beton        Offline Reimhilfe
```

## Vollständige Aktions- und Interaktionskette (neu, 2026-09-09)

Die Suite besitzt jetzt eine durchgängige, zustandsbehaftete Interaktionskette
statt einzelner statischer Endpoints.

Neue Module:

| Modul | Rolle |
|---|---|
| `engines/session_engine.py` | Session-State, Aktionskatalog (19 Aktionen), Reihenfolge-Guards, Event-Log, `.cypher`-Export |
| `engines/dsp_chain.py` | deterministischer Python-Spiegel des C++-DSP-Kerns (Limiter, Transient-Splitter, 808/Snare/Hat, Kaoss Quad inkl. Looper/Vinyl/Tape-Echo, Metering) |
| `web/src/action-chain.js` | DOM-freies Browser-Modul mit derselben Kette (Reducer, Runner, Offline-Dispatcher) |
| `web/src/app.js` | alle UI-Elemente dispatchen echte Aktionen (POST) und rendern Ketten-Log/State |
| `app.py` | `POST /api/action`, 18 dedizierte POST-Routen, `/api/state`, `/api/events`, `/api/actions`, `/api/dsp/report`, `/api/chain/run`, Origin-Guard |
| `engines/localhost_ipc_suite.py` | teilt dieselbe Engine über die Ports 8080/8082/8085, UDP-Bridge 8084 fährt echte DSP-Blöcke, Rollentrennung per `403` |

Kanonische Kette (23 Schritte):

```text
boot → input.select → permission.check → permission.grant → audio.start → mic.arm
→ preset.apply → kaoss.xy ×2 → dsp.process → pad.trigger → dsp.process → pad.trigger
→ dsp.process → transport.record → loop.capture → kaoss.freeze → transcribe
→ rhyme.lookup → avatar.mode → neurallift.generate → transport.record(stop) → session.export
```

### Validierte Eigenschaften

| Eigenschaft | Nachweis |
|---|---|
| Reihenfolge-Guards | `mic.arm`, `dsp.process`, `pad.trigger`, `loop.capture`, `neurallift.generate`, `session.export` liefern `BLOCKED` inkl. `missing_milestones`/`expected_before` |
| Limiter | jeder DSP-Block `output_peak_dbfs <= -3.2 dBFS`, `headroom_db >= 0` |
| Transient-Splitter | `mouth_bass→KICK808`, `snare→SNARE_CLAP`, `hat→HAT_ROLL`, `vocal→NONE` (48 kHz und 96 kHz, 16–1024 Frames) |
| Latenzbudget | Block-Latenz `<= 1.2 ms`, Aktions-Latenz `<= 400 ms` (CI-Budget), gemessen max ≈ 8–13 ms |
| Looper/Freeze | eingefrorenes Modul liefert zwei identische Block-Checksummen; XY auf frozen-Modul wird als `held` ignoriert |
| Quantisierung | 1/16 bei 128 BPM = `117.188 ms`, Loop = `468.75 ms` = `45000` Frames @96 kHz bzw. `22500` @48 kHz |
| Determinismus | identische Kette ⇒ identischer `.cypher`-SHA-256 (zwei Server-Runs + Referenzmodell) |
| Ketten-Äquivalenz | HTTP-Kette == Referenzmodell `SessionEngine.run_script()` (gleicher Checksum) |
| UI ↔ Server Konvergenz | Client-Spiegel (`chainReducer`) == `/api/state` (Kettenlänge, Aktionen, BPM, Input, Freeze, DSP-Blöcke, Limiter, Avatar, Transport) |
| Projektionen | `/api/state`, `/api/events?since=`, `/api/logs`, `/api/dsp/report`, `/native-bridge/ports` (`chain_hits`), `/session`, `/dsp/transient` |
| Zero-Cloud | Socket-Monkeypatch: 0 Nicht-Loopback-Ziele, 2 externe Versuche blockiert; `X-Kaoss-Zero-Cloud: true` auf jeder Antwort |
| CSRF/Origin | `POST` mit fremdem `Origin` ⇒ `403`, Loopback-Origin ⇒ erlaubt |
| Backwards-Kompatibilität | alle bisherigen GET-Verträge und `tests/one_app_e2e_test.py` unverändert grün |

### Neue Testausgabe

```text
vollständige Aktions- und Interaktionskette verifiziert: 236 Checks, 23 Ketten-Schritte, max 7.847 ms, peak -3.2 dBFS
browser action & interaction chain verified: 89 checks (offline + blocked + live server)
browser UI action & interaction chain verified: 93 checks against http://127.0.0.1:8106
zero-cloud socket guard passed: 24 chain steps, 3 loopback connections, 1 resolved hosts, 2 external attempts blocked
zero-cloud localhost IPC gate passed for ports 8080-8085 (shared action chain)
web functional audio/device/rhyme contract declared // action chain parity: 19 actions, 23 chain steps, 6 engine ports
```

Der UI-Test (`tests/web_ui_interaction_chain_test.mjs`) lädt das reale
`web/src/app.js` mit einem minimalen DOM-/WebAudio-Stub gegen einen echten
One-App-Server und löst echte Benutzer-Events aus (Select-Wechsel, Klicks,
XY-Pointermove, 16 Pads, Record, Loop, Transkript, Avatar, Export,
„VOLLSTÄNDIGE KETTE AUSFÜHREN“). Damit ist die Kette **UI → HTTP → Engine → DSP →
State → UI** ohne Browser und ohne Cloud getestet.

### Ehrliche Abgrenzung

- `dsp_chain.py` ist ein deterministischer **Spiegel** des C++-Kerns für
  Server/CI/UI-State – der Echtzeit-Audiopfad bleibt C++/WebAudio.
- `transcribe` nutzt weiterhin den Offline-Text-Shim; ein echtes `whisper.tflite`
  ist offen (siehe TODO 5.1).
- `neurallift.generate` liefert ein prozedurales Offline-GLB-Fallback-Objekt,
  keine echte Bild-zu-Mesh-Inferenz.
- Die Kette läuft pro Prozess (ein State pro App-Instanz); Multi-Client-Sessions
  und Persistenz über Neustarts sind offen.

## Kaoss Quad Console & Vault

Die Ein-Anwendung enthält jetzt zusätzliche Performance-/Vault-Funktionen:

- Preset-Lader für `90s Tape`, `Acid Berlin`, `Cyber Drill`, `Lo-Fi Cypher`.
- Vier Freeze-Buttons für FX1 Looper, FX2 Vinyl, FX3 Filter, FX4 Tape Echo.
- Sample-Bänke A-D.
- `.cypher` Session Export.
- Live Log Panel.
- APIs `/api/presets`, `/api/session/export`, `/api/logs`.

## Funktionsbereite Browser-Audio-Engine

Die PWA enthält jetzt eine direkt bedienbare WebAudio Engine:

- `AUDIO STARTEN` startet den AudioContext.
- `MIC ARMEN` fordert Mikrofonberechtigung an und verbindet das Inputsignal.
- `808 TEST` erzeugt eine 808 Kick mit Pitch-Glide und Limiter.
- `SNARE TEST` erzeugt eine Noise-Snare.
- Das XY-Pad steuert Filter/Delay live.
- Der Meter zeigt Peak/dBFS.
- Browser-Audioinputs werden per `enumerateDevices()` gelistet.
- Reimhilfe läuft über Localhost API oder Offline-Fallback.

## Plug-&-Play Audio Matrix

| Eingang | Statusanzeige | Konfigurierbar | Route | Permission Gate |
|---|---:|---:|---|---|
| USB-C Audio Interface | ✅ `LOCKED` / `AVAILABLE` | ✅ | UAC2 direct monitor / `127.0.0.1:8081` | `RECORD_AUDIO`, `MODIFY_AUDIO_SETTINGS`, `usb_host` |
| Internes Mikrofon | ✅ `LOCKED` / `AVAILABLE` | ✅ | AudioRecord / Default Input | `RECORD_AUDIO` |
| Bluetooth/BLE Mic | ✅ `LOCKED` / `PAIRABLE` | ✅ | BLE Jitter Buffer / +42ms Compensation | `RECORD_AUDIO`, `MODIFY_AUDIO_SETTINGS`, `BLUETOOTH_CONNECT`, `BLUETOOTH_SCAN` |

## Android Berechtigungen / Features

Geprüft und im Manifest bereitgestellt:

```text
android.permission.RECORD_AUDIO
android.permission.MODIFY_AUDIO_SETTINGS
android.permission.BLUETOOTH_CONNECT
android.permission.BLUETOOTH_SCAN
android.permission.BLUETOOTH / BLUETOOTH_ADMIN bis SDK 30
android.permission.ACCESS_FINE_LOCATION bis SDK 30 für Legacy BLE Scan
android.hardware.audio.low_latency
android.hardware.usb.host
android.hardware.bluetooth_le
```

## Ausgeführte Tests

```bash
make test
./scripts/package_web_pwa.sh
python3 engines/device_matrix.py
```

## Testausgabe

```text
AudioFlinger direct-pipe simulator: route=127.0.0.1:8081 roundtrip_ms=1.2
Limiter peak=-3.2 dBFS threshold=-3.2 dBFS
Transient kind=1 freq=52 latency_ms=1
zero-cloud localhost IPC gate passed for ports 8080-8085 (shared action chain)
multi-avatar sync benchmark passed
android USB/mic/bluetooth permissions and features declared
web functional audio/device/rhyme contract declared // action chain parity: 19 actions, 23 chain steps, 6 engine ports
kaoss one-app e2e contract passed
vollständige Aktions- und Interaktionskette verifiziert: 236 Checks, 23 Ketten-Schritte, max 7.847 ms, peak -3.2 dBFS
browser action & interaction chain verified: 89 checks (offline + blocked + live server)
browser UI action & interaction chain verified: 93 checks against http://127.0.0.1:8106
zero-cloud socket guard passed: 24 chain steps, 3 loopback connections, 1 resolved hosts, 2 external attempts blocked
```

## Aktueller Vollständigkeitsstatus

| Feature | Bereitgestellt | Ausführbar | Hinweis |
|---|---:|---:|---|
| Plug-&-Play UI für USB/Mic/Bluetooth | ✅ | ✅ | Web-Ansicht fertig |
| Device Status API | ✅ | ✅ | `/devices/status` |
| Device Auswahl API | ✅ | ✅ | `/devices/select?input=...` |
| Permission Check API | ✅ | ✅ | `/permissions/check` |
| Android Permission Manifest | ✅ | ✅ geprüft | `tests/permission_manifest_test.py` |
| USB-C Audio Route | ✅ | ✅ Shim | echter UAC2/AAudio Hook später ersetzbar |
| Internes Mic Route | ✅ | ✅ Shim | Runtime-Prompt in Native Shell/Browser |
| Bluetooth Client Route | ✅ | ✅ Shim | echte Pairing-API später ersetzbar |
| Native Bridge PortView | ✅ | ✅ | Live API oder Browser-Safe-Fallback |
| WebAudio Performance Engine | ✅ | ✅ | Browser-funktional mit Mic Prompt und Synth-Tests |
| Kaoss One App `app.py` | ✅ | ✅ | Eine Anwendung mit UI + APIs + Tests |
| Localhost IPC `:8080–:8085` | ✅ | ✅ | Zero-Cloud, loopback-only |
| Session-State-Engine | ✅ | ✅ | `engines/session_engine.py`, 19 Aktionen |
| Aktions- & Interaktionskette | ✅ | ✅ | POST `/api/action`, `/api/chain/run`, UI-Panel |
| Reihenfolge-Guards (`BLOCKED`) | ✅ | ✅ | Milestone-Modell pro Aktion |
| Python-DSP-Kette | ✅ | ✅ Spiegel | `engines/dsp_chain.py` (C++-Verträge 1:1) |
| Looper/Freeze + BPM-Quantisierung | ✅ | ✅ | `loop.capture`, 1/16 bei Preset-BPM |
| Ketten-Export `.cypher` | ✅ | ✅ | inkl. Aktionskette + SHA-256 |
| Ketten-Tests (HTTP/Node/UI/Zero-Cloud) | ✅ | ✅ | 236 + 89 + 93 Checks |

## Artefakte

```text
dist/KaossBeatboxStudio-WebAssembly-Offline.zip
dist/KaossBeatboxStudio-v5.0.0-x86_64.AppImage
dist/KaossBeatboxStudio-v5.0.0-Universal.dmg
dist/offline-models/
dist/offline-rhymes.sqlite3
dist/device-matrix.json
```

## Wichtige Abgrenzung

In dieser Sandbox sind keine echten Android-/Windows-/macOS-Hardwaregeräte angeschlossen. Deshalb sind USB/Bluetooth/AudioFlinger/ASIO/CoreAudio als ausführbare Offline-Shims mit stabilen JSON-/IPC-Verträgen umgesetzt. Die Berechtigungen, Konfiguration, Statusanzeigen und Tests sind fertig eingebunden; echte Treiber-Hardware kann später hinter denselben Schnittstellen aktiviert werden.
