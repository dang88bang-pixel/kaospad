# Vollständige GitHub-Dokumentation: Abarbeitbare TODO-Liste

Projekt: **Korg Kaoss Pad & AI Beatbox Studio // NeuralLift-360 3D Dance Suite**  
Dokumentstand: 2026-09-08  
Branch: `arena/01a081b7-kaospad`  
Ziel: Vollständige, ehrliche Liste aller vorhandenen, simulierten und noch fehlenden Teile, Anbindungen, Attribute, UI-Screens, Tests, Plattform-Builds und Release-Schritte.

---

## 0. Legende

| Status | Bedeutung |
|---|---|
| ✅ DONE | Im Repository vorhanden und lokal ausführbar/getestet. |
| 🧪 SHIM | Ausführbarer Offline-Ersatz/Simulator mit stabiler Schnittstelle, aber noch keine echte Hardware-/KI-Produktion. |
| 🧩 TODO | Muss noch implementiert werden. |
| ⛔ BLOCKED | Benötigt externe Hardware, Vendor-SDK, Modellgewicht, Zertifikat oder OS-spezifische Build-Umgebung. |
| 🔁 REPLACEABLE | Aktueller Shim ist bewusst so gebaut, dass er später durch echte Implementierung ersetzt werden kann. |

---

## 1. Aktueller Repository-Stand

### 1.1 Bereits vorhanden

| Bereich | Pfad | Status |
|---|---|---|
| C++ DSP Core | `android/app/src/main/cpp/` | ✅ DONE |
| CMake Build | `CMakeLists.txt` | ✅ DONE |
| Makefile Hub | `Makefile` | ✅ DONE |
| Localhost IPC Suite | `engines/localhost_ipc_suite.py` | ✅ DONE / 🧪 SHIM |
| Device Matrix USB/Mic/Bluetooth | `engines/device_matrix.py` | ✅ DONE / 🧪 SHIM |
| Offline Reim-Matrix | `engines/whisper_offline/rhyme_matrix.py` | ✅ DONE / 🧪 SHIM |
| NeuralLift HTTP Fallback | `engines/neurallift_360/engine_service.py` | ✅ DONE / 🧪 SHIM |
| Web/PWA UI | `web/` | ✅ DONE |
| Native Bridge PortView UI | `web/index.html`, `web/src/app.js` | ✅ DONE |
| Plug-&-Play Audio UI | `web/index.html`, `web/src/app.js` | ✅ DONE |
| Android Manifest Permissions | `android/app/src/main/AndroidManifest.xml` | ✅ DONE |
| Android Scaffold Build | `android/gradlew` | 🧪 SHIM |
| Desktop Rust Host Scaffold | `desktop/`, `desktop/src-tauri/` | 🧪 SHIM |
| Tests | `tests/` | ✅ DONE |
| CI Workflows | `.github/workflows/` | ✅ DONE / 🧪 teilweise |
| Validation Report | `VALIDATION_REPORT.md` | ✅ DONE |

### 1.2 Lokal erfolgreich getestet

```bash
make test
./scripts/package_web_pwa.sh
python3 engines/device_matrix.py
```

Erwartete Ausgaben:

```text
AudioFlinger direct-pipe simulator: route=127.0.0.1:8081 roundtrip_ms=1.2
Limiter peak=-3.2 dBFS threshold=-3.2 dBFS
Transient kind=1 freq=52 latency_ms=1
zero-cloud localhost IPC gate passed for ports 8080-8085
multi-avatar sync benchmark passed
android USB/mic/bluetooth permissions and features declared
```

---

## 2. Globale Produkt-Reife TODOs

### 2.1 Produktionsreife Zieldefinition

- [ ] Einen finalen Scope für `v5.0.0` festlegen: Demo, Beta, Hardware Preview oder Production.
- [ ] Akzeptanzkriterien pro Plattform definieren: Android, Linux, macOS, Windows, Web/PWA.
- [ ] Mindesthardware definieren:
  - [ ] Android SoC: Snapdragon/Exynos/MediaTek Klassen.
  - [ ] GPU/NPU: Adreno/Mali Mindestprofile.
  - [ ] RAM Mindestgröße.
  - [ ] Audio-Interface Klassen: USB Audio Class 1/2, 48/96 kHz, 24/32 Bit.
  - [ ] Bluetooth Profile: BLE, Classic, LC3/LC3plus, A2DP, HFP Einschränkungen.
- [ ] Performance-Budgets verbindlich festlegen:
  - [ ] Audio Callback Dauer.
  - [ ] DSP CPU Budget.
  - [ ] ML Inferenzzeit.
  - [ ] UI Framezeit.
  - [ ] Speicherlimit pro Plattform.
- [ ] Sicherheitsmodell finalisieren:
  - [ ] Zero-Cloud garantiert.
  - [ ] Kein externer DNS Lookup.
  - [ ] Keine Telemetrie.
  - [ ] Lokale Datenhaltung und Löschfunktion.
- [ ] Lizenzmodell für alle Dependencies prüfen.

---

## 3. Native Audio & Hardware TODOs

## 3.1 Android AudioFlinger / Oboe / AAudio

Aktuell: 🧪 `audio_flinger_hook.cpp` simuliert Direct-Pipe-Latenz.

- [ ] Echte Oboe/AAudio Engine einbauen.
- [ ] Audio Callback mit Float32 Stream implementieren.
- [ ] Input/Output Device Selection via Android `AudioManager` implementieren.
- [ ] USB-C Audio Class Device Discovery implementieren.
- [ ] Hotplug Listener für USB attach/detach implementieren.
- [ ] Sample-Rate Negotiation implementieren:
  - [ ] 44.1 kHz
  - [ ] 48 kHz
  - [ ] 88.2 kHz
  - [ ] 96 kHz
- [ ] Buffer-Size Negotiation implementieren:
  - [ ] 64 Frames
  - [ ] 96 Frames
  - [ ] 128 Frames
  - [ ] 256 Frames fallback
- [ ] Real Roundtrip Measurement via Loopback implementieren.
- [ ] Glitch/Underrun Counter implementieren.
- [ ] Dropout Recovery implementieren.
- [ ] Route Lock UI Status anbinden.
- [ ] Android Foreground Service für stabile Audio-Session implementieren.
- [ ] Low-Latency Flags prüfen:
  - [ ] `android.hardware.audio.low_latency`
  - [ ] `android.hardware.audio.pro`
  - [ ] Performance Mode Low Latency.
- [ ] Input gain / AGC / Noise Suppression Steuerung implementieren.
- [ ] Echo Canceller optional abschaltbar machen.
- [ ] External DAC capabilities anzeigen.
- [ ] Real AudioFlinger Remote Submix prüfen.
- [ ] Rechtliche/OS-Grenzen für What-U-Hear Capture dokumentieren.

### 3.2 USB-C Plug-&-Play

Aktuell: ✅ UI + API vorhanden, 🧪 Device-Status simuliert.

- [ ] Android `UsbManager` Integration.
- [ ] USB Permission Intent Flow implementieren.
- [ ] Device VID/PID lesen.
- [ ] Product/Manufacturer String anzeigen.
- [ ] Supported sample rates anzeigen.
- [ ] Supported bit depths anzeigen.
- [ ] Channel Count In/Out anzeigen.
- [ ] Phantom Power Detection, falls Interface API verfügbar.
- [ ] DAC Clock Lock Status anzeigen.
- [ ] Device reconnect ohne App-Neustart.
- [ ] Fallback auf internes Mic bei USB Disconnect.
- [ ] Persistente bevorzugte USB-Route speichern.
- [ ] Testmatrix mit mindestens 5 USB Interfaces erstellen.

### 3.3 Internes Mikrofon

Aktuell: ✅ UI + API vorhanden, 🧪 Route simuliert.

- [ ] Android Runtime Permission Prompt implementieren.
- [ ] Browser/PWA Mic Permission Flow finalisieren.
- [ ] AudioRecord Input Stream implementieren.
- [ ] Geräte-Mic Auswahl implementieren:
  - [ ] Top Mic
  - [ ] Bottom Mic
  - [ ] Beamforming Mic, falls verfügbar
- [ ] AGC Status anzeigen.
- [ ] Noise Suppression Status anzeigen.
- [ ] Feedback Notch Filter implementieren.
- [ ] Club-Mode Input Protection implementieren.
- [ ] Live Metering für Input Peak/RMS.
- [ ] Mic Calibration Screen ergänzen.

### 3.4 Bluetooth Client / BLE Mic

Aktuell: ✅ UI + API vorhanden, 🧪 Bluetooth-Status simuliert.

- [ ] Android `BluetoothManager` Integration.
- [ ] Android 12+ `BLUETOOTH_CONNECT` Runtime Flow.
- [ ] Android 12+ `BLUETOOTH_SCAN` Runtime Flow.
- [ ] Legacy BLE Location Flow bis SDK 30 dokumentieren.
- [ ] BLE Device Scan UI.
- [ ] Pairing UI.
- [ ] Connected Device Status.
- [ ] RSSI Anzeige.
- [ ] Codec Anzeige:
  - [ ] SBC
  - [ ] AAC
  - [ ] aptX, falls verfügbar
  - [ ] LC3/LC3plus, falls verfügbar
- [ ] Realistische Latenzmessung pro Codec.
- [ ] Jitter Buffer implementieren.
- [ ] Compensation Slider für Bluetooth Delay.
- [ ] Reconnect Strategy.
- [ ] Fallback bei Disconnect.
- [ ] Testmatrix mit DJI Mic, Rode Wireless GO, Hollyland etc.

### 3.5 Desktop Audio Backends

Aktuell: 🧪 Rust Host Scaffold.

- [ ] Linux ALSA Backend implementieren.
- [ ] Linux PipeWire Backend implementieren.
- [ ] Linux JACK Backend optional.
- [ ] macOS CoreAudio Backend implementieren.
- [ ] Windows WASAPI Backend implementieren.
- [ ] Windows ASIO Backend implementieren.
- [ ] ASIO SDK Lizenz-/Download-Prozess dokumentieren.
- [ ] Multi-device aggregate device handling.
- [ ] Latency calibration pro OS.
- [ ] Device hotplug Events pro OS.
- [ ] Audio route UI mit Desktop Backend verbinden.

---

## 4. DSP Engine TODOs

### 4.1 Brickwall Limiter

Aktuell: ✅ ausführbar und getestet.

- [ ] Oversampling für true peak limiting ergänzen.
- [ ] Lookahead optional ergänzen.
- [ ] Release/Attack Parameter exposed machen.
- [ ] Soft-knee Kurve messbar dokumentieren.
- [ ] LUFS/RMS Metering ergänzen.
- [ ] SIMD Optimierung prüfen:
  - [ ] NEON Android/ARM
  - [ ] SSE/AVX Desktop
- [ ] Fuzz Tests mit Random Audio ergänzen.

### 4.2 Transient Splitter / Mouth-Bass → 808

Aktuell: ✅ deterministischer Basistest, 🧪 vereinfachte Erkennung.

- [ ] FFTW3 oder KissFFT Pipeline implementieren.
- [ ] Multi-band transient detection:
  - [ ] 20–90 Hz Kick/Mouth Bass
  - [ ] 3–8 kHz Snare/Clap
  - [ ] 8–16 kHz Hi-Hat/Roll
- [ ] Pitch detection für Mouth-Bass.
- [ ] Envelope follower implementieren.
- [ ] PLL/BPM Sync implementieren.
- [ ] Quantisierung 1/16 und 1/32.
- [ ] 808 Oscillator als modulare Voice.
- [ ] Decay, Glide, Saturation UI Parameter.
- [ ] Sample-Layer Snare/Clap Engine.
- [ ] Hi-hat noise synth.
- [ ] Preset-System:
  - [ ] Boom-Bap
  - [ ] Drill
  - [ ] Acid Berlin
  - [ ] Lo-Fi
- [ ] Audio fixture tests ergänzen.
- [ ] Hardware latency tests ergänzen.

### 4.3 Kaoss Quad / KP3+

Aktuell: ✅ Grund-State + Freeze, 🧪 noch keine volle Emulation.

- [ ] Vollständige 4-Engine DSP Chain.
- [ ] XY Pad Mapping pro Engine.
- [ ] Freeze pro Engine persistent machen.
- [ ] Looper Engine implementieren.
- [ ] Reverse Loop implementieren.
- [ ] Slicer mit 8 Slices implementieren.
- [ ] Grain Pitch implementieren.
- [ ] Vinyl Break Physikmodell.
- [ ] Tape Scratch.
- [ ] Flanger Jet.
- [ ] Ducking Compressor.
- [ ] Moog-style Ladder Filter.
- [ ] Vowel/Formant Morph A-E-I-O-U.
- [ ] Tape Echo mit Wow/Flutter.
- [ ] Ping-Pong Delay.
- [ ] Dark Hall Reverb.
- [ ] KP3+ 8x8 LED Matrix UI.
- [ ] Sample Banks A/B/C/D.
- [ ] Resampling Engine.
- [ ] Master FX Release Slider.
- [ ] MIDI Mapping optional.

---

## 5. AI / ML / Offline Intelligence TODOs

### 5.1 Whisper Offline

Aktuell: 🧪 HTTP Shim + Reim-Matrix vorhanden.

- [ ] Echtes `whisper.tflite` Modell integrieren.
- [ ] Quantisierte Modellvarianten definieren:
  - [ ] tiny int8
  - [ ] base int8 optional
  - [ ] multilingual vs german-optimized
- [ ] TensorFlow Lite Runtime integrieren.
- [ ] NNAPI Delegate optional.
- [ ] Metal/CoreML Delegate für macOS optional.
- [ ] ONNX Runtime Alternative prüfen.
- [ ] Streaming Audio Buffer 500 ms implementieren.
- [ ] VAD implementieren.
- [ ] Partial Transcript Events.
- [ ] Word timestamps.
- [ ] Offline Language Detection.
- [ ] Profanity/Slang handling ohne Cloud.
- [ ] Performance Benchmark pro Plattform.

### 5.2 SQLite Reim-Matrix

Aktuell: ✅ kleine ausführbare DB.

- [ ] Vollständige 85.000+ Einträge importieren.
- [ ] Phonetischen Index erzeugen.
- [ ] Deutsch/Berlin Slang Datenmodell.
- [ ] Assonanzsuche.
- [ ] Kadenz/Silbenzahl berechnen.
- [ ] Flow-Abbruch-Erkennung >600 ms.
- [ ] Vorschlagsranking.
- [ ] Session-Learning lokal speichern.
- [ ] Datenschutz: Export/Löschen aller lokalen Lernprofile.

### 5.3 NeuralLift-360

Aktuell: 🧪 Default Avatar Fallback API.

- [ ] Bildimport Pipeline implementieren.
- [ ] Depth Estimation:
  - [ ] MiDaS
  - [ ] ZoeDepth
  - [ ] mobile quantized variants
- [ ] Normal Estimation.
- [ ] Mesh Reconstruction.
- [ ] Texture Projection.
- [ ] GLB/GLTF Export.
- [ ] LOD 0 45k tris.
- [ ] LOD 1 18k tris.
- [ ] Auto-Rigging 24 Bones.
- [ ] Blendshape Support optional.
- [ ] Fallback Avatar Library.
- [ ] GPU timeout recovery.
- [ ] Memory budget enforcement.
- [ ] Inference benchmark target 1.8s prüfen.

### 5.4 MediaPipe / MoPac Dance Learner

Aktuell: Ordner vorhanden, 🧩 Pipeline fehlt.

- [ ] MediaPipe Pose Integration.
- [ ] 33-Punkt Skeleton Stream.
- [ ] Kamera Permission Flow.
- [ ] Live MoCap Preview.
- [ ] BVH Export.
- [ ] BVH Import.
- [ ] Video Import.
- [ ] Move Segmentation.
- [ ] Transient Marker Binding.
- [ ] Move Profile Slots A/B/C/D.
- [ ] Gesture Cleanup/Smoothing.
- [ ] Foot lock correction.
- [ ] Retargeting auf 24-Bone Avatar.

---

## 6. Localhost IPC / Daemon TODOs

Aktuell: ✅ alle Ports ausführbar als Shims.

### 6.1 Port `8080` Master Orchestrator

- [x] Health Endpoint.
- [x] Native Bridge PortView Endpoint.
- [x] Device Status/Select Endpoint.
- [ ] Persistente Session State Machine.
- [ ] Profile laden/speichern.
- [ ] Watchdog für alle Daemons.
- [ ] Prozess-Restart Strategie.
- [ ] Log Stream Endpoint.
- [ ] Config Export/Import.

### 6.2 Port `8081` Audio Loopback

- [x] TCP PCM Shim.
- [ ] Real Float32 PCM Stream.
- [ ] Ringbuffer Shared Memory.
- [ ] Backpressure handling.
- [ ] Clock drift correction.
- [ ] Route negotiation.

### 6.3 Port `8082` NeuralLift Engine

- [x] Health/Default Mesh Endpoint.
- [ ] Upload Foto Endpoint.
- [ ] Job Queue.
- [ ] Progress Events.
- [ ] GLB Binary Response.
- [ ] GPU/CPU Fallback.

### 6.4 Port `8083` Avatar Orchestrator

- [x] TCP JSONL Skeleton Shim.
- [ ] WebSocket Server.
- [ ] FlatBuffers Schema.
- [ ] 60 FPS skeletal transform stream.
- [ ] Multi-avatar state replication.
- [ ] Cypher/Unisono/Chaos mode engine.

### 6.5 Port `8084` DSP Transient Bridge

- [x] UDP JSON Shim.
- [ ] 64-byte binary datagram format.
- [ ] BPM event stream.
- [ ] Kick/Snare/Hat event stream.
- [ ] Clock sync with audio engine.
- [ ] Packet loss stats.

### 6.6 Port `8085` Offline Whisper

- [x] Transcribe Shim.
- [x] Rhymes Endpoint.
- [ ] Streaming IPC pipe.
- [ ] Real TFLite inference.
- [ ] Word-level alignment.
- [ ] Reim ranking.

---

## 7. UI / UX TODOs

### 7.1 Bereits vorhandene UI

- [x] Hero Screen.
- [x] Kaoss XY Pad.
- [x] Native Bridge PortView.
- [x] Plug-&-Play Audio I/O Matrix.
- [x] Permission Cards.
- [x] PWA Manifest.
- [x] Service Worker Offline Cache.

### 7.2 Generelle UI Attribute

- [ ] Design Tokens zentralisieren:
  - [ ] `#ff7a00` Amber Glow
  - [ ] `#00f5d4` Neon Cyan
  - [ ] `#111318` Dark Shell
  - [ ] Panel colors
  - [ ] Status colors
- [ ] Accessibility prüfen:
  - [ ] Kontrast
  - [ ] Focus states
  - [ ] Screen reader labels
  - [ ] Large touch targets
- [ ] Mobile 390px Layout finalisieren.
- [ ] Tablet Layout.
- [ ] Desktop 3-panel Layout.
- [ ] Offline Error States.
- [ ] No-device fallback states.
- [ ] Permission denied recovery UI.
- [ ] Bluetooth pairing failure UI.
- [ ] USB disconnect toast.
- [ ] Club/Night Mode.

### 7.3 Screen-Katalog TODO

| Screen | Name | Status | TODO |
|---|---|---:|---|
| SCREEN_4 | Tanz-Anlern-Modus | 🧩 TODO | Camera/MoCap UI, Profile Slots A-D |
| SCREEN_6 | Server Daemon Matrix | ✅ teilweise | Live logs, restart buttons, PID monitor |
| SCREEN_7 | Multi-Avatar Party | 🧩 TODO | 3D stage, 8 avatar slots, modes |
| SCREEN_9 | Clean Cypher HUD | 🧩 TODO | Gesture overlays |
| SCREEN_10 | Funky Live 3D Avatar Cypher | 🧩 TODO | NeuralLift UI + bottom nav |
| SCREEN_13 | One-Touch Cypher USB-C Sync | 🧩 TODO | Big recording capsules + USB status |
| SCREEN_14 | Mobile USB-C Audio & Mic Matrix | ✅ teilweise | Real device scan and calibration |
| SCREEN_15 | Desktop Master Studio | 🧩 TODO | 3-panel console |
| SCREEN_16 | YouTube Auto Detection | 🧩 TODO | Browser/source detection limits |
| SCREEN_17 | Modular Theme FX | 🧩 TODO | Preset browser |
| SCREEN_18 | Responsive Studio | 🧩 TODO | All form factors |
| SCREEN_19 | One-Touch Cypher & Auto-Track | 🧩 TODO | Ergonomic performance mode |
| SCREEN_21 | Neural Cypher Lab & Track Forge | 🧩 TODO | Style/stem tools |
| SCREEN_22 | Endless Reel Recursion Studio | 🧩 TODO | Tape reel UI and overdubs |
| SCREEN_23 | Cyber-Transkriptor & Track Vault | 🧩 TODO | Teleprompter, colored rhymes, export |
| SCREEN_28 | AI Beatbox Session & Musik Agent | 🧩 TODO | Freeform lanes A/B |
| SCREEN_29 | Kaoss Pad Quad FX Studio | ✅ teilweise | Full 4 FX engines, LED matrix |

### 7.4 Plug-&-Play UI spezifisch

- [x] Select für USB/Mic/Bluetooth.
- [x] Statuskarten.
- [x] Permissionkarten.
- [x] Latency/Route Anzeige.
- [ ] Real hardware icon states.
- [ ] Device detail drawer.
- [ ] Input gain slider.
- [ ] Monitor mix slider.
- [ ] Bluetooth delay compensation UI.
- [ ] USB sample-rate override.
- [ ] Mic AGC toggle.
- [ ] Noise suppression toggle.
- [ ] Test tone / loopback calibration button.

---

## 8. Plattform-Build TODOs

### 8.1 Android

Aktuell: 🧪 Scaffold-Artefakte.

- [ ] Offiziellen Gradle Wrapper erzeugen und committen.
- [ ] Kotlin/Java MainActivity vollständig.
- [ ] Native Library laden.
- [ ] JNI Bridge für DSP.
- [ ] JNI Bridge für Device Matrix.
- [ ] Runtime Permissions UI.
- [ ] Foreground Audio Service.
- [ ] Release Signing konfigurieren.
- [ ] AAB Build real validieren.
- [ ] APK Build auf Gerät installieren.
- [ ] Hardware loopback test auf Gerät.

### 8.2 Linux

- [ ] Tauri oder alternative Desktop Shell finalisieren.
- [ ] AppImage Builder integrieren.
- [ ] Debian Package Builder.
- [ ] ALSA/PipeWire real testen.
- [ ] udev rules für USB Audio prüfen.
- [ ] Desktop file, icon, MIME types.

### 8.3 macOS

- [ ] Universal Binary Build.
- [ ] CoreAudio Backend.
- [ ] Metal/Accelerate optional.
- [ ] `.dmg` Builder.
- [ ] Codesigning.
- [ ] Notarization.
- [ ] Microphone entitlement.
- [ ] Hardened Runtime.

### 8.4 Windows

- [ ] WASAPI Backend.
- [ ] ASIO Backend.
- [ ] MSI Builder.
- [ ] Portable ZIP.
- [ ] Driver detection.
- [ ] Code signing.
- [ ] Windows audio permission/onboarding.

### 8.5 Web/PWA

- [x] Offline Cache.
- [x] PWA Manifest.
- [ ] Install prompt UI.
- [ ] WebAudio Input Capture.
- [ ] WebMIDI optional.
- [ ] WASM DSP Build.
- [ ] SharedArrayBuffer/Cross-Origin Isolation prüfen.
- [ ] Browser storage quota handling.

---

## 9. CI/CD TODOs

Aktuell: Workflows vorhanden, aber viele Schritte bauen Shims oder benötigen Runner/Assets.

- [ ] GitHub Actions Syntax mit `actionlint` prüfen.
- [ ] CMake/Ninja Linux Build real im Runner prüfen.
- [ ] Android Gradle Build echt machen.
- [ ] macOS Build auf `macos-latest` validieren.
- [ ] Windows Build auf `windows-latest` validieren.
- [ ] Artifact names finalisieren.
- [ ] Checksums erzeugen.
- [ ] SBOM erzeugen.
- [ ] Release Notes Template.
- [ ] Version aus Tag automatisch in App übernehmen.
- [ ] Signing Secrets definieren:
  - [ ] Android keystore
  - [ ] Apple Developer ID
  - [ ] Windows code signing cert
- [ ] Secretless offline fallback dokumentieren.
- [ ] Release workflow nur auf Tags oder manuell.
- [ ] PR checks für Tests.
- [ ] Nightly benchmark workflow.

---

## 10. Test TODOs

### 10.1 Vorhandene Tests

- [x] Audio latency simulator.
- [x] Limiter test.
- [x] Transient splitter test.
- [x] Localhost IPC test ports `8080–8085`.
- [x] Multi-avatar synthetic FPS benchmark.
- [x] Android permission manifest test.

### 10.2 Noch fehlende Tests

- [ ] Real hardware roundtrip latency test.
- [ ] USB hotplug integration test.
- [ ] Bluetooth pairing integration test.
- [ ] Mic permission denial test.
- [ ] Audio underrun stress test.
- [ ] Long-running audio soak test.
- [ ] NeuralLift image-to-GLB golden test.
- [ ] Whisper fixture transcription test.
- [ ] Rhyme ranking test with 85k DB.
- [ ] Web UI Playwright tests.
- [ ] Accessibility test.
- [ ] PWA offline install test.
- [ ] CI release dry-run test.
- [ ] Zero external network enforcement with socket monkeypatch.
- [ ] Fuzz tests for malformed IPC payloads.

---

## 11. Daten, Modelle, Assets TODOs

- [ ] Echtes Whisper Modell beschaffen und lizenzieren.
- [ ] Model checksum manifest.
- [ ] NeuralLift/Depth Modelle beschaffen und lizenzieren.
- [ ] Motion Diffusion/EDGE Modelle beschaffen und lizenzieren.
- [ ] MediaPipe assets prüfen.
- [ ] 808/Snare/Hat Sample Library erstellen oder lizenzieren.
- [ ] KP3+/Kaoss inspirierte, aber rechtlich eigene Presets erstellen.
- [ ] Icons erstellen.
- [ ] App screenshots.
- [ ] Store metadata.
- [ ] Demo project/session assets.
- [ ] Datenschutztexte.
- [ ] Offline Manual.

---

## 12. Security / Privacy TODOs

- [ ] Netzwerk-Policy pro Plattform implementieren.
- [ ] Android Network Security Config: external cleartext blockieren.
- [ ] Firewall/Test gegen externe Sockets.
- [ ] Keine Analytics SDKs.
- [ ] Keine Crash Cloud SDKs ohne explizite Opt-in Alternative.
- [ ] Lokale Logs rotieren.
- [ ] Sensitive Audio automatisch lokal verschlüsseln optional.
- [ ] Löschfunktion für Sessions.
- [ ] Export-Funktion für lokale Daten.
- [ ] Permission rationale UI.
- [ ] Security Review der IPC Endpoints.
- [ ] Bind nur `127.0.0.1` validieren.
- [ ] CSRF/Origin Schutz für localhost HTTP prüfen.

---

## 13. Abhängigkeiten / Lizenz TODOs

- [ ] FFTW3 vs KissFFT Lizenzentscheidung.
- [ ] TFLite Lizenz prüfen.
- [ ] ONNX Runtime Lizenz prüfen.
- [ ] MediaPipe Lizenz prüfen.
- [ ] Three.js Lizenz prüfen.
- [ ] Tauri Lizenz und Bundle-Lizenzen.
- [ ] ASIO SDK Lizenz manuell prüfen.
- [ ] Audio Samples lizenzieren.
- [ ] ML Model Licenses inventarisieren.
- [ ] SBOM automatisieren.

---

## 14. Release-Artefakt TODOs

Zielnamen aus Spezifikation:

- [ ] `KaossBeatboxStudio-v5.0.0-Universal-Signed.apk`
- [ ] `KaossBeatboxStudio-v5.0.0-Universal.aab`
- [ ] `KaossBeatboxStudio-v5.0.0-x86_64.AppImage`
- [ ] `KaossBeatboxStudio-v5.0.0-Universal.dmg`
- [ ] `KaossBeatboxStudio-v5.0.0-Setup.msi`
- [x] `KaossBeatboxStudio-WebAssembly-Offline.zip` als PWA ZIP Scaffold
- [ ] SHA256SUMS Datei.
- [ ] GPG Signaturen optional.
- [ ] Release Notes.
- [ ] Installationsanleitung pro OS.
- [ ] Known Issues Liste.

---

## 15. Priorisierte nächste Arbeitspakete

### Phase A – Ehrliche Beta lauffähig machen

1. [ ] Android echten Gradle Wrapper hinzufügen.
2. [ ] Android JNI Bridge zwischen UI und C++ DSP bauen.
3. [ ] Android Runtime Permissions UI für Mic/Bluetooth/USB implementieren.
4. [ ] AudioRecord/AAudio Input wirklich an DSP anschließen.
5. [ ] WebAudio/WASM Fallback für Browser implementieren.
6. [ ] UI Screens SCREEN_14, SCREEN_29, SCREEN_6 fertigstellen.
7. [ ] Release Workflow ohne Platzhalter-Artefakte validieren.

### Phase B – Audio-Produktion

1. [ ] Oboe/AAudio Low-Latency Engine.
2. [ ] USB Hotplug und Device Capabilities.
3. [ ] FFT Transient Splitter.
4. [ ] Vollständige Kaoss Quad FX.
5. [ ] Loop/Sampler Engine.
6. [ ] Hardware Loopback Tests.

### Phase C – AI / Avatar

1. [ ] Whisper TFLite Streaming.
2. [ ] Reim-Matrix importieren.
3. [ ] MediaPipe Pose.
4. [ ] BVH Import/Export.
5. [ ] NeuralLift image-to-avatar pipeline.
6. [ ] Three.js 3D Avatar Stage.

### Phase D – Produktionsrelease

1. [ ] Signing pro Plattform.
2. [ ] Native Installer pro OS.
3. [ ] Real Device Test Matrix.
4. [ ] SBOM + checksums.
5. [ ] GitHub Release mit echten Artefakten.
6. [ ] Store-/Manual-Dokumentation.

---

## 16. Definition of Done für „vollständig fertig“

Das Projekt gilt erst dann als vollständig produktionsreif, wenn alle folgenden Punkte erfüllt sind:

- [ ] Echte Audioaufnahme funktioniert auf Android per USB-C, internem Mic und Bluetooth.
- [ ] Eingangsquelle ist zur Laufzeit ohne Neustart umschaltbar.
- [ ] Statusanzeige zeigt echte Geräte- und Permissionzustände.
- [ ] DSP läuft im echten Audio Callback stabil ohne Dropouts.
- [ ] Latenz wurde auf echter Hardware gemessen und dokumentiert.
- [ ] Whisper transkribiert echte Live-Audioeingaben offline.
- [ ] Reim-Matrix enthält Produktionsdatenbestand.
- [ ] NeuralLift erzeugt aus Foto echte GLB Avatare offline.
- [ ] MediaPipe/MoCap/BVH Pipeline funktioniert offline.
- [ ] Alle UI-Screens aus dem Katalog sind implementiert.
- [ ] Android, Linux, macOS, Windows und Web Artefakte sind echte installierbare Builds.
- [ ] CI/CD erzeugt und veröffentlicht echte signierte Release-Artefakte.
- [ ] Zero-Cloud wurde automatisiert und manuell validiert.
- [ ] Datenschutz-, Lizenz- und Sicherheitsprüfung abgeschlossen.

