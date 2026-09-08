# Korg Kaoss Pad & AI Beatbox Studio // NeuralLift-360

Offline-first scaffold for a multi-platform Kaoss-style beatbox, DSP, localhost IPC and 3D avatar performance suite.

## Projektstatus / vollständige TODO-Dokumentation

Der aktuelle Implementierungsstand, alle fehlenden Parts, Native-/Hardware-Anbindungen,
Attribute, UI-Screens, Tests und Release-Aufgaben sind vollständig als abarbeitbare
Liste dokumentiert in:

- [`docs/FULL_IMPLEMENTATION_TODO.md`](docs/FULL_IMPLEMENTATION_TODO.md)
- [`VALIDATION_REPORT.md`](VALIDATION_REPORT.md)

## What is included

- Native C++ DSP core with deterministic tests for:
  - simulated low-latency AudioFlinger/Oboe direct pipe
  - `-3.2 dBFS` brickwall soft-knee limiter
  - mouth-bass transient detection and 808 synthesis
  - 4-module Kaoss Quad state/freeze engine
- Localhost-only NeuralLift-360 daemon reference on `127.0.0.1:8082`.
- Offline model manifest generator; it never downloads cloud assets.
- Web/PWA cyber-hardware UI prototype with service-worker cache.
- Minimal desktop Rust host describing ALSA/CoreAudio/ASIO routing matrix.
- CI workflows for native validation, multi-platform artifact packaging and GitHub release publication.

> Note: hardware HAL hooks, proprietary ASIO SDK pieces, model weights and store-grade signing certificates cannot be generated inside CI without vendor assets. This repo keeps those boundaries explicit and provides safe, offline, buildable shims that can be replaced by real platform integrations.

## Quick start

```bash
make test
```

Run individual gates:

```bash
make test-native-dsp-latency
make test-offline-daemons
make test-web
```

Prepare deterministic offline model placeholders:

```bash
python3 engines/neurallift_360/scripts/download_weights.py --target=dist/offline-models
```

Build the Linux scaffold bundle:

```bash
make release-bundle
```

## Localhost IPC matrix

| Port | Service | Policy |
|---:|---|---|
| 8080 | master-system-orchestrator | localhost only |
| 8081 | audio-loopback-daemon | localhost only |
| 8082 | neurallift-engine | localhost only |
| 8083 | avatar-orchestrator | localhost only |
| 8084 | dsp-transient-bridge | localhost only |
| 8085 | offline-whisper-daemon | localhost only |

## Eine Anwendung starten

The complete currently executable suite is available as a single local application:

```bash
make run-app
# opens http://127.0.0.1:8080/
```

`app.py` serves the PWA and all local APIs from one process:

- `/health` and `/api/status`
- `/native-bridge/ports`
- `/devices/status`, `/devices/select`, `/permissions/check`
- `/mesh/default`, `/avatar/frame`, `/dsp/transient`
- `/transcribe`, `/rhymes`

For sandbox preview only, it can be bound externally:

```bash
python3 app.py --host 0.0.0.0 --port 8080
```

## Funktionsbereite Browser-Audio-Engine

The PWA now includes a directly runnable WebAudio performance path:

- `AUDIO STARTEN` creates an interactive `AudioContext`.
- `MIC ARMEN` requests microphone access with echo cancellation, AGC and noise suppression disabled where the browser allows it.
- `808 TEST` synthesizes a glide 808 kick through a `-3.2 dBFS` waveshaper limiter.
- `SNARE TEST` synthesizes a filtered noise snare.
- The XY pad controls filter cutoff, resonance, delay time and feedback in real time.
- The meter shows live peak level.
- Browser audio inputs are enumerated with `enumerateDevices()` after permission.
- The rhyme helper uses the localhost `/rhymes` API when available and a zero-cloud fallback otherwise.

## Plug & Play Audio Input Matrix

The local master orchestrator exposes configurable input selection and permission
status for USB-C audio, the internal microphone and Bluetooth/BLE microphone
clients:

```bash
make run-localhost-ipc
curl http://127.0.0.1:8080/devices/status?selected=usb_c_audio
curl http://127.0.0.1:8080/devices/select?input=bluetooth_client
curl http://127.0.0.1:8080/permissions/check
```

The web UI renders the same status as cards with latency, route and permission
badges. Android declares `RECORD_AUDIO`, `MODIFY_AUDIO_SETTINGS`, USB host and
Bluetooth client permissions/features; runtime permission prompts remain handled
by the native shell or browser runtime.

## Native Bridge PortView Auto

The web view now contains a **Native Bridge PortView // AUTO** panel. In a packaged
Android/Tauri host, inject `window.__KAOSS_NATIVE_BRIDGE__.portStatus(port)` to let
the UI read live daemon state without browser-side localhost probing. In normal
browser preview mode the panel falls back to a safe zero-cloud simulation, keeping
all ports visible in the view while preserving the localhost-only rule.

## Release automation

Tag pushes matching `v*.*.*` run `.github/workflows/multiplatform-ci-cd.yml`, collect Android/Linux/macOS/Windows artifacts and publish them with `GITHUB_TOKEN`.

## Design system

- Amber glow: `#ff7a00`
- Neon cyan: `#00f5d4`
- Dark shell: `#111318`
- Typography: Space Grotesk + monospace fallbacks
