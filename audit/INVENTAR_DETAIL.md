# Inventar Detail — Phase 1 Audit

Erzeugt: 2026-09-11
Repo: dang88bang-pixel/kaospad @ arena/01a090e3-kaospad
Tool: /tmp/gen_inventory.py

## Legende
- REAL: Echte Implementierung, getestet
- MOCK: SHIM mit stabiler Schnittstelle, aber simuliert
- PLACEHOLDER: Stub-Datei, kaum Logik (<30 Zeilen, scaffold)
- TODO/FIXME: Enthält Marker, offene Implementierung
- STUB: Dummy returns
- DEAD: Nicht referenziert

Datei,Zeilen,Status,Grund,Prioritaet
web/src/app.js,1021,MOCK,MOCK/SHIM,P2
engines/session_engine.py,891,MOCK,MOCK/SHIM,P2
android/app/src/main/assets/www/src/app.js,699,MOCK,MOCK/SHIM,P2
engines/localhost_ipc_suite.py,401,MOCK,MOCK/SHIM,P2
releases/PARTS_AUDIT.md,223,MOCK,MOCK/SHIM,P2
docs/INSTALLATION.md,189,MOCK,MOCK/SHIM,P2
tests/alternative_blocker_workaround_test.py,157,MOCK,MOCK/SHIM,P2
scripts/test_audio_loopback.sh,120,MOCK,MOCK/SHIM,P2
scripts/install_audio_backends.sh,97,MOCK,MOCK/SHIM,P2
scripts/quickstart_workaround.sh,87,MOCK,MOCK/SHIM,P2
desktop/src/audio_host.rs,86,MOCK,MOCK/SHIM,P2
android/app/src/main/cpp/audio_flinger_hook.cpp,54,MOCK,MOCK/SHIM,P2
docs/MOCK_VS_LIVE.md,28,MOCK,MOCK/SHIM;scaffold placeholder,P2
desktop/Cargo.toml,27,MOCK,MOCK/SHIM;scaffold placeholder,P2
scripts/check_asio_alternative.sh,11,MOCK,MOCK/SHIM;scaffold placeholder,P2
scripts/setup_asio_sdk.ps1,3,MOCK,MOCK/SHIM;scaffold placeholder,P2
scripts/build_signed_apk.py,747,PLACEHOLDER,STUB/PLACEHOLDER,P1
tests/web_ui_interaction_chain_test.mjs,680,PLACEHOLDER,STUB/PLACEHOLDER,P1
android/app/src/main/assets/www/src/action-chain.js,398,PLACEHOLDER,STUB/PLACEHOLDER,P1
web/src/action-chain.js,398,PLACEHOLDER,STUB/PLACEHOLDER,P1
web/src/audio-engine.js,269,PLACEHOLDER,STUB/PLACEHOLDER,P1
.github/workflows/multiplatform-ci-cd.yml,261,PLACEHOLDER,STUB/PLACEHOLDER,P1
scripts/download_open_models.sh,254,PLACEHOLDER,STUB/PLACEHOLDER;dummy return,P1
scripts/verify_release_artifacts.py,203,PLACEHOLDER,STUB/PLACEHOLDER,P1
tests/release_artifact_guard_test.py,151,PLACEHOLDER,STUB/PLACEHOLDER,P1
engines/neurallift_360/glb.py,77,PLACEHOLDER,STUB/PLACEHOLDER,P1
engines/neurallift_360/engine_service.py,50,PLACEHOLDER,STUB/PLACEHOLDER,P1
releases/README.md,50,PLACEHOLDER,STUB/PLACEHOLDER,P1
engines/neurallift_360/scripts/download_weights.py,48,PLACEHOLDER,STUB/PLACEHOLDER,P1
.github/workflows/release-publisher.yml,26,PLACEHOLDER,scaffold placeholder,P1
assets/tmp/MODELS.offline.json,26,PLACEHOLDER,scaffold placeholder,P1
releases/ALTERNATIVEN.md,25,PLACEHOLDER,scaffold placeholder,P1
scripts/package_web_pwa.sh,24,PLACEHOLDER,scaffold placeholder,P1
desktop/src/daemon_manager.rs,16,PLACEHOLDER,scaffold placeholder,P1
desktop/src-tauri/src/daemon_manager.rs,16,PLACEHOLDER,scaffold placeholder,P1
releases/AEHNLICHE_PROJEKTE.md,16,PLACEHOLDER,scaffold placeholder,P1
Dockerfile.offline-build,14,PLACEHOLDER,scaffold placeholder,P1
scripts/build_appimage.sh,10,PLACEHOLDER,scaffold placeholder,P1
web/package.json,7,PLACEHOLDER,scaffold placeholder,P1
engines/whisper_offline/README.md,6,PLACEHOLDER,STUB/PLACEHOLDER;scaffold placeholder,P1
scripts/create_universal_dmg.sh,5,PLACEHOLDER,scaffold placeholder,P1
android/app/src/main/assets/www/sw.js,4,PLACEHOLDER,scaffold placeholder,P1
engines/mopac_dance_learner/README.md,4,PLACEHOLDER,scaffold placeholder,P1
web/sw.js,4,PLACEHOLDER,scaffold placeholder,P1
scripts/build_windows_installer.ps1,3,PLACEHOLDER,scaffold placeholder,P1
app.py,788,REAL,,P3
tests/action_interaction_chain_test.py,473,REAL,,P3
engines/dsp_chain.py,360,REAL,,P3
tests/action_chain_ui_test.mjs,296,REAL,,P3
web/src/dsp-core.js,270,REAL,,P3
tests/web_functional_contract_test.py,207,REAL,,P3
tests/functional_execution_audit_test.py,194,REAL,,P3
android/app/src/main/assets/www/src/audio-engine.js,180,REAL,,P3
tests/offline_ipc_socket_test.py,170,REAL,,P3
tests/stress_error_resilience_test.py,168,REAL,,P3
android/app/src/main/cpp/kaoss_audio_processor.cpp,152,REAL,,P3
tests/native_audio_bridge_test.py,147,REAL,,P3
android/app/src/main/cpp/kaoss_jni.cpp,146,REAL,,P3
tests/audio_input_processor_test.cpp,139,REAL,,P3
engines/device_matrix.py,127,REAL,,P3
android/app/src/main/java/com/kaoss/studio/MainActivity.kt,126,REAL,,P3
Makefile,119,REAL,,P3
scripts/fetch_sample_library.sh,118,REAL,,P3
android/app/src/main/java/com/kaoss/studio/KaossJsBridge.kt,100,REAL,,P3
.github/workflows/android-signed-apk.yml,95,REAL,,P3
tests/one_app_e2e_test.py,87,REAL,,P3
tests/full_chain_attributes_test.py,83,REAL,,P3
android/app/build.gradle.kts,80,REAL,,P3
android/app/src/main/cpp/kaoss_dsp.hpp,78,REAL,,P3
scripts/generate_sbom.py,78,REAL,,P3
scripts/sign_release_gpg.sh,75,REAL,,P3
android/app/src/main/cpp/kaoss_audio_processor.hpp,74,REAL,,P3
android/app/src/main/cpp/audio_input_engine.hpp,68,REAL,,P3
scripts/verify_gradle_wrapper.py,65,REAL,,P3
engines/usb_uac2.py,63,REAL,,P3
engines/whisper_offline/rhyme_matrix.py,63,REAL,,P3
android/app/src/main/cpp/dsp_transient_splitter.cpp,61,REAL,,P3
tests/client_hal_orchestrator_test.py,60,REAL,,P3
scripts/generate_checksums.sh,59,REAL,,P3
releases/ONLINE_ALTERNATIVEN.md,57,REAL,,P3
engines/whisper_offline/tflite_runtime.py,55,REAL,,P3
engines/neurallift_360/midas.py,54,REAL,,P3
scripts/install_toolchains.sh,53,REAL,,P3
engines/oboe_exclusive.py,51,REAL,,P3
engines/local_audio_probe.py,50,REAL,,P3
scripts/build_wasm_docker.sh,44,REAL,,P3
tests/permission_manifest_test.py,43,REAL,,P3
engines/whisper_offline/transcriber.py,41,REAL,,P3
tests/signed_apk_test.py,41,REAL,,P3
android/app/src/main/cpp/kaoss_quad_engine.cpp,40,REAL,,P3
scripts/build_wasm.sh,40,REAL,,P3
engines/mopac_dance_learner/pose.py,39,REAL,,P3
scripts/fetch_gradle_wrapper.sh,34,REAL,,P3
tests/brickwall_limiter_test.cpp,34,REAL,,P3
CMakeLists.txt,33,REAL,,P3
tests/transient_splitter_test.cpp,33,REAL,,P3
engines/ble_codecs.py,30,REAL,,P3
tests/audio_latency_e2e_test.cpp,28,REAL,,P3
tests/session_persist_replay_test.py,27,REAL,,P3
android/app/src/main/AndroidManifest.xml,26,REAL,,P3
desktop/src-tauri/src/audio_host.rs,25,REAL,,P3
android/app/src/main/cpp/CMakeLists.txt,24,REAL,,P3
android/app/src/main/java/com/kaoss/studio/UsbUac2Client.kt,23,REAL,,P3
android/app/src/main/java/com/kaoss/studio/KaossNative.kt,22,REAL,,P3
.github/workflows/audio-dsp-benchmark.yml,18,REAL,,P3
android/app/src/main/cpp/oboe_exclusive_stream.cpp,18,REAL,,P3
tests/multi_avatar_sync_test.js,16,REAL,,P3
android/app/src/main/java/com/kaoss/studio/BleCodecClient.kt,14,REAL,,P3
android/app/src/main/res/xml/network_security_config.xml,12,REAL,,P3
desktop/src/main.rs,11,REAL,,P3
desktop/src-tauri/src/main.rs,11,REAL,,P3
android/gradle/wrapper/gradle-wrapper.properties,7,REAL,,P3
desktop/src-tauri/Cargo.toml,7,REAL,,P3
scripts/download_models.sh,6,REAL,,P3
android/build.gradle.kts,4,REAL,,P3
android/gradle.properties,4,REAL,,P3
android/settings.gradle.kts,4,REAL,,P3
android/app/src/main/res/values/styles.xml,1,REAL,,P3
assets/samples/KIT.json,1,REAL,,P3
android/app/src/main/cpp/audio_input_engine.cpp,157,STUB,dummy return,P1
web/wasm/dsp_core_wasm.cpp,132,STUB,dummy return,P1
android/app/src/main/cpp/aaudio_input_engine.cpp,115,STUB,dummy return,P1
docs/FULL_IMPLEMENTATION_TODO.md,844,TODO,TODO/FIXME,P1
VALIDATION_REPORT.md,307,TODO,TODO/FIXME,P1
README.md,269,TODO,TODO/FIXME,P1
tests/zero_cloud_socket_guard_test.py,156,TODO,TODO/FIXME,P1
android/app/src/main/java/com/kaoss/studio/AudioInputController.kt,154,TODO,TODO/FIXME,P1
docs/ALTERNATIVE_LOESUNGSWEGE.md,140,TODO,TODO/FIXME,P1
releases/INTEGRATION_STATUS.md,115,TODO,TODO/FIXME,P1
