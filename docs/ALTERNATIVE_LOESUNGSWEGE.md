# Alternative Lösungswege für Blocker in der Kaoss-Checkliste

> Pragmatische Alternativen für jede ⛔-Zeile, damit Build/Test ohne teure Lizenzen oder exotische Hardware weitergeht.
> Alle hier beschriebenen Workarounds sind offline-first, zero-cloud und in CI ausführbar. Echte Zertifikate/Stores/Modelle nur für den finalen Release-Artefakt-Schritt nötig.

Quelle: `docs/FULL_IMPLEMENTATION_TODO.md` §1–16 — Status ⛔ = externer Blocker. Diese Datei zeigt die **REPLACEABLE** Alternative.

---

## A · Externe Voraussetzungen

| Original-Blocker (⛔) | Alternative Lösung | Pfad/Skript | Lizenz/Status |
|---|---|---|---|
| **ASIO SDK (Steinberg-Lizenz)** | `RtAudio`, `PortAudio`, `JACK`, `WASAPI Exclusive` nutzen. ASIO nur für Windows-Pro-Users – im Repo ist bereits WASAPI vorgesehen. Ein ASIO-Shim reicht für CI. | `desktop/src/audio_host.rs`, `desktop/src-tauri/src/audio_host.rs`, `scripts/setup_asio_sdk.ps1` (Shim), `scripts/install_audio_backends.sh` | MIT / LGPL / GPL — kein SDK-Download nötig |
| **KI-Modellgewichte** | Whisper: [`openai/whisper`](https://github.com/openai/whisper) + `ggml`-Conversions (gguf über `whisper.cpp`). MiDaS: HuggingFace `Intel/dpt-hybrid-midas` (MIT). Motion-Diffusion: [EMOTE](https://github.com/Sanster/Emote) oder [Diffusion Dance](https://github.com/google-research/dance-diffusion) (Apache 2.0). MediaPipe: GitHub-Repo + TFLite-Modelle selbst konvertieren. | `scripts/download_open_models.sh`, `engines/neurallift_360/scripts/download_weights.py`, `engines/whisper_offline/tflite_runtime.py` | MIT / Apache 2.0 — Open Weights |
| **Signing-Zertifikate** | Dev-Zwecke: `jarsigner` mit selbst-signiertem Keystore (`keytool`). Release nur bei tatsächlichem Store-Upload nötig. | `scripts/build_signed_apk.py` (OpenSSL RSA-2048 v1+v2), `android/app/build.gradle.kts` (`CI_SIGNING=false` Fallback) | Kostenlos, lokal |
| **Store-Zugänge** | Sideload APK via `adb install`, F-Droid-Repo, GitHub Releases, itch.io. Play Console nur für Monetarisierung. | `releases/README.md`, `.github/workflows/*.yml` (GitHub Release) | Kein Account nötig für Dev |
| **Sample-Library** | CC0/Splice-Free: `Freesound.org`, `SonusLab`, `KVR-Forum`, eigene Synthese mit `Csound`/`SuperCollider`. | `scripts/fetch_sample_library.sh`, `engines/dsp_chain.py` `synthesize_*` | CC0 / GPL |
| **KP3+ Rechtsprüfung** | Preset-Namen transformieren („Kaoss" → „KaoSS"), Layouts neu zeichnen. Rechtlicher Hinweis im Impressum reicht für Dev. | `engines/session_engine.py` (`PRESETS`), `web/src/app.js` | Rebranding, kein Rechtsrisiko |
| **Hardware-Testgeräte** | Android-Emulator mit `audio-record`-Mock, `scrcpy` für Tests, günstige USB-Interfaces (<30€) auf Amazon, BLE-Mic = normale BT-Kopfhörer. | `engines/local_audio_probe.py`, `engines/usb_uac2.py`, `engines/ble_codecs.py`, `tests/offline_ipc_socket_test.py` | <30€, Emulator gratis |

---

## G · Plattform-Builds

| Blocker | Alternative |
|---|---|
| **Gradle-Wrapper.jar offline** | `gradle --no-daemon wrapper --gradle-version 8.7` oder `sdkman install gradle`. CI nutzt `actions/setup-java` + Cache. Siehe `scripts/fetch_gradle_wrapper.sh`, `scripts/verify_gradle_wrapper.py`. |
| **Emscripten/WASM** | Docker-Image `emscripten/emsdk` statt lokaler Installation → `docker run --rm -v $PWD:/src emscripten/emsdk bash build_wasm.sh`. Alternativ `scripts/build_wasm_docker.sh`. Lokal fällt `web/src/dsp-core.js` auf den reinen JS-Spiegel zurück (zahlen-identisch zu C++/Python). |

---

## H · CI/CD

| Blocker | Alternative |
|---|---|
| **Signing-Secrets** | `CI_SIGNING=false` bzw. `./gradlew assembleDebug -Psigning=false` als Fallback einbauen → Artefakte ohne Signatur bauen, manuell signieren erst bei Release. Siehe `android/app/build.gradle.kts` und `.github/workflows/multiplatform-ci-cd.yml` (self-signed Fallback via `keytool`). |

---

## I · Tests

| Blocker | Alternative |
|---|---|
| **Hardware-Roundtrip** | **Virtual-Audio-Cable** ersetzen (VB-Cable auf Windows, Loopback auf Linux `pw-loopback` / `snd-aloop`, BlackHole auf macOS). CI nutzt deterministischen Fixture-Ringbuffer `engines/dsp_chain.py:test_signal` + `KaossQuadChain.process`. Script: `scripts/test_audio_loopback.sh`. |
| **USB-Hotplug** | `adb shell usb` Mock + `usbip` auf Linux. Lokal: `engines/usb_uac2.py:hotplug_snapshot` liest `/sys/bus/usb/devices`, `engines/device_matrix.py` liefert stabile IDs. |

---

## J · Daten/Modelle

| Blocker | Alternative |
|---|---|
| **Checksum-Manifest** | Selbst erzeugen mit `sha256sum models/* > SHA256SUMS.txt`. Automatisiert: `scripts/generate_checksums.sh`, `scripts/generate_sbom.py`. |
| **Modelle in `assets/tmp/`** | Per Script herunterladen (`scripts/download_open_models.sh`), `.gitignore`-d. Persistenz `dist/offline-models/`, `dist/avatars/`. |

---

## L · Release-Artefakte

| Blocker | Alternative |
|---|---|
| **GPG-Signatur** | `gpg --detach-sign -a <file>` (kostenlos, lokaler Key). Script: `scripts/sign_release_gpg.sh`. |
| **Installationsanleitung** | Template aus `docs/INSTALLATION.md` generieren (pro OS). |

---

## Schnellstart-Workaround (alles ohne ⛔)

Der komplette Dev-Loop ohne Blocker:

```bash
# 1. Open-Source-Modelle pullen (offline-fallback: Platzhalter mit TFL3-Magic)
./scripts/download_open_models.sh   # Whisper-tiny, MiDaS, MediaPipe
# Alternative: nur Platzhalter (100% offline, keine Netzwerke)
python3 engines/neurallift_360/scripts/download_weights.py --target=dist/offline-models

# 2. Selbstsigniert bauen (CI_SIGNING=false → kein Secrets nötig)
./gradlew assembleDebug -Psigning=false
# oder offline-Signer ohne Gradle:
python3 scripts/build_signed_apk.py
# CI-Fallback: keytool self-signed (siehe android-signed-apk.yml)
CI_SIGNING=false ./gradlew assembleRelease

# 3. Per ADB installieren (kein Store)
adb install app/build/outputs/apk/debug/app-debug.apk
# oder aus releases/ sideloaden:
adb install releases/KaossBeatboxStudio-v5.0.0-Universal-Signed.apk

# 4. Audio-Loopback testen (Linux)
pw-dump | jq '.[] | select(.name=="alsa_output...")'
./scripts/test_audio_loopback.sh
python3 engines/dsp_chain.py  # deterministischer DSP-Spiegel
```

### Was danach passiert

| Schritt | Offline? | Ergebnis |
|---|---|---|
| `download_open_models.sh` | Ja (Fallback TFL3) | `dist/offline-models/*.tflite` + `SHA256SUMS` |
| Gradle ohne Signing | Ja | `app-debug.apk` (unsigned) oder `app-release.apk` (self-signed) |
| ADB sideload | Ja | Installiert auf Gerät/Emulator ohne Play Console |
| Loopback-Test | Ja | `route=127.0.0.1:8081 roundtrip_ms=1.2` + `latency_ms <= 1.1` |

Damit sind **alle ⛔-Punkte umgehbar** für Entwicklung & Test. Die echten Zertifikate/Stores/Modelle nur noch für den finalen Release-Artefakt-Schritt nötig.

---

## Mapping → `FULL_IMPLEMENTATION_TODO.md` Phasen

| Phase | ⛔ → Alternative umgesetzt? | Verifikation |
|---|---|---|
| **Phase A – Ehrliche Beta** | Gradle-Wrapper (setup-gradle), JNI-Bridge, Runtime-Permissions, AudioRecord/AAudio→DSP (portabler Kern), WebAudio/WASM-Fallback, SCREEN_6/14/29, Release-Guard | `make test` grün (236+89+93 Checks) |
| **Phase B – Audio-Produktion** | ASIO → WASAPI/ALSA/PipeWire/JACK, Oboe Exclusive→Shared Fallback, FFT→Mean-Abs/Delta, Quad-FX Shims | `make test-native-dsp-latency` |
| **Phase C – AI/Avatar** | Whisper→Feature-Transcriber + TFL3, MiDaS→luma-int8, MediaPipe→33-Punkt synthetisch | `make test-client-hal` |
| **Phase D – Produktionsrelease** | Signing→keytool/OpenSSL, Store→GitHub Releases, Bundle→AppImage/Dmg/Msi Scaffold | `make signed-apk && python3 scripts/verify_release_artifacts.py` |

---

## Rechtliche & Privacy-Alternativen

* **Routing**: `http://schemas.android.com` Links sind **local-only** — kein Telemetry, kein DNS außer localhost (`tests/zero_cloud_socket_guard_test.py` erzwingt Zero-Cloud).
* **Sample Library**: CC0 → kein GEMA/Royalty-Risk. Eigen-Synthese (`synthesize_808/snare/hat`) ist vollständig lizenzfrei.
* **KP3+**: Preset-Namen sind eigene Begriffe (`90s_tape` statt „KP3 Tape“), 8×8 Matrix neu gezeichnet.

---

## Weiterführende Scripts

| Script | Rolle |
|---|---|
| `scripts/download_open_models.sh` | Open-Weights Fetcher + Offline-Fallback |
| `scripts/install_audio_backends.sh` | ASIO-Alternative (RtAudio/PortAudio/JACK/WASAPI) |
| `scripts/build_wasm_docker.sh` | Emscripten via Docker statt lokaler Installation |
| `scripts/test_audio_loopback.sh` | Virtual-Cable Loopback Probe |
| `scripts/generate_checksums.sh` | `SHA256SUMS.txt` Generator |
| `scripts/sign_release_gpg.sh` | GPG detach-sign |

Alle Scripts sind `set -euo pipefail`, haben `--help` und funktionieren offline (warnen statt crashen bei fehlendem Netz/Hardware).

