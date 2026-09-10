# Vollständige Teileprüfung — alle Parts der Anwendung

Stand: 2026-09-10 · Branch `arena/01a085c8-kaospad` @ `4fa93ab`  
Geprüft: Quelltext Zeile für Zeile (kein Geräte-Sideload).  
Codeumfang ~64 Quelldateien: Python ~3 000 Z., Web ~1 470 Z., Android ~500 Z., Tests ~2 380 Z., Scripts ~830 Z., Desktop ~140 Z.

Legende: **LIVE** · **SHIM** · **UI-ONLY** · **CLOUD** · **SCAFFOLD** · **OFFEN**

---

## A. One-App-Server — `app.py` (588 Zeilen) — LIVE

Threading-HTTP auf `127.0.0.1` (Sandbox: `0.0.0.0` explizit). Bind anderer Hosts → Exit.

**GET (Lesen):** `/health`, `/api/runtime`, `/api/status`, `/api/state`, `/api/actions`, `/api/events`, `/api/events/stream` (SSE ein Chunk, kein Dauerloop), `/api/session/latest`, `/native-bridge/ports`, `/session`, `/devices/status|usb|ble|select`, `/permissions/check`, `/audio/oboe`, `/models/whisper|midas`, `/mesh/default`, `/avatar/frame`, `/dsp/transient|report`, `/api/presets`, `/api/session/export`, `/api/logs`, `/transcribe`, `/rhymes`, plus statische `web/`.

**POST (Kette):** `/api/action`, `/api/chain/run`, `/api/session/import`, plus 18 Alias-Routen (`input.select` … `chain.reset`). CSRF: fremder Origin → **403**. Body JSON oder form, max 4 MB.

**Nicht:** WebSocket, echter PCM-Upload-Stream, Daemon-Restart, PID-Watchdog.

---

## B. Session-Engine — `engines/session_engine.py` (891 Z.) — LIVE

Version `5.0.0-offline-one-app`. Thread-Lock, Event-Log, Milestones, `BLOCKED` bei verletzter `requires`-Kette.

### 19 Aktionen (vollständig)

| # | Aktion | Engine/Port | requires | Handler |
|---|---|---|---|---|
| 1 | `boot` | orchestrator 8080 | — | Reset |
| 2 | `input.select` | 8080 | — | usb/mic/bt |
| 3 | `permission.check` | 8080 | input.selected | Matrix |
| 4 | `permission.grant` | 8080 | permission.checked | Runtime-Keys |
| 5 | `audio.start` | audio 8081 | input+grant | 96 kHz/128, Oboe-JSON |
| 6 | `mic.arm` | 8081 | audio.started | Monitor -6 dB |
| 7 | `preset.apply` | dsp 8084 | audio.started | 4 Themes |
| 8 | `kaoss.xy` | 8084 | audio.started | Modul 0–3 |
| 9 | `kaoss.freeze` | 8084 | audio.started | Freeze-Bit |
| 10 | `dsp.process` | 8084 | mic.armed | Limiter/Transient |
| 11 | `pad.trigger` | 8084 | mic.armed | Banken A–D |
| 12 | `transport.record` | 8080 | dsp.processed | Rec on/off |
| 13 | `loop.capture` | 8084 | recording | 1/16 Quant |
| 14 | `transcribe` | whisper 8085 | mic.armed | Shim + PCM-Features |
| 15 | `rhyme.lookup` | 8085 | permission.checked | SQLite |
| 16 | `avatar.mode` | avatar 8083 | audio.started | 5 Modi |
| 17 | `neurallift.generate` | 8082 | avatar.mode | GLB Fallback |
| 18 | `session.export` | 8080 | mic.armed | `.cypher` + SHA-256 |
| 19 | `chain.reset` | 8080 | — | Wipe |

**FULL_CHAIN_SCRIPT:** 23 Schritte (inkl. mehrfach XY/Freeze/Pads). Persistenz `dist/sessions/*.cypher.json`, Replay `replay_cypher`.

**Presets:** `90s_tape` 92.4 · `acid_berlin` 128 · `cyber_drill` 142 · `lofi_cypher` 84.  
**Bänke:** A Kick/808 · B Snare · C Hat · D Vocal FX, je 4 Slots.

---

## C. DSP — `engines/dsp_chain.py` (360 Z.) + C++ — LIVE (deterministisch)

Python: Soft-Knee Brickwall **-3.2 dBFS**, Peak/RMS, Direct-Pipe-Formel, Mouth-Transient (Mean-Abs/Delta, **kein FFT**), `synthesize_808/snare/hat`, `KaossQuadChain` (4 Module: Looper, Vinyl-Wow, Filter, Tape-Echo-Term), `process_block`, Checksum, `quantize_step_ms`.

C++ Spiegel (`kaoss_dsp.hpp`, `audio_flinger_hook.cpp`, `dsp_transient_splitter.cpp`, `kaoss_quad_engine.cpp`): gleiche Verträge, Tests `audio_latency_e2e_test` / `brickwall_limiter_test` / `transient_splitter_test`.

**Nicht:** Oversampling-True-Peak, Lookahead, FFTW, echte Loop-Wiedergabe aus RAM-Audio, SIMD.

---

## D. Geräte / HAL

| Part | Datei | Zeilen | Zustand |
|---|---|---|---|
| Device-Matrix | `device_matrix.py` | 120 | SHIM IDs + LIVE Probe-Hook |
| ALSA/`/dev/snd` | `local_audio_probe.py` | 50 | LIVE Scan, kein Stream |
| USB UAC2 | `usb_uac2.py` + `UsbUac2Client.kt` | 64+23 | sysfs VID/PID; Android PendingIntent **ohne** Audio-ISO |
| BLE | `ble_codecs.py` + `BleCodecClient.kt` | 31+14 | Matrix LC3plus/LC3/SBC/AAC/aptX; **kein** GATT |
| Oboe | `oboe_exclusive.py` + `oboe_exclusive_stream.cpp` | 52+18 | JSON Exclusive/LowLatency/Float32; `#ifdef HAVE_OBOE` leer |
| AudioFlinger | `audio_flinger_hook.cpp` | 54 | roundtrip Formel 1.2 ms |

IPC `localhost_ipc_suite.py` (401 Z.): sechs Ports Health/JSON — SHIM, kein Float32-mmap.

---

## E. AI / Avatar

| Part | Datei | Zustand |
|---|---|---|
| Reime | `rhyme_matrix.py` 62 | LIVE kleine SQLite, **nicht** 85k |
| Transcribe | `transcriber.py` 41 | Feature-Heuristik auf PCM/`text` |
| TFLite | `tflite_runtime.py` 55 | Stub `TFL3` Bytes, kein Interpreter |
| NeuralLift HTTP | `engine_service.py` 50 | Fallback-JSON |
| GLB | `glb.py` 77 | **echte** Mini-glTF-Datei nach `dist/avatars/` |
| MiDaS | `midas.py` 54 | int8 HxW Buffer, kein Netz |
| Pose | `mopac_dance_learner/pose.py` 39 | 33 Landmarks synthetisch |
| Weights | `download_weights.py` 44 | schreibt Stub-Files |

`neurallift.generate` setzt `fallback=True`.

---

## F. Web / PWA — LIVE UI + WebAudio

`index.html` 189 Z. — **eine** Seite, Sektionen:

1. Hero  
2. Runtime Port Auto  
3. Native Bridge PortView (6 Daemon-Karten)  
4. I/O Matrix USB/Mic/BT + Permissions  
5. Kaoss Quad Console (4 Freeze, Presets, `.cypher`)  
6. Live Engine (Audio/Mic/808/Snare/Meter/Reime)  
7. Aktionskette (strict, 16 Pads, Record/Loop, Avatar, Transcribe, Log)  
8. XY-Pad  
9. Daemon-Zeilen 127.0.0.1:8080–8085  

`app.js` 699 Z.: Runtime-fetch mit **catch-Fallback**, `dispatchAction` → `/api/action`, Offline-Reducer, WebAudio-Buttons, XY→`kaoss.xy`.  
`audio-engine.js` 180 Z.: AudioContext 48 kHz, Filter/Delay/Limiter-Kurve, getUserMedia, 808/Snare-Synths, Meter RAF. **Kein** inneres catch.  
`action-chain.js` 398 Z.: Katalog/Reducer/offlineDispatcher paritätisch zum Server.  
`styles.css`, `manifest.webmanifest`, `sw.js` 4 Z. Cache-Scaffold.

**Fehlende Screens (Katalog):** Tanz-Anlern Kamera, 3D-Party, Cypher-HUD, NeuralLift-Lab, Endless Reel, Desktop-3-Panel, 8×8 LED, YouTube-Detect.

---

## G. Android Native

| Datei | Inhalt | Fertig? |
|---|---|---|
| `AndroidManifest.xml` | min 26 / target 35, Mic/BT/USB/Internet, NSC, MAIN/LAUNCHER | Permissions LIVE |
| `MainActivity.kt` 52 | WebView `file:///android_asset/www/`, JS, `KaossNativeBridge`, Runtime Mic/BT | Shell LIVE |
| `KaossJsBridge.kt` | `portStatus`, `dspPipe` try/catch | JSON-SHIM |
| `KaossNative.kt` | `loadLibrary("kaoss_native")` swallow UnsatisfiedLinkError | CLOUD-APK hat `.so` |
| `kaoss_jni.cpp` 86 | pipeStatus, limiterPeak, detectTransient, oboeExclusive | LIVE Math |
| Gradle `app/build.gradle.kts` | AGP 8.5, NDK 26, CI-Signing via Env | CLOUD |
| `gradlew` lokal | schreibt Platzhalter-APK | SCAFFOLD |

Foreground-Service: **OFFEN**. Device-Matrix JNI: **OFFEN**.

---

## H. Desktop — SCAFFOLD

`desktop/src/*.rs` und `src-tauri` je ~65+16+11: Audio-Host-Stubs, Daemon-Manager-Stubs.  
`build_appimage.sh` 10 Z., `create_universal_dmg.sh` 5 Z., `build_windows_installer.ps1` 3 Z., `setup_asio_sdk.ps1` 3 Z. — Echo-Platzhalter. **Keine** ALSA/CoreAudio/WASAPI-Implementierung.

---

## I. Tests (16 Dateien, ~2381 Z.)

| Test | Checks / Rolle |
|---|---|
| `action_interaction_chain_test.py` | 236 HTTP |
| `action_chain_ui_test.mjs` | 89 offline+live |
| `web_ui_interaction_chain_test.mjs` | 93 DOM-Stub |
| `web_functional_contract_test.py` | Katalog-Parität 19/23/6 |
| `zero_cloud_socket_guard_test.py` | externe Sockets BLOCK |
| `one_app_e2e_test.py` | One-App |
| `offline_ipc_socket_test.py` | Ports 8080–8085 |
| `client_hal_orchestrator_test.py` | Oboe/USB/BLE/Whisper/MiDaS JSON |
| `full_chain_attributes_test.py` | Attribute |
| `session_persist_replay_test.py` | Store |
| `permission_manifest_test.py` | Manifest |
| `signed_apk_test.py` | Offline-ZIP v1+v2 |
| C++ 3 Tests | Latenz/Limiter/Transient |
| `multi_avatar_sync_test.js` | synthetisches FPS |

**Nicht:** Playwright, Hardware-Loopback, USB-Hotplug-IT, Soak.

---

## J. Release / CI / Scripts

| Artefakt | Status |
|---|---|
| Offline APK Universal-Signed ~113 KB | v1+v2 Archiv, **kein** ART-Launch |
| Cloud APK GHA [34466007825](https://github.com/dang88bang-pixel/kaospad/actions/runs/34466007825) | **assembleRelease SUCCESS**, Artifact |
| PWA ZIP | `releases/…-PWA.zip` / `package_web_pwa.sh` |
| AAB / AppImage / DMG / MSI | OFFEN / Scaffold |
| `build_signed_apk.py` 747 | OpenSSL Signer, Stub-DEX |
| `android-signed-apk.yml` | Temurin17 SDK35 NDK26 Gradle 8.7 |
| Multiplatform-CI | Android-Job nutzte Stub-`gradlew`; Cloud-Workflow ersetzt das für APK |
| JDK lokal | BLOCKED TLS; PyPI JRE 25 ohne javac |

---

## K. Fehlerbehandlung (quer)

- Server: Origin-403, unknown action 400, ungültige Inputs ERROR, Chain BLOCKED.  
- UI: fetch-catch → Offline-Endpunkte; Chain-Log.  
- Native: UnsatisfiedLinkError, `dspPipe` catch JSON.  
- Audio JS: throw ohne lokalen catch (UI wrappen).  
- SSE: ein Event, kein Keep-Alive-Loop.

---

## L. Abhängigkeiten

Laufzeit One-App: **nur Python 3 Stdlib** + optionales sysfs.  
Android Cloud: AndroidX core-ktx, NDK log, CMake. **Keine** Oboe-AAR.  
ML: keine echten `.tflite`.  
Netz: Zero-Cloud by design.

---

## M. Fazit je Part (eine Zeile)

| Part | Urteil |
|---|---|
| HTTP One-App | vollständig für Offline-Beta |
| 19-Aktionskette | vollständig, Guards LIVE |
| DSP Math | LIVE, nicht Studio-FX-Vollsatz |
| Web UI | eine lange Studio-Seite LIVE, Katalog-Screens fehlen |
| WebAudio | LIVE im Browser |
| Android Shell | LIVE im Cloud-APK, Offline-APK tot |
| JNI DSP | LIVE Formeln |
| Oboe/USB/BLE Hardware | Vertrag SHIM |
| Whisper/MiDaS/MoPac | SHIM + Stub-Gewichte |
| IPC-Daemons | Health SHIM |
| Desktop | Scaffold |
| Tests | stark auf Kette/Zero-Cloud, schwach Hardware |
| Store/DoD | nicht fertig |

**Gesamt:** Die **Software-Kette UI → POST → Engine → DSP → State → Export** ist in voller Länge implementiert und getestet. Die **Geräte-, Modell- und Multi-OS-Produktkette** ist in voller Länge spezifiziert, aber nur als HAL/Shim/Cloud-Build vorhanden.

Nachtrag 2026-09-10: `.cypher` Replay-Button in der UI; `tests/functional_execution_audit_test.py` führt alle 19 Aktionen mit State-Side-Effects aus (40 Checks, grün). Ähnliche Projekte: `releases/AEHNLICHE_PROJEKTE.md`.
