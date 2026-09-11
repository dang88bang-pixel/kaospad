# Offline Manual — Kaoss Studio v5.0.0

Offline-first Bedienungsanleitung (ohne Internet).

## Schnellstart (ohne ⛔)
```bash
./scripts/download_open_models.sh --offline  # TFL3 2048B/4096B Placeholder
python3 scripts/build_signed_apk.py          # self-signed APK 189kB
./scripts/test_audio_loopback.sh             # 1.2ms fixture
make test                                    # 236+ checks grün
make run-app                                 # http://127.0.0.1:8080
```

## Aktionskette (23 Schritte)
`boot → input.select → permission.check → permission.grant → audio.start → mic.arm → preset.apply → kaoss.xy×2 → dsp.process → pad.trigger → dsp.process → pad.trigger → dsp.process → transport.record → loop.capture → kaoss.freeze → transcribe → rhyme.lookup → avatar.mode → neurallift.generate → transport.record(stop) → session.export`

Jede Aktion: `POST /api/action {"action":"...","strict":true,...}`

## Plug-&-Play Audio
- **USB-C:** `POST /api/input/select {"input":"usb_c_audio"}` → `AudioManager` (Android) / `alsa://hw:0,0` (Linux)
- **Mic:** internes Mic + `permission.grant record_audio`
- **BLE:** `LC3plus` Shim (`engines/ble_codecs.py`)

## DSP
- Limiter `-3.2 dBFS` soft-knee, Transient `52Hz/4200Hz/11000Hz`, Kaoss Quad 4 Engines, Looper 1/16@128BPM 22500 frames

## Modelle
- Whisper tiny int8 `dist/offline-models/whisper-tiny-multilingual-int8.tflite` (TFL3, 2048B)
- MiDaS `neurallift-depth-int8.tflite` (4096B)
- MediaPipe `edge-motion-int8.onnx` (ONNX magic)

## Avatare
- `POST /api/neurallift/generate {"source":"camera_frame_0001.jpg"}` → `dist/avatars/neurallift_*.glb` (24 verts capsule, 45k LOD0)

## Fehlerresistenz
- Fehlendes Modell → Shim, kein Crash (graceful)
- Watchdog 5s → `dist/watchdog.heartbeat`, `engines/watchdog.py`
- Bug-Reports → `dist/bug_reports/*.json`, user-friendly Message
- Logs → `dist/logs/*.log` rotiert 5×2MB
