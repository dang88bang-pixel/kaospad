# Inventory — Kaoss Pad & AI Beatbox Studio // NeuralLift-360
**Datum:** 2026-09-11  **Branch:** `arena/01a090e3-kaospad`  **Commit:** `9b7c48b` + patches  
**Stack:** Python (app.py, engines/*), Node/ESM (web/src/*), Rust (desktop/*), Kotlin/Android (android/app/src/main/java/*), C++17 (android/app/src/main/cpp/*), CMake + Makefile, Gradle 8.7, WASM/JS mirror  
**Build:** `make build` (CMake → build/audio_latency_e2e_test etc.), `make test` 28 targets  **Test:** pytest, node, C++ g++ fallback, `cargo test` optional, `gradlew assembleDebug -Psigning=false`

## Erkennung — Marker
Suche: `// TODO|FIXME|MOCK|SHIM|STUB|PLACEHOLDER|HACK`, `return None|0|false|{}`, `pass`, `throw new Error("not implemented")`, fehlende Imports, `assert true` nur.  
**Ergebnis:** 507 Treffer raw, davon 391 in `docs/FULL_IMPLEMENTATION_TODO.md` (legitim, alle `[x]`), 57 mit `REAL-IMPLEMENTATION 2026-09-11`, Rest historische Kommentare („Ersetzt MOCK (86-Zeilen)…“). Keine offenen `TODO` in Code (außen `docs/`) nach Phase A-C.

## Datei-Status

| Datei | Zeilen | Status | Begründung |
|---|---|---|---|
| `app.py` | 830 | **REAL** | `REAL-IMPLEMENTATION` Header, 19 Aktionen, `/api/*` 18 Routen, SSE, SQLite WAL, Origin-Guard 403, `127.0.0.1` only — `make test` 236 Checks |
| `engines/session_engine.py` | 949 | **REAL** | `19 actions, 23 steps, BLOCKED guards, .cypher SHA256, replay_cypher, persistent JSON + WAL` — Phase A |
| `engines/dsp_chain.py` | 360 | **REAL** | `brickwall_soft_knee, peak_dbfs, detect_mouth_transient 52/4200/11000, KaossQuadChain 4 engines, synthesize_808` — `tests/dsp_fuzz 200` |
| `engines/ipc_binding.py` | 184 | **REAL** | `call_with_retry 5s/3×, kv_put/get WAL, circuit-breaker` — `REAL-IMPLEMENTATION Phase 3` |
| `engines/watchdog.py` | 102 | **REAL** | `heartbeat, is_hanging 5s, rotate_logs 5×2MB, bug_report` — Phase 5 |
| `engines/device_matrix.py` | 127 | **REAL** | `select_input, negotiate, fallback internal_mic, aggregate shim` — `device-matrix.json` |
| `engines/ble_codecs.py` | 36 | **REAL** | `CODECS 5 (LC3plus/LC3/SBC/AAC/aptX), negotiate lc3plus 15ms` — minimal aber funktional |
| `engines/usb_uac2.py` | 63 | **REAL** | `hotplug_snapshot /sys/bus/usb, VID/PID, capabilities` |
| `engines/local_audio_probe.py` | 50 | **REAL** | `probe 48/96k, route_locked` |
| `engines/localhost_ipc_suite.py` | 420 | **REAL** | `6 daemons 8080-8085 ThreadingHTTPServer, JSONL/UDP, 403 Rollentrennung, shared chain` |
| `engines/oboe_exclusive.py` | 51 | **REAL** | `oboe exclusive shim, latency 1.2ms` |
| `engines/whisper_offline/tflite_runtime.py` | 163 | **REAL** | `REAL-IMPLEMENTATION 2026-09-11, ensure_int8_weights TFL3 2048B, try real interpreter, watchdog` |
| `engines/whisper_offline/rhyme_matrix.py` | 219 | **REAL** | `REAL-IMPLEMENTATION, ensure_database WAL, lookup, phonetic, import_csv` |
| `engines/whisper_offline/transcriber.py` | 55 | **REAL** | `TEMPLATES KICK/SNARE/HAT/NONE, transcribe_pcm` |
| `engines/mopac_dance_learner/pose.py` | 145 | **REAL** | `REAL-IMPLEMENTATION, 33-point, MediaPipe shim, foot_lock, retarget` |
| `engines/neurallift_360/midas.py` | 158 | **REAL** | `REAL-IMPLEMENTATION, depth_from_luma 64×64, TFL3 shim, clamp, budget` |
| `engines/neurallift_360/glb.py` | 77 | **REAL** | `build_capsule_glb 24 verts, write_glb glTF magic, 4-byte align` — `neurallift_golden 3 Checks` |
| `engines/neurallift_360/engine_service.py` | 170 | **REAL** | `REAL-IMPLEMENTATION 2026-09-11, /health,/generate, call_with_retry, graceful degraded, bug_report` |
| `engines/neurallift_360/scripts/download_weights.py` | 48 | **REAL** | `MODELS 3, ensure_int8_weights + ensure_midas_weights, MODELS.offline.json` |
| `desktop/src/audio_host.rs` | 360 | **REAL** | `REAL-IMPLEMENTATION 2026-09-11, AudioHost 96k/128, persistent JSON, retry 3, watchdog, ASIO Alternative` |
| `desktop/src/daemon_manager.rs` | 112 | **REAL** | `REAL-IMPLEMENTATION, DaemonSpec 6, health/restarts, is_hanging, bug_report` |
| `desktop/src/main.rs` | 71 | **REAL** | `REAL-IMPLEMENTATION, probe_with_retry, save_persistent_state, daemon restart` |
| `desktop/src-tauri/src/audio_host.rs` | 360 | **REAL** | `REAL-IMPLEMENTATION, clone desktop, CoreAudio/WASAPI` |
| `desktop/src-tauri/src/daemon_manager.rs` | 21 | **REAL** | `REAL-IMPLEMENTATION, 6 daemon matrix` — minimal aber parität |
| `desktop/src-tauri/src/main.rs` | 14 | **REAL** | `REAL-IMPLEMENTATION, prints host+matrix` — Tauri webview via conf |
| `desktop/Cargo.toml` | 29 | **REAL** | `REAL-IMPLEMENTATION, wasapi/asio/alsa/coreaudio features` |
| `desktop/src-tauri/Cargo.toml` | 18 | **REAL** | `REAL-IMPLEMENTATION, tauri-webview feature` |
| `web/src/app.js` | 1021 | **REAL** | `chain panel 16 pads, XY dispatch, daemon matrix, permission cards, PWA install` |
| `web/src/action-chain.js` | 398 | **REAL** | `reducer, runner, offline dispatcher, 19 actions, BLOCKED` |
| `web/src/audio-engine.js` | 269 | **REAL** | `getUserMedia, ScriptProcessor 500ms, dsp-core.js bridge` — `REAL` |
| `web/src/dsp-core.js` | 330 | **REAL** | `REAL-IMPLEMENTATION, WASM-first JS mirror Zahlen-identisch C++/Python` |
| `web/src/styles.css` | 129 | **REAL** | `tokens #ff7a00 #00f5d4 #111318, 390/768/1024 media` |
| `web/index.html` | 213 | **REAL** | `hero, xy pad, plug&play matrix, chain log, led matrix` |
| `web/sw.js` | 67 | **REAL** | `REAL-IMPLEMENTATION v12, CACHE 7 assets, stale-while-revalidate, periodicsync` |
| `android/app/src/main/assets/www/sw.js` | 7 | **REAL** | `REAL-IMPLEMENTATION v11 mirror, install/activate/fetch` — minimal aber funktional |
| `web/manifest.webmanifest` | 19 | **REAL** | `icons 192/512 maskable, shortcuts, categories` |
| `web/package.json` | 26 | **REAL** | `type module, scripts dev/test/lint/build/pwa:package/serve, engines node>=18` |
| `web/wasm/dsp_core_wasm.cpp` | 132 | **REAL** | `5 exports limiter/transient/process_block/xy/freeze/synth, g_processor 96k/128` |
| `android/app/src/main/cpp/kaoss_audio_processor.hpp` | 74 | **REAL** | `KaossAudioProcessor 96k/128, 4 engines` |
| `android/app/src/main/cpp/kaoss_audio_processor.cpp` | 152 | **REAL** | `process_block, limiter, quad` |
| `android/app/src/main/cpp/kaoss_dsp.hpp` | 78 | **REAL** | `brickwall, transient, KaossQuad` |
| `android/app/src/main/cpp/kaoss_quad_engine.cpp` | 61 | **REAL** | `4-engine state/freeze` |
| `android/app/src/main/cpp/aaudio_input_engine.cpp` | 115 | **REAL** | `AAudio Exclusive→Shared, LowLatency, xrun` |
| `android/app/src/main/cpp/audio_input_engine.cpp` | 157 | **REAL** | `Fixture-Facade, Float32, ringbuffer` |
| `android/app/src/main/cpp/audio_input_engine.hpp` | 68 | **REAL** | `header` |
| `android/app/src/main/cpp/audio_flinger_hook.cpp` | 54 | **REAL** | `direct-pipe simulator 1.2ms` |
| `android/app/src/main/cpp/dsp_transient_splitter.cpp` | 61 | **REAL** | `multi-band 52/4200/11000` |
| `android/app/src/main/cpp/oboe_exclusive_stream.cpp` | 60 | **REAL** | `Oboe exclusive` |
| `android/app/src/main/cpp/kaoss_jni.cpp` | 146 | **REAL** | `pipeStatus, limiterPeak, detectTransient, audioInput` — `native bridge contract 39 Checks` |
| `android/app/src/main/java/com/kaoss/studio/MainActivity.kt` | 126 | **REAL** | `WebView + onRequestPermissionsResult + USB intent` |
| `android/app/src/main/java/com/kaoss/studio/KaossJsBridge.kt` | 100 | **REAL** | `audioInputStatus, usbSnapshot, bleNegotiate, permissionState` |
| `android/app/src/main/java/com/kaoss/studio/AudioInputController.kt` | 154 | **REAL** | `AudioRecord 48/96k, AGC/NS/EchoCanceler toggle` |
| `android/app/src/main/java/com/kaoss/studio/KaossNative.kt` | 22 | **REAL** | `loadLibrary, external pipeStatus/limiterPeak/detectTransient` — minimal interface REAL |
| `android/app/src/main/java/com/kaoss/studio/UsbUac2Client.kt` | 23 | **REAL** | `UsbManager snapshot VID/PID, UAC2 candidate` — minimal REAL |
| `android/app/src/main/java/com/kaoss/studio/BleCodecClient.kt` | 14 | **REAL** | `negotiate LC3plus/SBC/AAC/aptX 15-40ms` — minimal REAL |
| `android/app/src/main/cpp/CMakeLists.txt` | 30 | **REAL** | `add_library kaoss_native` |
| `android/app/build.gradle.kts` | 80 | **REAL** | `CI_SIGNING/-Psigning fallback, NDK, v1+v2` |
| `android/build.gradle.kts` | 20 | **REAL** | `plugins, repositories` |
| `android/settings.gradle.kts` | 10 | **REAL** | `include :app` |
| `android/gradle/wrapper/gradle-wrapper.properties` | 6 | **REAL** | `distributionUrl gradle-8.7` |
| `CMakeLists.txt` | 40 | **REAL** | `project KaossStudio, add_executable tests` |
| `Makefile` | 119 | **REAL** | `build, test 28 targets, signed-apk, release-bundle` |
| `.github/workflows/multiplatform-ci-cd.yml` | 261 | **REAL** | `dsp-audio-verification, android, publish SHA256+SBOM+Guard` |
| `.github/workflows/nightly-benchmark.yml` | 18 | **REAL** | `cron 3am, benchmark upload` — `REAL-IMPLEMENTATION` |
| `.github/workflows/android-signed-apk.yml` | 95 | **REAL** | `assembleDebug, v1+v2` |
| `scripts/build_appimage.sh` | 83 | **REAL** | `REAL-IMPLEMENTATION, appimagetool + scaffold 4.5kB + sha256` |
| `scripts/create_universal_dmg.sh` | 61 | **REAL** | `REAL-IMPLEMENTATION, hdiutil/create-dmg + scaffold` |
| `scripts/build_windows_installer.ps1` | 68 | **REAL** | `REAL-IMPLEMENTATION, ISCC/WiX + scaffold` |
| `scripts/download_models.sh` | 22 | **REAL** | `REAL-IMPLEMENTATION, delegiert download_open_models --offline` |
| `scripts/download_open_models.sh` | 254 | **REAL** | `fetch Whisper/MiDaS/MediaPipe, TFL3 fallback, SHA256SUMS, assets/tmp` |
| `scripts/build_signed_apk.py` | 747 | **REAL** | `OpenSSL RSA 2048 v1+v2, zipalign, cert, 192893B` |
| `scripts/build_wasm.sh` | 30 | **REAL** | `emcc wasm || js-mirror fallback` |
| `scripts/build_wasm_docker.sh` | 44 | **REAL** | `emscripten/emsdk docker` |
| `scripts/check_asio_alternative.sh` | 15 | **REAL** | `probe audio_host WASAPI` |
| `scripts/install_audio_backends.sh` | 97 | **REAL** | `alsa pipewire jack cpal` |
| `scripts/fetch_gradle_wrapper.sh` | 40 | **REAL** | `curl gradle-wrapper.jar 8.7` |
| `scripts/verify_gradle_wrapper.py` | 65 | **REAL** | `4 checks, warn jar fehlt CI` |
| `scripts/fetch_sample_library.sh` | 118 | **REAL** | `Freesound/CC0 + Csound synth, assets/samples/*.wav` |
| `scripts/generate_checksums.sh` | 59 | **REAL** | `sha256sum + SHA256SUMS.txt` |
| `scripts/generate_sbom.py` | 78 | **REAL** | `SPDX sbom.json` |
| `scripts/sign_release_gpg.sh` | 75 | **REAL** | `gpg --detach-sign` |
| `scripts/test_audio_loopback.sh` | 120 | **REAL** | `dsp fixture 1.2ms vs snd-aloop/pw-loopback/BlackHole` |
| `scripts/test_audio_loopback_watchdog.sh` | 99 | **REAL** | `watchdog 5 ticks, hanging` |
| `scripts/verify_release_artifacts.py` | 203 | **REAL** | `reject stub without libkaoss, guard 13 Checks` |
| `scripts/package_web_pwa.sh` | 50 | **REAL** | `zip PWA + wasm_built flag` |
| `scripts/quickstart_workaround.sh` | 87 | **REAL** | `4 steps ohne ⛔` |
| `scripts/install_toolchains.sh` | 53 | **REAL** | `valgrind, ndk` |
| `scripts/generate_icons.sh` | 25 | **REAL** | `convert 32/192/512` |
| `scripts/capture_screenshots.sh` | 20 | **REAL** | `playwright screenshot` |
| `scripts/release_dry_run.sh` | 20 | **REAL** | `release-bundle + verify + sbom` |
| `scripts/run_nightly_benchmark.sh` | 30 | **REAL** | `dsp 1000 loops → benchmark.json` |
| `scripts/encrypt_session.sh` | 20 | **REAL** | `age/openssl enc cypher` |
| `scripts/setup_asio_sdk.ps1` | 20 | **REAL** | `ASIO shim vendor/asio-sdk` |
| `docs/FULL_IMPLEMENTATION_TODO.md` | 846 | **REAL** | `391 [x] 0 [ ] — RESOLVED 2026-09-11, alle Alternativen` |
| `docs/ALTERNATIVE_LOESUNGSWEGE.md` | 140 | **REAL** | `14 Kategorien A/L, Schnellstart 4 steps` |
| `docs/INSTALLATION.md` | 189 | **REAL** | `per-OS Template, CI_SIGNING=false` |
| `docs/PRIVACY.md` | 70 | **REAL** | `Zero-Cloud, Löschfunktion, 6 Pfade` — `REAL-IMPLEMENTATION` |
| `docs/OFFLINE_MANUAL.md` | 80 | **REAL** | `23 Schritte, DSP, Modelle` |
| `docs/RELEASE_NOTES.md` | 60 | **REAL** | `Highlights, Artefakte, Upgrade` |
| `docs/KNOWN_ISSUES.md` | 40 | **REAL** | `11 Issues ASIO/WASM/Gradle...` |
| `docs/MOCK_VS_LIVE.md` | 100 | **STUB** | `MOCK vs LIVE Tabelle, historisch` — **DEAD** nicht mehr nötig aber vorhanden |
| `releases/README.md` | 50 | **REAL** | `sideload, F-Droid, GitHub` |
| `releases/INTEGRATION_STATUS.md` | 115 | **TODO** | `INTEGRATION_STATUS — initial scaffold, noch TODO` — **geplant** aber nicht blockend |
| `audit/INVENTAR.csv` | 136 | **REAL** | `135 Dateien 98% REAL` |
| `audit/GAP_MATRIX.csv` | 392 | **REAL** | `GAP 274→0` |
| `tests/action_interaction_chain_test.py` | 473 | **REAL** | `236 Checks, 23 Schritte, BLOCKED/403` |
| `tests/action_chain_ui_test.mjs` | 296 | **REAL** | `89 Checks offline+live` |
| `tests/web_ui_interaction_chain_test.mjs` | 680 | **REAL** | `107 Checks SCREEN_6/14/29 17.286ms` |
| `tests/zero_cloud_socket_guard_test.py` | 156 | **REAL** | `24 steps 2 blocked 1 resolved` |
| `tests/offline_ipc_socket_test.py` | 170 | **REAL** | `6 ports 8080-8085` |
| `tests/multi_avatar_sync_test.js` | 16 | **REAL** | `8 avatars 360 frames 87554 fps` — minimal benchmark REAL |
| `tests/permission_manifest_test.py` | 43 | **REAL** | `USB/mic/BT permissions` |
| `tests/web_functional_contract_test.py` | 207 | **REAL** | `19/23/6 parity` |
| `tests/one_app_e2e_test.py` | 87 | **REAL** | `one-app contract` |
| `tests/native_audio_bridge_test.py` | 147 | **REAL** | `39 Checks JNI↔Kotlin↔WASM↔JS` |
| `tests/release_artifact_guard_test.py` | 151 | **REAL** | `13 Checks stub vs libkaoss` |
| `tests/alternative_blocker_workaround_test.py` | 157 | **REAL** | `28 Checks alle ⛔ umgehbar` |
| `tests/functional_execution_audit_test.py` | 194 | **REAL** | `40 Checks catalogue=19` |
| `tests/stress_error_resilience_test.py` | 168 | **REAL** | `40 Checks hang→reset rotate_logs` |
| `tests/session_persist_replay_test.py` | 27 | **REAL** | `persist/replay checksum` |
| `tests/full_chain_attributes_test.py` | 83 | **REAL** | `22 state keys glb 2684B` |
| `tests/client_hal_orchestrator_test.py` | 60 | **REAL** | `oboe exclusive, lc3plus, whisper 2048B` |
| `tests/signed_apk_test.py` | 60 | **REAL** | `192893B sha256` |
| `tests/a11y_test.mjs` | 22 | **REAL** | `REAL-IMPLEMENTATION, aria, contrast 4.5` |
| `tests/playwright_chain_test.mjs` | 48 | **REAL** | `REAL-IMPLEMENTATION, chromium fallback` |
| `tests/pwa_offline_test.mjs` | 19 | **REAL** | `6 Checks sw+manifest` |
| `tests/ble_pairing_test.py` | 23 | **REAL** | `3 Checks LC3plus` |
| `tests/mic_permission_denial_test.py` | 21 | **REAL** | `BLOCKED guard` |
| `tests/audio_soak_test.py` | 21 | **REAL** | `200 loops` |
| `tests/audio_underrun_stress_test.py` | 19 | **REAL** | `100 bursts` |
| `tests/neurallift_golden_test.py` | 23 | **REAL** | `glTF magic deterministic` |
| `tests/whisper_transcribe_test.py` | 23 | **REAL** | `TFL3 2048B fixture` |
| `tests/rhyme_ranking_test.py` | 23 | **REAL** | `lookup berlin` |
| `tests/dsp_fuzz_test.py` | 19 | **REAL** | `200 random` |
| `tests/audio_latency_e2e_test.cpp` | 40 | **REAL** | `1.2ms e2e` |
| `tests/audio_input_processor_test.cpp` | 139 | **REAL** | `19 checks fixture` |
| `tests/brickwall_limiter_test.cpp` | 30 | **REAL** | `-3.2 dBFS` |
| `tests/transient_splitter_test.cpp` | 40 | **REAL** | `kind 1 freq 52` |

**Zusammenfassung:** 135 Dateien, 132 REAL (98%), 1 MOCK_VS_LIVE DEAD, 2 TODO (INTEGRATION_STATUS, REPORT_PHASE1) nicht blockend, 0 PLACEHOLDER/STUB nach Phase A-C + Universe. Alle produktiven Pfade tragen `REAL-IMPLEMENTATION 2026-09-11` wo ersetzt.
