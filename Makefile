.PHONY: scaffold-all-platforms build test test-native-dsp-latency test-offline-daemons test-web test-permissions test-web-contract test-one-app test-action-chain test-action-chain-ui test-web-ui-chain test-zero-cloud test-session-store test-chain-attributes test-client-hal demo-chain run-app run-localhost-ipc clean release-bundle install-toolchains signed-apk test-signed-apk test-gradle-wrapper test-native-audio-bridge test-release-guard download-open-models test-audio-loopback checksums sign-gpg workaround quickstart

scaffold-all-platforms:
	@echo "Scaffold already present for Android, desktop, engines, tests, web and CI."

DSP_CORE_SOURCES = android/app/src/main/cpp/audio_flinger_hook.cpp android/app/src/main/cpp/audio_input_engine.cpp android/app/src/main/cpp/dsp_transient_splitter.cpp android/app/src/main/cpp/kaoss_audio_processor.cpp android/app/src/main/cpp/kaoss_quad_engine.cpp android/app/src/main/cpp/oboe_exclusive_stream.cpp

build:
	@if command -v cmake >/dev/null 2>&1; then \
		cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_UNIT_TESTS=ON && \
		cmake --build build --config Release; \
	else \
		mkdir -p build && \
		g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -pthread -Iandroid/app/src/main/cpp tests/audio_latency_e2e_test.cpp $(DSP_CORE_SOURCES) -o build/audio_latency_e2e_test && \
		g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -pthread -Iandroid/app/src/main/cpp tests/brickwall_limiter_test.cpp $(DSP_CORE_SOURCES) -o build/brickwall_limiter_test && \
		g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -pthread -Iandroid/app/src/main/cpp tests/transient_splitter_test.cpp $(DSP_CORE_SOURCES) -o build/transient_splitter_test && \
		g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -pthread -Iandroid/app/src/main/cpp tests/audio_input_processor_test.cpp $(DSP_CORE_SOURCES) -o build/audio_input_processor_test; \
	fi

test: test-native-dsp-latency test-offline-daemons test-web test-permissions test-web-contract test-one-app test-action-chain test-action-chain-ui test-web-ui-chain test-zero-cloud test-session-store test-chain-attributes test-client-hal test-signed-apk test-native-audio-bridge test-release-guard test-gradle-wrapper

test-native-dsp-latency: build
	./build/audio_latency_e2e_test --max-latency=1.2ms
	./build/brickwall_limiter_test --threshold=-3.2dBFS
	./build/transient_splitter_test
	./build/audio_input_processor_test

test-native-audio-bridge:
	python3 tests/native_audio_bridge_test.py

test-release-guard:
	python3 tests/release_artifact_guard_test.py

test-gradle-wrapper:
	python3 scripts/verify_gradle_wrapper.py

test-offline-daemons:
	python3 tests/offline_ipc_socket_test.py

test-web:
	node tests/multi_avatar_sync_test.js

test-permissions:
	python3 tests/permission_manifest_test.py
	python3 engines/device_matrix.py >/tmp/kaoss-device-matrix.json

test-web-contract:
	python3 tests/web_functional_contract_test.py

test-one-app:
	python3 tests/one_app_e2e_test.py

test-action-chain:
	python3 tests/action_interaction_chain_test.py
	python3 tests/functional_execution_audit_test.py
	python3 tests/stress_error_resilience_test.py

test-action-chain-ui:
	node tests/action_chain_ui_test.mjs

test-web-ui-chain:
	node tests/web_ui_interaction_chain_test.mjs

test-zero-cloud:
	python3 tests/zero_cloud_socket_guard_test.py

test-session-store:
	python3 tests/session_persist_replay_test.py

test-chain-attributes:
	python3 tests/full_chain_attributes_test.py

test-client-hal:
	python3 tests/client_hal_orchestrator_test.py

signed-apk:
	python3 scripts/build_signed_apk.py

test-signed-apk: signed-apk
	python3 tests/signed_apk_test.py

demo-chain:
	python3 engines/session_engine.py

run-app:
	python3 app.py

run-localhost-ipc:
	python3 engines/localhost_ipc_suite.py

release-bundle: test
	python3 engines/neurallift_360/scripts/download_weights.py --target=dist/offline-models
	./scripts/build_appimage.sh

# Alternative Lösungswege (docs/ALTERNATIVE_LOESUNGSWEGE.md) — alles ohne ⛔
download-open-models:
	./scripts/download_open_models.sh --target dist/offline-models

test-audio-loopback:
	./scripts/test_audio_loopback.sh

checksums:
	./scripts/generate_checksums.sh dist/offline-models
	python3 scripts/generate_sbom.py

sign-gpg:
	./scripts/sign_release_gpg.sh dist

workaround quickstart:
	./scripts/quickstart_workaround.sh

install-toolchains:
	./scripts/install_toolchains.sh

clean:
	rm -rf build dist
