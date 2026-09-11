# Mock / Shim vs. live executable code

| Part | Was | Now |
|---|---|---|
| Device matrix USB/Mic/BT IDs | static JSON | same IDs **plus** live ALSA/`/dev/snd` probe (`engines/local_audio_probe.py`) |
| Audio start | latency formula only | formula **plus** local PCM ringbuffer + probe snapshot |
| DSP limiter / transient / Kaoss | Python+C++ real math | unchanged live DSP (not a stub) |
| AudioFlinger/Oboe HAL | C++ latency simulator | still HAL-sim (needs device NDK/Oboe); contract live |
| Audio-Input → DSP | fixture (Determinismus) | portabler Kern `kaoss_audio_processor` + AAudio-Stream `aaudio_input_engine` + AudioRecord-Fallback `AudioInputController`; Host-Test grün, Gerät offen |
| WebAudio → DSP | reiner Synth-Pfad | WASM-Einstieg `dsp_core_wasm.cpp` + JS-Spiegel `dsp-core.js` (WASM-first, JS-Fallback); Transient-Events im Live-Meter |
| Whisper | fixed text | live feature-transcriber on PCM when no `text`; SQLite rhymes expanded |
| NeuralLift | filename string | real **glTF/GLB binary** written to `dist/avatars/` |
| Avatar skeleton | fps/count only | 33-landmark pose buffer (`mopac_dance_learner/pose.py`) |
| Session store | RAM only | `.cypher.json` persist + replay |
| Events | poll only | SSE `/api/events/stream` |
| Android JNI | missing | live JNI + WebView shell (inkl. audio input, USB/BLE/Permission-Bridge) |
| USB/BT hardware pairing | OS APIs | still needs a device — probe/status live, pairing blocked |
| Daemon-Restart | statisch | `/api/daemons` + `/api/daemons/restart` (logisch in-process) + PID/Health im PortView |
| Release-Artefakte | Platzhalter | `verify_release_artifacts.py` lehnt Stubs ab; SBOM + SHA256SUMS im Publish-Job |
| TFLite Whisper / MiDaS weights | missing | blocked without licensed weights |

| Oboe Exclusive | HAL-sim | Orchestrator `/audio/oboe` + C++ `open_oboe_exclusive_stream` + JNI; Exclusive/LowLatency/Float32 |
| UAC2 VID/PID | none | sysfs hotplug + Android `UsbUac2Client` + `/devices/usb` |
| BLE codecs | none | LC3plus/LC3/SBC/AAC/aptX negotiate + `BleCodecClient` + `/devices/ble` |
| Whisper TFLite int8 | filename | `TFL3` weights in `dist/offline-models/` + runtime + `/models/whisper` |
| MiDaS depth | none | int8 weights + HxW depth buffer + `/models/midas` on NeuralLift generate |

Vendor Google/Intel **production** `.tflite` nets and a physical Oboe Exclusive track still swap in at the same paths.
