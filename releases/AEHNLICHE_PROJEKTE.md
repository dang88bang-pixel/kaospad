# Ähnliche Projekte — was dort bereits vollständig getestet ist

Vergleich 2026-09-10. Nur **softwareseitig getestete** Parts, die wir hier übernehmen oder bewusst nicht 1:1 kopieren.

| Projekt | Getestet vollständig | Bei uns |
|---|---|---|
| [PWA Soundboard](https://github.com/digitalcolony/soundboard-pwa) | Offline SW-Cache, Pad-Trigger, Manifest-Install | SW + 16 Pads **LIVE**; Install-Prompt UI dünn |
| [offline-plugin PWA](https://github.com/NekR/offline-plugin-pwa) | Service-Worker Offline-First | `sw.js` cached HTML/JS inkl. action-chain |
| [openDAW](https://github.com/andremichelle/openDAW) | WebAudio Graph, Timeline (AGPL) | WebAudio Filter/Delay/Limiter **LIVE**; keine DAW-Timeline |
| Typische Kaoss/KP3+ JS-Demos | XY → Filter/Delay | XY → `kaoss.xy` **und** WebAudio **LIVE** |
| Android WebView+JSBridge Samples | `addJavascriptInterface`, Permissions | MainActivity **LIVE** (Cloud-APK) |
| Session-Reducer (Redux-artig) | ordered actions + blocked | 19 Aktionen + Guards **LIVE** getestet (236 Checks) |

**Nicht** in Open-Source-Pendants produktionsfertig (und hier ebenfalls HAL): Oboe Exclusive auf Gerät, USB-UAC2 ISO, BLE-LC3plus, Whisper-TFLite-Gewichte, Play-AAB.

**Konsequenz:** Fehlende *Software*-Parts (Replay-UI, funktionale End-to-End-Ausführung jeder Aktion, I/O-Fehleranzeige) werden ergänzt. Hardware/ML bleiben Verträge.
