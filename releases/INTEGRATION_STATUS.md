# Integrations- und Fertigstellungsstand

Stand: **2026-09-10**, Branch `arena/01a085c8-kaospad` @ `4fa93ab`.  
Legende: **LIVE** ausführbar · **SHIM** gleiche API, Ersatzlogik · **CLOUD** nur auf GitHub-Runner · **OFFEN** · **BLOCKED** Hardware/Gewichte/TLS.

## Gesamturteil

| Schicht | Reife | Bemerkung |
|---|---|---|
| **One-App Python + PWA** | **Beta-lauffähig** | `app.py` + `web/` + 19-Aktionskette, Zero-Cloud, Tests |
| **Android Cloud-APK** | **Build grün** | GHA `assembleRelease` [Run 34466007825](https://github.com/dang88bang-pixel/kaospad/actions/runs/34466007825) |
| **Android Offline-APK** | **Archiv, nicht ART** | 112 984 B, Stub-DEX, kein `.so` |
| **Nativ Audio (Oboe/USB/BLE)** | **HAL-Vertrag, kein Gerät** | JNI/C++/Kotlin da, Exclusive-Track braucht Hardware |
| **Whisper / NeuralLift / MoPac** | **SHIM + Stub-Gewichte** | keine lizenzierten Produktionsnetze |
| **Desktop (Linux/macOS/Win)** | **Scaffold** | Rust-Host, keine echten Installer |
| **Produktions-DoD (TODO §16)** | **nicht erfüllt** | echte Capture, echte Modelle, alle Screens, alle OS-Artefakte |

Geschätzte Fertigstellung gegen das interne DoD: **~35–45 %** (Software-Kette hoch, Hardware/ML/Store niedrig).

---

## 1. Integrationskarte (was mit was spricht)

```
UI (web/index.html + app.js + audio-engine.js)
    │  fetch relativ / JS-Bridge
    ├─► app.py  127.0.0.1  /api/action /state /events /runtime
    │       └─ session_engine (19 Aktionen, Guards, BLOCKED)
    │              ├─ dsp_chain.py  ↔  C++ DSP (Limiter, Transient, Quad, 808)
    │              ├─ device_matrix + local_audio_probe + usb_uac2 + ble_codecs
    │              ├─ whisper_offline (transcriber + rhyme SQLite + tflite stub)
    │              └─ neurallift_360 (glb.py + midas stub) + mopac pose
    │
    ├─► Android WebView MainActivity
    │       KaossJsBridge → KaossNative JNI → libkaoss_native.so (Cloud-APK)
    │       UsbUac2Client / BleCodecClient  (OS-APIs, pairing OFFEN)
    │
    └─► Localhost-IPC 8080–8085  (Health-Shims, kein echter PCM/WS)
```

Parität Browser-Reducer ↔ Server: `tests/web_functional_contract_test.py` (19 Aktionen, 23 Schritte, 6 Ports).

---

## 2. Modulstatus

### LIVE (getestet / gebaut)

| Modul | Nachweis |
|---|---|
| Session-Engine + DSP-Spiegel | `make demo-chain` / 236 HTTP-Checks |
| PWA UI (Pad, Quad, Kette, Mic/808 WebAudio) | `web/` + HTTP :8080 |
| Zero-Cloud Origin/Socket-Guard | `zero_cloud_socket_guard_test.py` |
| Session-Persistenz `.cypher.json` + SSE | `session_persist_replay_test.py` |
| Android Manifest Permissions | `permission_manifest_test.py` |
| JNI + WebView + Runtime-Permissions | `MainActivity.kt`, `kaoss_jni.cpp` |
| Cloud `assembleRelease` | GHA success, Artifact `KaossBeatboxStudio-v5.0.0-cloud-signed` |
| C++ Limiter/Transient/Quad Tests | `make test-native-dsp-latency` |

### SHIM (API fest, Kern ersetzt)

| Modul | Ersatz | Swap-in |
|---|---|---|
| Oboe Exclusive | Formel + `open_oboe_exclusive_stream` | echte AAudio Exclusive |
| USB-UAC2 | sysfs/JSON + `UsbUac2Client` | UsbManager + Permission-Intent |
| BLE Codecs | LC3plus-Negotiation-JSON | BluetoothGatt + Hardware-Codec |
| Whisper | Feature-Transcriber + `TFL3` Stub | lizenziertes `whisper.tflite` |
| MiDaS / NeuralLift | int8-Buffer + prozedurales GLB | Vendor-Weights |
| AudioFlinger What-U-Hear | 1.2 ms Simulator | OS-Loopback (rechtlich begrenzt) |
| Ports 8081–8085 | TCP/UDP JSON Health | PCM mmap / WS 60 FPS / TFLite |
| `android/gradlew` lokal | Platzhalter-Skript | offizielles wrapper.jar |

### CLOUD-only

JDK 17, SDK 35, NDK 26, Gradle 8.7 — lokal TLS-blockiert (`SSL_ERROR_SYSCALL`). PyPI `jdk4py` = **JRE ohne javac**.

### OFFEN / BLOCKED

- Echte Mic/USB/BLE-Capture im DSP-Callback  
- WASM-DSP, Playwright, Replay-from-`.cypher`  
- UI-Screens 4, 7, 9, 10, 13, 15–23, 28 (Katalog)  
- Desktop AppImage/DMG/MSI  
- Play AAB + Upload-Key  
- 85k-Reim-DB, echte Samples, Store-Assets, SBOM  

---

## 3. APK-Zwei-Wege (wichtig)

| Artefakt | Größe / Ort | Launch? | Inhalt |
|---|---|---|---|
| Offline-Signer | `releases/…-Universal-Signed.apk` ~113 KB | **nein** (DEX 412 B) | PWA + Quellen + v1/v2 |
| **Cloud Gradle** | GitHub Artifact | **ja, erwartet** | Kotlin DEX, `libkaoss_native.so`, assets/www, CI-Keystore |

Gerätetest der Cloud-APK ist **noch nicht** in dieser Box erfolgt.

---

## 4. Testgatter

Vorhanden: Native-DSP, IPC, Permissions, One-App, Action-Chain 236, UI-Harness 89+93, Zero-Cloud, HAL-Orchestrator, Signed-APK-Zip, Session-Replay, Attribute-Chain.

Fehlt: Hardware-Roundtrip, USB-Hotplug, BLE-Pairing, Soak/Underrun, Whisper-Golden, Playwright, PWA-Install.

---

## 5. Definition of Done vs. jetzt

Aus `docs/FULL_IMPLEMENTATION_TODO.md` §16 — **0/14 Produktionshaken geschlossen**.  
Nächste sinnvolle Schritte:

1. Cloud-APK auf Gerät sideloaden und Launch/WebView/Mic prüfen.  
2. Optional Secret `KAOSS_KEYSTORE_BASE64`.  
3. AudioRecord/AAudio an `dsp.process` hängen.  
4. Desktop-Installer und fehlende Screens nur nach Scope-Schnitt (Beta vs. Studio).
