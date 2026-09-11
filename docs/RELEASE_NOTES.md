# Release Notes — v5.0.0-offline-one-app (2026-09-11)

Branch `arena/01a090e3-kaospad` — Zero-Cloud PWA + One-App + Desktop

## Highlights
- **Eine Anwendung** (`app.py` + `engines/session_engine.py`): 19 Aktionen, 23 Schritte, `BLOCKED` Guards, `.cypher` Export + SHA256, SSE `/api/events/stream`
- **DSP Parität** (C++/Python/JS): Limiter -3.2 dBFS, Transient 52/4200/11000 Hz, Kaoss Quad 4 Engines, Looper 22500 frames @128BPM
- **IPC 8080-8085** real Sockets + Protobuf Fallback, Retry 3×5s + Circuit-Breaker
- **Offline Modelle**: Whisper tiny TFL3 2048B, MiDaS 4096B, ONNX 1024B — `download_open_models.sh --offline`
- **Web PWA** (`web/sw.js` v12, manifest, action-chain.js)
- **Tests** 236+89+107+19+39+13+28 = grün, `make test` <30s

## Artefakte
- `KaossBeatboxStudio-v5.0.0-Universal-Signed.apk` (189649B, v1+v2, OpenSSL, self-signed, sideload via `adb install`)
- `KaossBeatboxStudio-WebAssembly-Offline.zip` (PWA, wasm_built flag)
- `KaossBeatboxStudio-v5.0.0-x86_64.AppImage` (scaffold 4.5kB, real via `desktop/target/release/kaoss-desktop`)
- `KaossBeatboxStudio-v5.0.0-Universal.dmg` (scaffold 4.5kB, real via macOS runner)
- `KaossBeatboxStudio-v5.0.0-Setup.msi` (scaffold, real via Inno Setup on Windows)
- `SHA256SUMS.txt` + `sbom.json` (SPDX)

## Alternative Lösungswege (alle ⛔ umgehbar)
Siehe `docs/ALTERNATIVE_LOESUNGSWEGE.md` — 14 Kategorien, `quickstart_workaround.sh` 4 Steps

## Known Issues
Siehe `docs/KNOWN_ISSUES.md`

## Upgrade
`git pull && ./scripts/download_open_models.sh --offline && make test`
