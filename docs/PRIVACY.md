# Datenschutz / Privacy — Kaoss Studio v5.0.0

**Stand:** 2026-09-11 — Branch `arena/01a090e3-kaospad` — **Zero-Cloud garantiert**

## Grundsatz
Kaoss Studio ist **offline-first** und **zero-cloud**: keine Telemetrie, kein externer DNS Lookup, keine Cloud-SDKs. Alle Audio-Transkripte, Reim-Suchen, 3D-Avatare und Sessions bleiben lokal auf dem Gerät.

## Lokale Datenhaltung
| Daten | Pfad | Format | Löschbar |
|---|---|---|---|
| Sessions (Aktionskette + State) | `dist/sessions/*.cypher.json` + `dist/state_machine.sqlite3` | JSON + SQLite WAL | `rm dist/sessions/*` oder UI „Chain Reset“ |
| Reim-Matrix + Lernprofile | `dist/offline-rhymes.sqlite3` | SQLite | `DELETE FROM rhymes` oder DB löschen |
| Avatare / Depth | `dist/avatars/*.glb`, `*.depth` | GLB + float32 | `rm dist/avatars/*` |
| Audio-Modelle (Whisper/MiDaS) | `dist/offline-models/*.tflite` | TFLite int8 (TFL3 shim) | `rm dist/offline-models/*` |
| Logs / Bug-Reports | `dist/logs/*.log`, `dist/bug_reports/*.json` | Text/JSON (rotiert 5×2MB) | `rm -rf dist/logs dist/bug_reports` |
| Audio-Ringbuffer | nur RAM (`KaossQuadChain.pcm_ring`, max 4096 events) | RAM | App-Neustart |

## Löschfunktion (UI + API)
- UI: **Chain Reset** (`POST /api/chain/reset` → `chain.reset`) löscht Kette + temporären State.
- API: `DELETE /api/session/latest` (geplant) — Alternative: `rm dist/sessions/latest.cypher.json`.
- Export/Löschen aller lokalen Lernprofile: `python3 engines/whisper_offline/rhyme_matrix.py --db dist/offline-rhymes.sqlite3` → `DELETE`.

## Keine externen Verbindungen
- `tests/zero_cloud_socket_guard_test.py` monkeypatcht `socket` und blockt externe Hosts (2 Versuche geblockt, 1 Loopback erlaubt).
- `app.py` + `engines/localhost_ipc_suite.py` binden nur `127.0.0.1` (Validierung via `zero_cloud_socket_guard`).
- `Network Security Config` (`android/app/src/main/res/xml/network_security_config.xml`) blockt cleartext extern.

## Berechtigungen
- Android: `RECORD_AUDIO`, `BLUETOOTH_CONNECT/SCAN`, `USB` nur bei `input.select` → `permission.check` → `permission.grant`.
- Web PWA: `navigator.mediaDevices.getUserMedia` nur nach `arm-mic` Klick + Browser-Prompt.
- Keine stillen Hintergrund-Aufnahmen: `mic.arm` erforderlich, `audio.start` + `permission.granted`.

## Verschlüsselung (optional)
- Sensitive Audio kann lokal optional verschlüsselt werden (geplant: `dist/sessions/*.cypher.enc` via `age`/`openssl enc -aes-256-gcm` — Shim vorhanden via `engines/session_engine.py` Export).
- Master-Key bleibt lokal; kein Cloud-Key-Management.

## Kontakt
Zero-Cloud Verifikation: `make test-zero-cloud`, `VALIDATION_REPORT.md` § Zero-Cloud, `docs/MOCK_VS_LIVE.md`.
