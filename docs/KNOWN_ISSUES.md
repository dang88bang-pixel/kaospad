# Known Issues — v5.0.0 (2026-09-11)

- **ASIO SDK:** Steinberg Lizenz nötig für echten ASIO — Fallback WASAPI Exclusive real, Shim `vendor/asio-sdk/README.txt` für CI
- **WASM Build:** `emcc` fehlt in Sandbox — `web/src/dsp-core.js` JS-Spiegel ist zahlen-identisch, Docker `emscripten/emsdk` in CI geht
- **Gradle Wrapper JAR:** fehlt offline — CI nutzt `gradle/actions/setup-gradle` 8.7, lokal `scripts/fetch_gradle_wrapper.sh`
- **Hardware Latenz:** Echte Loopback-Messung braucht `snd-aloop`/`pw-loopback`/`BlackHole` — Fixture `1.2ms` in `dsp_chain`
- **USB Testmatrix:** 5 echte Interfaces nicht in CI — `usb_uac2.py` Mock + Web UI 3 Cards
- **Playwright:** Nur DOM-Stub-Harness, echte Browser-Runs offen (`npm run test:e2e` fallback)
- **Valgrind/LeakCanary:** nicht in Sandbox — `engines/watchdog.py` simuliert via `events>4096`, real via `scripts/install_toolchains.sh`
- **Store Signing:** `CI_SIGNING=false` fallback unsigniert, echte Keys nur auf Tag-Runner
- **Icons/Screenshots:** 192/512 Icons nur placeholder base64 1×1, echte Assets in `assets/icons/` offen
- **SBOM Attestierung:** `dist/sbom.json` erzeugt, aber nicht im Release attestiert (cosign offen)
- **C++ WASM Parity:** `web/wasm/dsp_core_wasm.cpp` hat `return 0` Guards — real via `emcc` in CI
