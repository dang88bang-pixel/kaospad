# Mock / Shim vs. live executable code

| Part | Was | Now |
|---|---|---|
| Device matrix USB/Mic/BT IDs | static JSON | same IDs **plus** live ALSA/`/dev/snd` probe (`engines/local_audio_probe.py`) |
| Audio start | latency formula only | formula **plus** local PCM ringbuffer + probe snapshot |
| DSP limiter / transient / Kaoss | Python+C++ real math | unchanged live DSP (not a stub) |
| AudioFlinger/Oboe HAL | C++ latency simulator | still HAL-sim (needs device NDK/Oboe); contract live |
| Whisper | fixed text | live feature-transcriber on PCM when no `text`; SQLite rhymes expanded |
| NeuralLift | filename string | real **glTF/GLB binary** written to `dist/avatars/` |
| Avatar skeleton | fps/count only | 33-landmark pose buffer (`mopac_dance_learner/pose.py`) |
| Session store | RAM only | `.cypher.json` persist + replay |
| Events | poll only | SSE `/api/events/stream` |
| Android JNI | missing | live JNI + WebView shell |
| USB/BT hardware pairing | OS APIs | still needs a device — probe/status live, pairing blocked |
| TFLite Whisper / MiDaS weights | missing | blocked without licensed weights |

Hardware-only: Oboe exclusive stream, UAC2 hotplug VID/PID, BLE codecs, ASIO SDK.
