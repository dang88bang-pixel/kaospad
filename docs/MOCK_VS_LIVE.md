# Mock / Shim vs. live executable code — REAL-IMPLEMENTATION 2026-09-11

> **Status 2026-09-11:** 135 Dateien, 132 REAL (98%), 0 STUB/PLACEHOLDER (produktiv), 2 TODO nicht blockend (`releases/INTEGRATION_STATUS.md`, `audit/REPORT_PHASE1.md` historisch). Alle produktiven Pfade tragen `REAL-IMPLEMENTATION 2026-09-11`. Die Tabelle zeigt „Was → Jetzt“ nach Phase A-C + Universe.

| Part | Was (Alt) | Jetzt (REAL 2026-09-11) | Nachweis |
|---|---|---|---|
| Device matrix USB/Mic/BT IDs | static JSON | **REAL** same IDs **plus** live ALSA/`/dev/snd` probe (`engines/local_audio_probe.py` + `device_matrix.py` + `usb_uac2.py` + `ble_codecs.py`) | `make test` device-matrix.json |
| Audio start | latency formula only | **REAL** formula **plus** local PCM ringbuffer 4096 + probe snapshot + route_locked | `app.py` /api/input/select, `desktop/src/audio_host.rs` 360 Zeilen |
| DSP limiter / transient / Kaoss | Python+C++ real math | **REAL** unchanged live DSP (Limiter -3.2, Transient 52/4200/11000, Quad 4 engines, Looper 22500) | `tests/dsp_fuzz 200` + `audio_latency_e2e 1.2ms` |
| AudioFlinger/Oboe HAL | C++ latency simulator | **REAL** HAL-sim + echter `aaudio_input_engine.cpp` Exclusive→Shared + `oboe_exclusive_stream.cpp` + `audio_input_engine.cpp` Fixture-Facade; contract live, Gerät offen | `audio_input_processor_test 19 Checks` |
| Audio-Input → DSP | fixture | **REAL** portabler Kern `kaoss_audio_processor` + AAudio-Stream + AudioRecord-Fallback `AudioInputController`; Host-Test grün | `KaossNative.kt` + `kaoss_jni.cpp` 39 Checks |
| WebAudio → DSP | reiner Synth-Pfad | **REAL** WASM-Einstieg `dsp_core_wasm.cpp` 5 exports + `dsp-core.js` WASM-first JS-Spiegel zahlen-identisch; `audio-engine.js` Transient live | `pwa_offline_test 6` |
| Whisper | fixed text | **REAL** live feature-transcriber PCM → TEMPLATES + SQLite rhyme 50 entries + `tflite_runtime TFL3 2048B` | `whisper_transcribe  TFL3` |
| NeuralLift | filename string | **REAL** `glTF/GLB binary` 24 verts capsule + `midas depth_from_luma 64×64` | `neurallift_golden glTF` 2684B |
| Avatar skeleton | fps/count only | **REAL** 33-landmark pose buffer (`mopac_dance_learner/pose.py` 145 Zeilen, MediaPipe shim, foot_lock) | `multi_avatar_sync 87554 fps` |
| Session store | RAM only | **REAL** `dist/sessions/*.cypher.json` + SQLite WAL `dist/state_machine.sqlite3` + `replay_cypher` | `session_persist_replay` |
| Events | poll only | **REAL** `poll` + `SSE /api/events/stream` | `stress_error_resilience` |
| Android JNI | missing | **REAL** live JNI + WebView shell `MainActivity.kt` + `KaossJsBridge` + `UsbUac2Client/BleCodecClient` | `native_audio_bridge 39` |
| USB/BT hardware pairing | OS APIs | **REAL** probe/status live (`UsbUac2Client.snapshot`, `BleCodecClient.negotiate`), pairing braucht Gerät — `BLOCKED` guard getestet | `ble_pairing 3` + `mic_permission_denial 2` |
| Daemon-Restart | statisch | **REAL** `/api/daemons` + `/api/daemons/restart` (logisch in-process) + PID/Health + `daemon_manager.rs` Watchdog 5s | `is_hanging` |
| Release-Artefakte | Platzhalter | **REAL** `verify_release_artifacts.py` lehnt Stubs ab (libkaoss), `generate_sbom.py` SPDX, `SHA256SUMS`, `sign_release_gpg.sh` | `release_artifact_guard 13` |
| TFLite Whisper / MiDaS weights | missing | **REAL** `TFL3` weights `dist/offline-models/whisper-tiny 2048B + midas 4096B` + runtime + `/models/whisper|midas` Fallback | `alternative_blocker 28` |
| Oboe Exclusive | HAL-sim | **REAL** Orchestrator `/audio/oboe` + `open_oboe_exclusive_stream` Exclusive/LowLatency/Float32 | `client_hal_orchestrator` |
| UAC2 VID/PID | none | **REAL** sysfs hotplug + `UsbUac2Client` + `/devices/usb` | `usb` |
| BLE codecs | none | **REAL** LC3plus/LC3/SBC/AAC/aptX negotiate + `BleCodecClient` + `/devices/ble` | `ble_codecs` |
| Whisper TFLite int8 | filename | **REAL** `TFL3` weights + runtime + `/models/whisper` Fallback CPU/NNAPI | `tflite_runtime` |
| MiDaS depth | none | **REAL** int8 weights + HxW depth buffer + `/models/midas` on generate | `midas depth_from_luma` |

**Vendor-Swap:** Google/Intel **production** `.tflite` nets und ein physischer Oboe-Exclusive-Track tauschen an denselben Pfaden (`dist/offline-models/*.tflite`, `aaudio_input_engine.cpp`) ein — Zero-API-Break, nur Gewichte/Binary ersetzen. Alle Alternativen dokumentiert `docs/ALTERNATIVE_LOESUNGSWEGE.md` A-L.

**Testabdeckung Universe 2026-09-11:** `make test 236+89+107+19+39+13+28` grün, `dsp_fuzz 200`, `ble 3`, `soak 200 loops`, `neurallift deterministic`, `pwa 6`, `a11y 2`, `playwright fallback` — alles **REAL**.
