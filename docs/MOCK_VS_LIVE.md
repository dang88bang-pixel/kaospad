# Mock / Shim vs. live executable code

| Part | Was | Jetzt |
|---|---|---|
| Device matrix USB/Mic/BT IDs | static JSON | same IDs **plus** live ALSA/`/dev/snd` probe (`engines/local_audio_probe.py`) |
| Audio start | latency formula only | formula **plus** local PCM ringbuffer + probe snapshot |
| **Audio-Capture-Blöcke** | deterministische `test_signal()`-Fixtures | **echte Blöcke**: ALSA/`arecord`, USB-UAC2-Karte, Loopback-PCM-Pipe für BLE/UAC2-Clients, WAV-Datei; jeder Block mit Provenienz `real_capture` (`engines/audio_capture.py`) |
| DSP limiter / transient / Kaoss | Python+C++ real math | unchanged live DSP (not a stub) **plus** WASM-Build desselben C++-Kerns |
| **DSP-Kern im Browser** | JS-Neuimplementierung | `dist/wasm/kaoss_dsp.wasm` aus `kaoss_dsp_abi.cpp`; Parität gegen natives Binary + Python-Spiegel gemessen (≤ 5e-7) |
| AudioFlinger/Oboe HAL | C++ latency simulator | still HAL-sim (needs device NDK/Oboe); contract live |
| Whisper | fixed text | live feature-transcriber on PCM when no `text`; SQLite rhymes expanded |
| NeuralLift | filename string | real **glTF/GLB binary** written to `dist/avatars/` |
| Avatar skeleton | fps/count only | 33-landmark pose buffer (`mopac_dance_learner/pose.py`) |
| Session store | RAM only | `.cypher.json` persist + **params-treues Replay** + `dist/sessions/`-Inventar + Restore über `/api/session/restore` |
| Events | poll only | SSE `/api/events/stream` (Push, `Last-Event-ID`, Heartbeat) aus demselben Hub wie `/api/events` |
| UI-Tests | DOM-Stub-Harness | DOM-Stub **plus** Playwright/Chromium (`tests/ui/chain.spec.mjs`, 7 Specs) |
| Oboe Exclusive | HAL-sim | Orchestrator `/audio/oboe` + C++ `open_oboe_exclusive_stream` + JNI; Exclusive/LowLatency/Float32 |
| UAC2 VID/PID | none | sysfs hotplug + Android `UsbUac2Client` + `/devices/usb` + **PCM-Pipe `ipc_uac2`** |
| BLE codecs | none | LC3plus/LC3/SBC/AAC/aptX negotiate + `BleCodecClient` + `/devices/ble` + **PCM-Pipe `ipc_ble`** |
| Whisper TFLite int8 | filename | `TFL3` weights in `dist/offline-models/` + runtime + `/models/whisper` |
| MiDaS depth | none | int8 weights + HxW depth buffer + `/models/midas` on NeuralLift generate |
| Android JNI | missing | live JNI + WebView shell (Assets synchronisiert mit `web/`, inkl. `src/dsp-core.js`) |
| USB/BT hardware pairing | OS APIs | still needs a device — probe/status live, pairing blocked |
| TFLite Whisper / MiDaS weights | missing | blocked without licensed weights |

## Ehrliche Abgrenzung der neuen Teile

* **Capture ohne Hardware**: Sind weder Soundkarte noch Client-Pipe vorhanden,
  rechnet `dsp.process` weiterhin die deterministische Fixture – aber mit
  `capture.real_capture: false` und `pcm_ring_source: "fixture"`. Nichts wird
  als Live-Audio ausgegeben, das keines ist.
* **LC3plus-Decoder**: Der BLE-Pfad nimmt *decodierte* PCM-Blöcke vom Client
  entgegen (Android `BleCodecClient` decodiert mit dem Plattform-Codec). Ein
  eigener LC3-Decoder ist offline nicht lizenzierbar und wird nicht simuliert.
* **SSE**: HTTP/1.0-Streaming bis zum Disconnect (kein Chunked-Encoding),
  Reconnect übernimmt `EventSource` über `Last-Event-ID`.
* **WASM-Parität**: Gemessen wird der gemeinsame Kern (Limiter, Transient, 808,
  Kaoss-Quad-Stufe). Die Python-Spiegel besitzt zusätzlich Vinyl-Wow/Looper,
  der C++-Kern nicht; die Vektoren halten Vinyl deshalb auf 0.
* **Playwright**: Die Specs laufen in CI mit Chromium. Ist kein Browser
  installiert, meldet `make test-ui` SKIP (Grund wird ausgegeben); die
  Spec-Discovery (`make test-ui-list`) läuft immer.

Vendor Google/Intel **production** `.tflite` nets and a physical Oboe Exclusive track still swap in at the same paths.
