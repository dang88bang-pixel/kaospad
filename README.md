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
- Stateful offline session engine with the complete action & interaction chain
  (`input.select` → `mic.arm` → `preset.apply` → `kaoss.xy`/`freeze` → `dsp.process`
  → `pad.trigger` → `transport.record` → `loop.capture` → `transcribe` → `avatar.mode`
  → `neurallift.generate` → `session.export`), including out-of-order `BLOCKED` guards,
  per-action latency, a deterministic Python mirror of the C++ DSP core and a
  `.cypher` export that embeds the whole chain plus a SHA-256 checksum.
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
make test-action-chain
make test-web-ui-chain
make test-zero-cloud
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

## Automatischer Port Loader

`make run-app` uses `app.py --port auto` by default. The app selects the first
available local port from `8080, 8086, 8088, 8090, 8099` and exposes the active
runtime through:

```text
/api/runtime
```

The UI loads this endpoint automatically and displays the active app port, base
URL and available relative API endpoints. All browser calls use relative paths so
the same app works on localhost, Android WebView, Tauri and the Arena preview.

## Eine Anwendung starten

The complete currently executable suite is available as a single local application:

```bash
make run-app
# opens http://127.0.0.1:8080/
```

`app.py` serves the PWA and all local APIs from one process:

- `/health`, `/api/status`, `/api/runtime`, `/api/state`, `/api/actions`
- `/api/action` (POST) and `/api/chain/run` (POST) for the action chain
- `/api/events`, `/api/logs`, `/api/dsp/report`
- `/native-bridge/ports`
- `/devices/status`, `/devices/select`, `/permissions/check`
- `/mesh/default`, `/avatar/frame`, `/dsp/transient`
- `/transcribe`, `/rhymes`, `/api/session/export`

For sandbox preview only, it can be bound externally:

```bash
python3 app.py --host 0.0.0.0 --port 8080
```

## Vollständige Aktions- & Interaktionskette

Seit dieser Stufe besitzt die Suite eine **zustandsbehaftete Session-Engine**
(`engines/session_engine.py`) plus einen **deterministischen Python-DSP-Kern**
(`engines/dsp_chain.py`, Port des C++-Cores). Jede Benutzerinteraktion wird als
Aktion über `POST` an die Engine übergeben, verändert den Session-State und wird
mit Sequenznummer, Engine/Port, Latenz und Status in der Aktionskette geloggt.
Falsche Reihenfolge ergibt `BLOCKED` statt eines stillen Erfolgs.

```bash
make run-app                                   # UI + State Engine
curl -s -X POST localhost:8080/api/chain/run -H 'Content-Type: application/json' -d '{"strict":true}'
curl -s localhost:8080/api/state               # Route, Permissions, Kaoss, Transport, DSP, Kette
curl -s localhost:8080/api/events?since=0      # Aktionskette als Event-Log
make demo-chain                                # Kette ohne Server in der Konsole
```

Kanonische Kette (identisch in Server, Browser-Modul und Tests):

```text
boot → input.select → permission.check → permission.grant → audio.start → mic.arm
→ preset.apply → kaoss.xy (2x) → dsp.process → pad.trigger → dsp.process → pad.trigger
→ dsp.process → transport.record → loop.capture → kaoss.freeze → transcribe
→ rhyme.lookup → avatar.mode → neurallift.generate → transport.record(stop) → session.export
```

| Aktion | Engine (Port) | Voraussetzung | Ergebnis |
|---|---|---|---|
| `input.select` | orchestrator (8080) | – | Route gelockt, Sample-Rate, `dist/device-matrix.json` |
| `permission.check` | orchestrator (8080) | `input.selected` | benötigte/erteilte/offene Permissions |
| `permission.grant` | orchestrator (8080) | `permission.checked` | Runtime-Grant (z. B. `record_audio`) |
| `audio.start` | audio (8081) | `input.selected`, `permission.granted` | Sample-Rate/Buffer, Roundtrip, Route-Lock |
| `mic.arm` | audio (8081) | `audio.started` | Eingang armed, Monitor safe |
| `preset.apply` | dsp (8084) | `audio.started` | BPM, 1/16-Step, Kaoss-XY-Mapping |
| `kaoss.xy` | dsp (8084) | `audio.started` | XY pro Modul (frozen ⇒ `held`) |
| `kaoss.freeze` | dsp (8084) | `audio.started` | Freeze pro Modul |
| `dsp.process` | dsp (8084) | `mic.armed` | Limiter/Transient/Metering, Checksum |
| `pad.trigger` | dsp (8084) | `mic.armed` | Bank A-D, Transient, 808-Voice |
| `transport.record` | orchestrator (8080) | `dsp.processed` | Aufnahme Start/Stop |
| `loop.capture` | dsp (8084) | `transport.recording` | BPM-quantisierter Loop + Looper-Freeze |
| `transcribe` | whisper (8085) | `mic.armed` | Offline-Transkript + Reime |
| `rhyme.lookup` | whisper (8085) | `permission.checked` | SQLite-Reim-Matrix |
| `avatar.mode` | avatar (8083) | `audio.started` | Stage-Modus, FPS, Avatare, Bones |
| `neurallift.generate` | neurallift (8082) | `avatar.mode` | prozedurales GLB (Offline-Fallback) |
| `session.export` | orchestrator (8080) | `mic.armed` | `.cypher` inkl. Aktionskette + SHA-256 |
| `chain.reset` | orchestrator (8080) | – | Kette und State auf Null |

Alle Aktionen sind zusätzlich unter eigenen Pfaden erreichbar
(`/api/input/select`, `/api/kaoss/xy`, `/api/dsp/process`, `/api/pad/trigger`,
`/api/transport/record`, `/api/loop/capture`, `/api/transcribe`,
`/api/avatar/mode`, `/api/neurallift/generate`, `/api/session/export`, …) und
werden im Multi-Daemon-Modus (`make run-localhost-ipc`) vom jeweils zuständigen
Port serviert – inklusive Rollentrennung (fremde Aktion ⇒ `403`).

Im Browser bildet das Panel **Aktions- & Interaktionskette** die Kette ab:
`VOLLSTÄNDIGE KETTE AUSFÜHREN`, Ketten-Reset, strict-Schalter, Record/Loop,
16 Pads (Bank A-D), XY-Pad-Dispatch, Avatar-Modus, NeuralLift-GLB, Transkript
inkl. Reime, `.cypher`-Export und ein Live-Kettenlog mit Sequenz, Port, Latenz
und Status. Ohne Backend (statische `file://`-Preview) greift derselbe Code auf
einen deterministischen Offline-Dispatcher zurück.

### Ketten-Tests

```bash
make test-action-chain      # HTTP: 236 Checks (Guards, DSP, Determinismus, Projektionen)
make test-action-chain-ui   # Node: Browsermodul offline + gegen echten Server (89 Checks)
make test-web-ui-chain      # Node: echtes app.js mit DOM-Stub gegen echten Server (93 Checks)
make test-zero-cloud        # Socket-Monkeypatch: keine Nicht-Loopback-Ziele
```

## Kaoss Quad Console & Vault

The unified app now includes a single console for live performance control:

- Theme presets: `90s Tape Reel`, `Acid Berlin`, `Cyber Drill`, `Lo-Fi Cypher`.
- Four FX freeze buttons: Looper, Vinyl, Filter, Tape Echo.
- Sample banks A-D for 808, snare/clap, hat/percussion and vocal FX slots.
- `.cypher` session export through `/api/session/export` or the UI button.
- Live one-app log panel through `/api/logs`.

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
