# Installation — KaossBeatboxStudio v5.0.0

> Template generiert aus `docs/ALTERNATIVE_LOESUNGSWEGE.md` — offline-first, ohne ⛔-Blocker sideload-fähig.

## Schnellstart (alles ohne ⛔ — Dev & Test)

```bash
# 1. Open-Source-Modelle pullen (offline: Platzhalter TFL3)
./scripts/download_open_models.sh   # Whisper-tiny, MiDaS, MediaPipe
# check: ls -lh dist/offline-models/

# 2. Selbstsigniert bauen (CI_SIGNING=false → kein Signing nötig)
./gradlew assembleDebug -Psigning=false
# Alternativ offline ohne Gradle (OpenSSL RSA-2048 v1+v2):
python3 scripts/build_signed_apk.py
# oder via Docker/Emscripten für WASM:
./scripts/build_wasm_docker.sh   # emscripten/emsdk

# 3. Per ADB installieren (kein Store)
adb install app/build/outputs/apk/debug/app-debug.apk
# bzw. aus releases/:
adb install releases/KaossBeatboxStudio-v5.0.0-Universal-Signed.apk

# 4. Audio-Loopback testen (Linux)
pw-dump | jq '.[] | select(.name=="alsa_output...")'
./scripts/test_audio_loopback.sh
```

Verdacht: Alles ⛔ ist für Dev/Test umgangen. Echte Stores/Zertifikate erst für Release-Artefakte nötig.

---

## Android (Sideload / CI-Artefakt)

### Voraussetzungen ohne Store

* `adb` (`android-tools-adb`), Gerät mit USB-Debugging oder Emulator
* `scrcpy` optional für Mirroring/Tests (`sudo apt install scrcpy`)
* Cheap USB-Interface (<30€) für UAC2-Test, BLE-Mic = normale BT-Kopfhörer

### Installation

| Weg | Befehl | Hinweis |
|---|---|---|
| **A. Gradle (mit SDK)** | `./gradlew -p android :app:assembleRelease` | Braucht JDK 17 + SDK 35 + NDK 26 (siehe `.github/workflows/android-signed-apk.yml`) |
| **B. Ohne Gradle (offline)** | `python3 scripts/build_signed_apk.py` | Erzeugt `releases/KaossBeatboxStudio-*-Signed.apk` (v1 JAR + v2 Block 42, OpenSSL) |
| **C. CI-Artefakt** | GitHub → Actions → *Android signed APK* → Run workflow | Artifact `KaossBeatboxStudio-v5.0.0-cloud-signed` |
| **D. PWA (ohne APK)** | `./scripts/package_web_pwa.sh` | `dist/KaossBeatboxStudio-WebAssembly-Offline.zip` — installierbar als PWA |
| **Sideload** | `adb install app/build/outputs/apk/release/app-release.apk` | Kein Play-Zugang nötig. F-Droid / GitHub Releases / itch.io als Distribution |

### Self-Signed Keystore (Dev)

```bash
keytool -genkeypair -keystore android/signing/debug.jks -alias kaoss \
  -keyalg RSA -keysize 2048 -validity 3650 \
  -storepass android -keypass android \
  -dname "CN=Kaoss Debug, OU=Offline, O=Kaoss, L=Berlin, C=DE"
# build:
CI_SIGNING=false ./gradlew assembleDebug   # unsigniert
./gradlew assembleDebug -Psigning=false    # unsigniert
# release self-signed (ohne Store):
jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA-256 -keystore android/signing/debug.jks app-release-unsigned.apk kaoss
```

### Signing in CI ohne Secrets

Workflow `.github/workflows/multiplatform-ci-cd.yml` → Step *Prepare signing keystore*:

```yaml
if [ -n "${KAOSS_KEYSTORE_BASE64:-}" ]; then
  echo "${KAOSS_KEYSTORE_BASE64}" | base64 -d > keystore.jks
else
  keytool -genkeypair -keystore keystore.jks -alias kaoss ... # self-signed Fallback
fi
```

→ Release nur bei Tag `v*.*.*` → publiziert `release-assets/*` mit `SHA256SUMS` + `sbom.json`.

---

## Linux

### Audio-Backends ohne ASIO

| Backend | Install | Route |
|---|---|---|
| **ALSA** | `sudo apt install libasound2-dev alsa-utils` | `alsa://default` — 96kHz/128 → 1.2ms |
| **PipeWire** | `sudo apt install pipewire pipewire-alsa` | `pipewire://default` |
| **JACK** | `sudo apt install jackd2 libjack-jackd2-dev` | `jack://default` |
| **PortAudio / RtAudio** | `sudo apt install portaudio19-dev librtaudio-dev` | Cross-platform |

Test: `./scripts/install_audio_backends.sh`
Loopback: `modprobe snd-aloop` oder `pw-loopback` → `./scripts/test_audio_loopback.sh`

### Desktop Bundle

```bash
cd desktop && cargo build --release
./scripts/build_appimage.sh        # dist/KaossBeatboxStudio-v5.0.0-x86_64.AppImage
./scripts/create_universal_dmg.sh  # macOS (auf macos-latest)
```

---

## macOS

* CoreAudio (System), BlackHole für Loopback: `brew install blackhole-2ch`
* Hardened Runtime / Notarization erst für Store-Release nötig; Dev: `codesign --force --deep --sign - dist/*.dmg`

## Windows

* **WASAPI Exclusive** (im Repo: `oboe_exclusive_stream.cpp`) — kein ASIO SDK nötig.
* ASIO nur für Pro-Users: Steinberg SDK lizenzieren → `scripts/setup_asio_sdk.ps1`
* MSI: `desktop/target/release` + `scripts/build_windows_installer.ps1` (braucht WiX auf `windows-latest`)

## Web / PWA — Zero-Cloud

* Served via `app.py` (one-app) oder `make run-app` → `http://127.0.0.1:8080`
* WASM: `./scripts/build_wasm.sh` (braucht `emcc`) oder Docker-Alternative:
  `docker run --rm -v $PWD:/src emscripten/emsdk bash build_wasm.sh` / `./scripts/build_wasm_docker.sh`
* Ohne WASM: `web/src/dsp-core.js` JS-Spiegel — zahlen-identisch zu C++/Python.

## Daten / Modelle (J)

```bash
./scripts/download_open_models.sh --with-mediapipe --with-emote
sha256sum dist/offline-models/* > SHA256SUMS.txt   # J
./scripts/generate_checksums.sh dist/offline-models
ls -lh dist/offline-models/     # TFL3 placeholders offline, echte weights online
cat dist/offline-models/MODELS.offline.json
```

*Whisper*: `openai/whisper` → `whisper.cpp` gguf; *MiDaS*: `Intel/dpt-hybrid-midas` (MIT); *EMOTE/dance-diffusion* (Apache 2.0); *MediaPipe* TFLite self-convert. Offline-Fallback: deterministische `TFL3` Bytes.

## Sample-Library (CC0)

```bash
./scripts/fetch_sample_library.sh assets/samples offline   # CC0 synthetisch via dsp_chain
# Freesound CC0 (mit API-Key):
FREESOUND_API_KEY=xxx ./scripts/fetch_sample_library.sh assets/samples freesound
# Csound/SuperCollider optional:
# Csound, SuperCollider
```

## Hardware-Tests ohne exotische Hardware (I)

```bash
./scripts/test_audio_loopback.sh   # Virtual-Cable (VB-Cable/Loopback/BlackHole) + DSP Fallback
python3 engines/local_audio_probe.py
python3 engines/usb_uac2.py        # sysfs hotplug
# Emulator:
emulator -avd Pixel_7_API_34 &
adb shell am start -a android.media.action.IMAGE_CAPTURE
scrcpy
# BLE-Mic = normale BT-Kopfhörer (LC3plus 12ms comp, SBC 42ms)
```

## Checksums & GPG (L)

```bash
./scripts/generate_checksums.sh dist/offline-models
./scripts/generate_sbom.py        # dist/sbom.json (SPDX)
gpg --detach-sign -a dist/*.AppImage  # oder:
./scripts/sign_release_gpg.sh dist
sha256sum -c dist/SHA256SUMS.txt  # verify
gpg --verify dist/*.asc
```

## KP3+ Rechtliches

Preset-Namen sind eigene Begriffe (`KaoSS`, `90s_tape`, `Acid Berlin`); Layouts neu gezeichnet. Hinweis im Impressum ausreichend für Dev. Kein Korg-Logo/Type.

---

## Bekannte Einschränkungen (ehrlich)

* Offline-APK via `build_signed_apk.py` startet, hat aber **kein ART-Dex mit NDK .so** — echter NDK-Build nur via Gradle+SDK (CI oder lokal nach `install_toolchains.sh`).
* Tests nutzen deterministischen Fixture-Ringbuffer, nicht echte Hardware-Latenz (außer BlackHole/snd-aloop).
* Whisper/MiDaS sind offline-Shims (`TFL3` magic) bis echte Weights via `download_open_models.sh` gezogen werden.

---

## Quellen & Lizenzen der Alternativen

* RtAudio/PortAudio/JACK/WASAPI — MIT/LGPL/GPL, kein SDK
* Whisper/MiDaS/EMOTE/MediaPipe — MIT/Apache 2.0
* Freesound/SonusLab/KVR — CC0
* Keytool/OpenSSL — JDK/OS, kostenlos

