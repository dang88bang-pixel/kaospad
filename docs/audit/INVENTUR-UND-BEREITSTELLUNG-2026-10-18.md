# Inventur & Bereitstellungsbericht – Kaoss Pad / AI Beatbox Studio

Stand: **2026-10-18** · Branch: `arena/5dc65cd7-kaospad` · Basis-Commit: `2f2d068` (identisch mit `main`)
**Umsetzung Stufe A:** Commit `b799959` (Code) auf demselben Branch; Status je Maßnahme siehe §6 und Abschnitt „Stand nach Stufe A“.
Ergänzende Datei-Inventur (alle 179 getrackten Dateien): [`INVENTUR-2026-10-18.csv`](INVENTUR-2026-10-18.csv)

---

## 1. Gesamturteil

| Frage | Antwort |
|---|---|
| Ist das Repo heute **100 % bereitstellbar**? | **Nein.** Die lokale Offline-App läuft, aber die Release-Pipeline ist defekt und keine der Release-Artefakte für macOS, Windows und Linux ist ein echtes Produkt. |
| Erfüllt das Repo seine eigene Definition of Done (`docs/FULL_IMPLEMENTATION_TODO.md` §16)? | **Nein.** Alle 14 Punkte sind offen. |
| Fortschritt laut TODO-Checkboxen | **78 erledigt, 11 teilweise, 389 offen** → ca. **16 %** (eigene Zählung per Regex über `docs/FULL_IMPLEMENTATION_TODO.md`). |
| Was ist **sofort** bereitstellbar? | Die **lokale One-App** (Python-Server + PWA) als Beta/Preview. Die Web-Befunde P1-3 bis P1-6 und P1-10 sind seit `b799959` behoben (Stufe A). |
| Was **blockiert** eine echte Auslieferung? | (1) kaputte CI-Datei, (2) Scaffold-Artefakte für Desktop/macOS/Windows, (3) Signierschlüssel nicht im Repo, (4) rote Haupt-CI. |

**Wichtig zu „100 %“:** Vollständige Bereitstellung im Sinne der TODO-DoD ist in dieser Sandbox **nicht erreichbar**. Es fehlen Hardware-Tests (USB/BLE/Mikrofon), lizenzierte ML-Gewichte (Whisper-TFLite, MiDaS, MediaPipe), Store-/Notarisierungs-Zertifikate und Signierschlüssel. Ein realistisches Ziel ist daher „alle Artefakte der Release-Matrix werden gebaut, verifiziert und veröffentlicht; Shims sind klar gekennzeichnet“ (Abschnitt 6).

---

## 2. Methodik und Nachweise

Alles Folgende wurde **selbst ausgeführt**, nicht aus den bestehenden Berichten übernommen.

| Prüfung | Ergebnis |
|---|---|
| `make test` (lokal, vollständig) | **Exit 0**, ~80 s, 33 Zeilen mit Ergebnis-Marker. **Aber:** 5 SKIP-Meldungen in 4 Gates (Playwright-UI `test-ui-list` + `test-ui`, `wasmtime`-Parität, `pocketsphinx`-Dekodierlauf, `androguard`-Referenzprüfung). Ein grüner Exit-Code heißt hier also **nicht** „alles geprüft“. |
| Frischer Klon des Commits, `test-web-contract`, `test-action-chain-ui`, `test-web-ui-chain` | Alle grün mit **Node 20.19.0** (CI-Version) und **Node 22.22.3** (Sandbox). 89 bzw. 112 UI-Checks. |
| CI-Status `main` (GitHub API) | Run `34730881743` (Audio DSP Benchmark) **rot**: Job *Offline Action & Interaction Chain* schlägt im Schritt *Web/UI contract + DOM-stub harness* fehl. Run `34730881387` (Multi-Platform Release) **rot ohne einen einzigen Job** → Workflow wird nicht geparst. |
| YAML-Parse aller Workflows (PyYAML) | `multiplatform-ci-cd.yml` → `ScannerError … line 107`. Die anderen drei Workflows parsen. |
| Playwright-Discovery (`npm ci` im Klon) | 7 Specs in `chain.spec.mjs` gefunden. Browser-Download (`cdn.playwright.dev`) in der Sandbox blockiert. Auf GitHub lief der Job *Playwright Browser UI* auf `main` **grün**. |
| One-App Smoke-Test (`python3 app.py --host 127.0.0.1 --port 8080`) | 200 für `/health`, `/api/status`, `/api/runtime`, `/api/state`, `/api/actions` (20 POST-Routen, 19 Aktionen), `/api/wasm`, `/api/daemons`, `/devices/status`, `/permissions/check`, `/native-bridge/ports`, `/api/audio/capture`, `/api/sessions`, `/mesh/default`, `/rhymes`, `/api/presets`, `/`. Fremder `Origin` auf POST → **403**. `POST /api/chain/run` (strict) → **23 Schritte**. Antwort-Header `X-Kaoss-Zero-Cloud: true`. |
| Watchdog-Verhalten im Leerlauf (zweiter Serverstart, 25 s ohne Anfrage) | Alle 6 Rollen: `restarts: 3`, `state: degraded`. Siehe P1-10. |
| Release-Artefakte im HEAD | Committete APK ist ein **Offline-Stub**: keine `lib/*/libkaoss_native.so`, Stub-DEX. Der Release-Guard `verify_release_artifacts.py` würde sie ablehnen. |
| Gradle-Wrapper | `gradle-wrapper.jar` vorhanden (43 kB, enthält `GradleWrapperMain.class`). SHA-256 **nicht gegen die offizielle Quelle geprüft** (`services.gradle.org` nicht erreichbar). |
| Externe Hosts im Laufzeitcode (`web/`, `android/…/assets`, `engines/`, `app.py`) | **Keine** (Zero-Cloud-Versprechen hier eingehalten). |
| Tooling in der Sandbox | Vorhanden: Python 3.11, Node 20/22, g++ 12, make, gh. **Fehlend:** cmake, JDK, Gradle, Android NDK, Emscripten, Docker, Chromium-Browser, `flatc`. Daher sind Android-, Desktop- und macOS-/Windows-Builds hier **nicht prüfbar**. |

### Während der Prüfung verursachte Nebenwirkung (korrigiert)

`make test` (Target `signed-apk`) hat **drei getrackte Dateien überschrieben**: `android/signing/kaoss-release-cert.pem`, `releases/…Universal-Signed.apk` und `…apk.sha256`. Grund: der Schlüssel `kaoss-release-key.pem` liegt nicht im Repo, also erzeugt das Skript bei jedem Lauf ein neues Schlüsselpaar. Diese Änderungen wurden per `git checkout` zurückgesetzt; die vom Lauf erzeugten, ignorierten Build-Artefakte wurden entfernt. **Das Repo enthält nach dieser Prüfung nur die beiden neuen Dokumente.**

---

## 3. Inventur nach Bereichen

Legende: **LIVE** lauffähig und durch Tests abgedeckt · **SHIM** gleiche Schnittstelle, Ersatzlogik · **SCAFFOLD/PLATZHALTER** erzeugt nur Dummy-Dateien · **BLOCKED** braucht externe Ressourcen · **UNGEPRÜFT** in der Sandbox nicht ausführbar.

| Bereich | Umfang (getrackt) | Status | Nachweis / Anmerkung |
|---|---|---|---|
| **One-App-Server** `app.py` + `engines/` (Session-Engine, DSP-Spiegel, Capture, SSE, Session-Store, Resilience, Watchdog) | `app.py` + 26 Python-Module in `engines/` (Python gesamt inkl. Tests/Skripte: ~16.200 Zeilen) | **LIVE** (Beta) | `make test` grün; Smoke-Test grün. Mehrere Engines bleiben SHIM (Whisper, MiDaS, MediaPipe, USB/BLE-Pairing). |
| **Web/PWA** `web/` (UI, Kettenmodul, WebAudio, WASM-Lader) | 10 Dateien, ~2.600 Zeilen JS | **LIVE mit Befunden** | Siehe P1-4 bis P1-6 (Manifest, Service Worker, absolute Pfade). |
| **C++-DSP-Kern** `android/app/src/main/cpp` + `tests/*.cpp` | 18 C/C++-Dateien, ~1.700 Zeilen | **LIVE** (Host) / **UNGEPRÜFT** (Gerät) | `make test-native-dsp-latency` grün. Oboe wird nicht eingebunden → Exclusive-Pfad ist SHIM. |
| **WASM-Build** `web/wasm`, `scripts/build_wasm.sh` | 1 C++-Datei | **LIVE** via Zig | `dist/wasm/kaoss_dsp.wasm` (1,27 MB) gebaut; Emscripten-Glue nicht erzeugt. 4-Wege-Parität (274 Checks) grün; **wasmtime-Lauf übersprungen** lokal. |
| **Android** Gradle/Kotlin/JNI/Manifest | 40 Dateien | **UNGEPRÜFT** | Kein JDK/NDK in Sandbox. Manifest- und JNI-Signatur-Verträge grün (`permission_manifest_test`, `native_audio_bridge_test`). Ein Build auf GitHub ist nie für den aktuellen Stand belegt. |
| **Android-Assets** `android/app/src/main/assets/www` | 9 Dateien, Kopie von `web/` | **LIVE**, aber Drift-Risiko | Inhaltlich identisch zu `web/src`; CI kopiert neu. |
| **Desktop** `desktop/`, `desktop/src-tauri/` | 8 Dateien, ~144 Zeilen Rust | **SCAFFOLD** | Reine Routing-Matrix ohne Audio-Backend. Keine Tauri-Abhängigkeit. Zwei Crates mit divergierendem Code. |
| **Modelle/ML** `engines/whisper_offline`, `neurallift_360`, `mopac_dance_learner` | 11 Dateien | **SHIM / PLATZHALTER / BLOCKED** | Gewichte lizenzpflichtig; `download_weights.py` schreibt Platzhalter. `pocketsphinx`-Pfad nur mit Installation. |
| **Tests** `tests/` | 39 Dateien | **LIVE** | 36 Testskripte im Makefile, 33 Zeilen mit Ergebnis-Marker in `make test`. 4 Gates mit SKIP (siehe Abschnitt 2). |
| **CI/CD** `.github/workflows/` | 4 Workflows | **BLOCKER / rot** | Siehe P0-1 und P0-2. |
| **Build-Skripte** `scripts/` | 15 Dateien | **SCAFFOLD** (3 Stück) | `create_universal_dmg.sh`, `build_windows_installer.ps1`, `build_appimage.sh` erzeugen Textdateien mit der Endung `.dmg`/`.msi`/`.AppImage`. |
| **Signing** `android/signing/` | Cert + lokale Schlüssel | **PROBLEM** | Siehe P0-4. |
| **Release-Artefakte** `releases/` | 9 Dateien, ~250 kB Binärdaten | **PLATZHALTER** | Committete APK ist ein Stub (P0-3). |
| **Dokumentation** | 16 Dateien (Markdown/CSV) | **Teils veraltet** | Siehe Abschnitt 5. |
| **Backups** `backups/` | 9 Dateien | **HYGIENE** | Kopien alter Stände im Arbeitsbaum; gehören in die Git-Historie. |

**Code-Umfang gesamt:** rund 25.000 Zeilen (Python ~16.200, JS/MJS ~6.900 inkl. Tests, C/C++ ~1.700, Kotlin ~440, Rust ~144).

---

## 4. Befunde nach Priorität

> Statusangaben je Befund siehe §6 (Stufe A) und Abschnitt „Stand nach Stufe A“. Die Beschreibungen unten geben den Befund vor der Umsetzung wieder.

### P0 – blockiert jede Auslieferung

**P0-1: Release-Workflow ist syntaktisch kaputt (0 Jobs).**
`.github/workflows/multiplatform-ci-cd.yml` Zeile 107 und 231: Step-Namen `Guard: real ART …` und `Guard: verify real artifacts …` enthalten `: ` ohne Quotes. YAML lehnt das ab, GitHub startet 0 Jobs. Dadurch startet **kein** Tag-Release (`v*.*.*`).
*Fix (lokal verifiziert, in einer Kopie geparst, alle 7 Jobs erkannt):* beide Namen in `"…"` setzen.

**P0-2: Haupt-CI auf `main` ist rot.**
Run `34730881743`: Job *Offline Action & Interaction Chain* scheitert im Schritt *Web/UI contract + DOM-stub harness*. Lokal reproduziert sich das nicht (frischer Klon, Node 20 und 22, alle drei Targets grün). Die Job-Logs sind aus der Sandbox nicht abrufbar (Blob-Storage blockiert). **Nächster Schritt:** Log im GitHub-UI öffnen, Schritt *Web/UI contract* ansehen. Vermutung: CI-spezifische Umgebung (Port-Belegung, Zeitfenster der Latenz-Asserts), nicht belegt.

**P0-3: Release-Artefakte für macOS, Windows, Linux sind Dummy-Dateien.**
- `scripts/create_universal_dmg.sh:4` schreibt `Kaoss macOS Universal DMG scaffold` als `.dmg`.
- `scripts/build_windows_installer.ps1:2` schreibt `Kaoss Windows MSI scaffold` als `.msi`.
- `scripts/build_appimage.sh:7` schreibt Text als `.AppImage`, sonst wird das Rust-Binary kopiert (kein AppImage-Format).
- Der Guard `scripts/verify_release_artifacts.py:29-30` verlangt mindestens 256 kB für DMG und MSI; die Dummy-Dateien haben wenige Bytes → der Publish-Job **kann nie grün werden**, selbst nach P0-1.
- Die committete APK `releases/…Universal-Signed.apk` ist ein Offline-Stub (kein `libkaoss_native.so`, Stub-DEX) und trägt trotzdem den Release-Namen. **Nicht publizieren.**

**P0-4: Signierschlüssel fehlt im Repo, und Builds überschreiben das Zertifikat.**
- `android/signing/kaoss-release-cert.pem` (gültig bis 2036, CN „Kaoss Beatbox Studio Offline“) hat **keinen Privatschlüssel** im Repo oder in der Historie (`*-key.pem` ist ignoriert, `git log --all` leer).
- `scripts/build_signed_apk.py` erzeugt bei fehlendem Schlüssel ein neues Paar und überschreibt Cert, APK und `.sha256` (passiert bei `make test`, siehe Abschnitt 2).
- In CI ohne Secret wird ein **Wegwerf-Keystore mit Passwort `android`** erzeugt (`multiplatform-ci-cd.yml:82-99`, `android-signed-apk.yml`, `app/build.gradle.kts:30`). Die Signatur kann später kein Update derselben App sein.
*Entscheidung nötig:* Ist der Originalschlüssel noch vorhanden? Falls nein, muss ein neuer Schlüssel erzeugt, als GitHub-Secret hinterlegt und das Update-Problem für Nutzer dokumentiert werden.

### P1 – vor einer Beta nötig

**P1-1: `make test` meldet Erfolg trotz übersprungener Gates.** Die SKIP-Pfade in `scripts/run_ui_tests.sh:15` und in den Python-Tests liefern Exit 0. CI erzwingt nur die WASM-Cross-Runtime (`audio-dsp-benchmark.yml`), nicht die UI- oder Dekodierläufe lokal. *Empfehlung:* SKIP-Anzahl am Ende ausgeben und in CI als Fehler werten.

**P1-2: Android-Pipeline nie für den aktuellen Stand belegt.**
- `android-signed-apk.yml:6-7` triggert nur auf den alten Branch `arena/01a085c8-kaospad` → läuft für `main` und diesen Branch nie.
- `multiplatform-ci-cd.yml` `build-android` hat keinen erfolgreichen Lauf auf dem aktuellen Code (siehe P0-1).
- Der Gradle-Build mit CMake/NDK ist in der Sandbox nicht prüfbar.

**P1-3: Mehrere Workflow-Trigger zeigen auf alte Branches.** `audio-dsp-benchmark.yml:6` nennt `arena/01a081b7-kaospad`; das Muster `arena/*` ist nicht abgedeckt. *Empfehlung:* Trigger auf `main` und Pull-Requests vereinheitlichen.

**P1-4: PWA ist nicht installierbar.** `web/manifest.webmanifest` hat `"icons": []`, im Repo liegen keine Icons, und `index.html:8` setzt nur ein leeres `data:`-Favicon. Chrome verlangt 192- und 512-px-Icons für die Installation.

**P1-5: Service Worker ohne Versionspflege.** `web/sw.js:1` nutzt `kaoss-offline-v13-…` fest. Die Strategie ist *cache-first* ohne Revalidierung und ohne `activate`-Cleanup. Nutzer sehen nach einem Deploy also alte UI-Dateien, bis der Cache-Name manuell erhöht wird. Das WASM-Modul wird nicht gecacht.

**P1-6: Absolute Pfade widersprechen der Dokumentation.** `README.md:86` behauptet „All browser calls use relative paths“. Tatsächlich nutzt `web/src/app.js` 21-mal absolute Pfade (`fetch('/api/runtime')` …), und `web/src/dsp-core.js:18` setzt `WASM_URL = '/wasm/kaoss_dsp.wasm'`.
Folge: Die Android-APK lädt `file:///android_asset/www/index.html` (`MainActivity.kt:48`). Dort führen alle API-Aufrufe ins Leere, und die App fällt auf den Offline-Dispatcher zurück. Das WASM-Modul ist nicht im Paket, also rechnet die APK mit dem JS-Spiegel. Der Pfad ist technisch lauffähig, aber nicht so, wie die Doku ihn beschreibt.

**P1-7: Python-Abhängigkeiten nicht festgelegt.** Es gibt keine `requirements*.txt` oder `pyproject.toml`. `flatbuffers`, `wasmtime`, `ziglang`, `pocketsphinx`, `androguard` werden nur ad hoc in CI oder über Fehlermeldungen installiert. `desktop/` hat kein `Cargo.lock`. Nur `package-lock.json` (Playwright) ist vorhanden.

**P1-8: Desktop hat zwei divergierende Crates.** `desktop/src-tauri/` heißt „Tauri“, hat aber keine Tauri-Abhängigkeit. `audio_host.rs` existiert in beiden Varianten mit unterschiedlichem Inhalt; `main.rs` ist identisch. Zur Auslieferung als Desktop-App fehlen das echte Audio-Backend und ein Installer.

**P1-10: Watchdog meldet im Leerlauf Fehlalarme.** `app.py` füttert den Watchdog nur über `send_json` (Heartbeat bei jeder HTTP-Antwort, `app.py` ~Z.320). Ohne Anfragen werden alle sechs Rollen nach 5 s als „neugestartet“ gezählt und nach 3 Versuchen als `degraded` markiert. Gemessen: `GET /api/watchdog` → `state: degraded`, `restarts: 3` für jede Rolle, obwohl kein Dienst ausgefallen war (Test mit 25 s Leerlauf, Log `dist/logs/one-app.log`). Der Restart setzt keinen Session-Zustand zurück (`restart_daemon`, Z.194–215); das Problem ist das falsche Health-Signal in PortView und Logs. *Empfehlung:* Heartbeat-Thread im Server, nicht pro Antwort.

**P1-9: Keine Notarisierung/Signierung für macOS und Windows**, kein MSI-Builder, kein ASIO-SDK-Prozess (`setup_asio_sdk.ps1` schreibt nur eine README-Datei). Siehe TODO §8.3/8.4.

### P2 – Hygiene und Wartbarkeit

- **P2-1:** `docs/audit/INVENTAR.csv` deckt nur 113 von 179 Dateien ab (66 fehlen, u. a. `engines/resilience.py`, `watchdog.py`, `kpcm_flatbuffers.py`). Die neue Inventur liegt als `INVENTUR-2026-10-18.csv` bei.
- **P2-2:** `backups/` (9 Dateien) und `releases/KaossBeatboxStudio-v5.0.0-PWA.zip` gehören nicht in den Arbeitsbaum.
- **P2-3:** `android/app/src/main/assets/www` ist eine committete Kopie von `web/`; das kann auseinanderlaufen. Eine Build-Synchronisation (wie in CI) reicht, die Kopie könnte entfallen.
- **P2-4:** `Dockerfile.offline-build` ist nicht geprüft (kein Docker in der Sandbox).
- **P2-5:** `android/gradlew`-Jar: SHA-256 gegen die offizielle Gradle-Distribution prüfen (sobald Zugang besteht).
- **P2-6:** Android-Release hat `isMinifyEnabled = false` und keinen Foreground-Service (TODO §8.1).

---

## 5. Dokumentations-Widersprüche (zum Korrigieren)

| Dokument | Aussage | Realität heute |
|---|---|---|
| `README.md:86` | „All browser calls use relative paths“ | **Stufe A erledigt:** keine absoluten Browser-Pfade mehr in `web/` (geprüft per grep: fetch, EventSource, serviceWorker, href/src). |
| `REPORT.md` / `VALIDATION_REPORT.md` | CI „4/4 Jobs grün“ (Run 34722066403) | Aktueller `main`-CI ist rot (P0-2) |
| `releases/INTEGRATION_STATUS.md` | „Android Cloud-APK Build grün“ | Bezieht sich auf alten Run und alten Branch; für aktuellen Stand nicht belegt |
| `docs/FULL_IMPLEMENTATION_TODO.md` §8.1 | Gradle-Wrapper-Jar „offline nicht erzeugbar“ | Jar liegt im Repo (43 kB, `GradleWrapperMain.class`) |
| `docs/FULL_IMPLEMENTATION_TODO.md` Kopf | Stand 2026-09-12, Branch `arena/01a08bf1` | Aktuell 2026-10-18; Branch heute `arena/5dc65cd7` |
| `Makefile` / `make test` | „Alle Gates grün“ (impliziert) | **Stufe A:** `make test-strict` ergänzt (rot bei SKIP). `make test` bleibt Exit 0; lokal werden noch 4 Gates übersprungen (androguard, pocketsphinx, flatc, Playwright-Chromium). |
| `releases/README.md` | „Signierte APK, Schlüssel offline“ | Schlüssel nicht im Repo, Cert ohne Privatschlüssel (P0-4). **Stufe A:** Signierskript überschreibt das Cert nicht mehr; ohne Schlüssel nur Wegwerf-Signatur in `dist/`. Die Doku selbst ist noch nicht angepasst. |
| `docs/audit/INVENTAR.csv` | Vollständige Dateiinventur | 66 von 179 Dateien fehlen (P2-1). Ersetzt durch `INVENTUR-2026-10-18.csv` (186 Dateien nach Stufe A). |

---

## 6. Weg zu „100 % Bereitstellung“

Die Stufen bauen aufeinander auf. Die Spalte „Wer“ zeigt, was ich im Repo umsetzen kann und was Ihre Entscheidung oder Ihr Zugang braucht.

### Stufe A – Beta der lokalen App (Web/PWA + Server)

Freigabe durch Sie: „Stufe A komplett“ (scope `all_a`). Status nach Umsetzung in Commit `b799959`:

| # | Maßnahme | Wer | Aufwand | Status |
|---|---|---|---|---|
| A1 | P0-1: zwei Step-Namen quoten | Ich (verifiziert) | minimal | **erledigt** (YAML parst, 7 Jobs) |
| A2 | P0-2: Log des fehlgeschlagenen Schritts sichten, Ursache beheben | Sie (GitHub-UI) + ich | klein–mittel | **offen** – Logs waren nicht abrufbar; bitte Log von Run `34730881743`, Schritt „Web/UI contract“, teilen |
| A3 | P1-4 bis P1-6: Icons, Service-Worker-Versionierung, relative Pfade | Ich | mittel | **erledigt** (Icons 192/512, `sw.js` v14 netzwerk-zuerst, 29 relative Pfade, Android-Assets synchronisiert) |
| A4 | P1-1: SKIPs als Fehler oder mindestens sichtbar machen | Ich | klein | **erledigt** als `make test-strict`; `make test` bleibt tolerant |
| A5 | P1-7: `requirements.txt` und `Cargo.lock` anlegen | Ich | klein | **erledigt** als `requirements-dev.txt` (gepinnt) und zwei `Cargo.lock` (ohne Abhängigkeiten) |
| A6 | Doku korrigieren (Abschnitt 5) | Ich | klein | **erledigt** für README, Makefile, Inventar; `releases/README.md` und TODO-Kopf weiterhin offen |
| A7 | P1-10: Watchdog-Heartbeat vom Antwortpfad lösen (Hintergrund-Thread), Fehlalarme im Leerlauf beseitigen | Ich | klein | **erledigt** (25 s Leerlauf: `restarts` 0, vorher 3 je Rolle) |

**Zusätzlich über den Plan hinaus, aus P0-4:** `scripts/build_signed_apk.py` überschreibt ein vorhandenes Zertifikat nicht mehr, wenn der Schlüssel fehlt. Stattdessen Wegwerf-Signatur nach `dist/signed-ephemeral/` mit Warnung. `releases/` bleibt unberührt. Die Tests `signed_apk_test.py` und `dex_builder_test.py` wählen den APK-Pfad entsprechend.

### Stufe B – Releases mit echten Artefakten (Android, Linux, macOS, Windows, Web)

| # | Maßnahme | Wer | Aufwand |
|---|---|---|---|
| B1 | Release-Keystore erzeugen, als Secrets `KAOSS_KEYSTORE_BASE64`, `KAOSS_KEYSTORE_PASSWORD`, `KAOSS_KEY_ALIAS`, `KAOSS_KEY_PASSWORD` hinterlegen; Default-Passwort-Fallback in Publish-Jobs entfernen | **Sie** (Schlüsselentscheidung, P0-4) | klein, aber Konsequenzen für Updates |
| B2 | Scaffold-Skripte (`create_universal_dmg.sh`, `build_windows_installer.ps1`, `build_appimage.sh`) durch echte Builds ersetzen (`cargo`, `hdiutil`/`create-dmg`, WiX/`cargo-wix`, AppImage-Tooling) | Ich (Code) + CI-Läufe | groß |
| B3 | Android: `assembleRelease` auf aktuellem Stand grün bekommen; `android-signed-apk.yml` auf `main` umstellen | Ich (Code) + CI | mittel |
| B4 | Stub-APK und Dummy-Artefakte aus `releases/` entfernen | Ich (nach Ihrer Freigabe) | klein |
| B5 | Apple Developer ID, Notarisierung, Windows-Codesigning-Zertifikat beschaffen | **Sie** | extern |
| B6 | Keine Stub-Artefakte in Releases: Guard in CI als Pflichtschritt | Ich | klein |

### Stufe C – Produktion (TODO §16)

Echte Hardware-Messungen (USB-Interfaces, BLE-Mikrofone, Latenz), lizenzierte Modelle (Whisper-TFLite, MiDaS, MediaPipe), Sample-Lizenzen, Datenschutz- und Lizenzprüfung (TODO §12/§13), Store-Metadaten. **Diese Punkte liegen außerhalb dieser Sandbox und sind mit Ihrer Hardware bzw. Lizenzbeschaffung zu erledigen.**

---

## 7. Nächste Schritte

1. **Sie (A2):** Log des Schritts *Web/UI contract* im Run `34730881743` im GitHub-UI ansehen und die Fehlermeldung teilen. Ohne Log kann ich die Ursache des roten Main-CI nicht belegen.
2. **Sie (B1, Schlüssel):** Keystore-Datei zum Release-Cert `android/signing/kaoss-release-cert.pem` als Secret hinterlegen. Befehl: `base64 -w0 <keystore> | gh secret set KAOSS_KEYSTORE_BASE64`. Zusätzlich `KAOSS_KEYSTORE_PASSWORD`, `KAOSS_KEY_ALIAS`, `KAOSS_KEY_PASSWORD` setzen. Danach entferne ich das Fallback-Passwort `android` aus CI und `build.gradle.kts`.
3. **Ich (nach Ihrer Meldung):** Fallback-Passwort entfernen und den signierten Release-Pfad über den Secret-Lauf belegen.
4. **Ich:** Stufe B2/B3 (echte Desktop-, Android- und Web-Artefakte) auf diesem Branch angehen. Stufe B5 (Apple-, Windows-Zertifikate) bleibt bei Ihnen.
5. **Hinweis:** Stufe C (Hardware, Modelle, Lizenzen, Store) liegt außerhalb dieser Sandbox.

## Stand nach Stufe A (Commit `b799959`)

**Verifiziert:**

| Prüfung | Ergebnis |
|---|---|
| `make test` (lokal, mit `requirements-dev.txt` in venv) | Exit 0. wasmtime-Gate läuft jetzt real (177 Checks, vorher SKIP). `releases/` unverändert. |
| Verbleibende Übersprünge lokal | androguard, pocketsphinx, flatc (Kreuzdecodierung), Playwright-Chromium (CDN in der Sandbox gesperrt). |
| `make test-strict` im frischen Klon | Rot, listet die übersprungenen Gates (gewollt). |
| Frischer Klon von `origin/arena/5dc65cd7-kaospad` (`b799959`): `test-web-contract`, `test-action-chain-ui`, `test-web-ui-chain` | Grün mit Node 22.22.3 und Node 20.19.0. |
| UI-Harness (DOM-Stub, relative URLs) | 112 UI-Checks, 23 Chain-Schritte, Limiter sicher. |
| `app.py` Smoke (Port 8082) | 200 für `/`, `manifest.webmanifest`, `sw.js`, `icons/*.png`, `src/app.js`, `src/dsp-core.js`, `/api/status`, `/api/wasm`, `/rhymes?word=…`, `/devices/status`, `/native-bridge/ports`. |
| Watchdog im Leerlauf (25 s ohne Anfrage) | Alle 6 Rollen `healthy`, `restarts: 0`. Vorher `degraded` mit `restarts: 3`. |
| Android-Assets | Synchron mit `web/` (einzige Unterschiede: README, package.json, wasm, wie vorher). |

**Nicht verifiziert (ehrlich benannt):**

- **Playwright-Specs (`make test-ui`)** sind nicht gelaufen, weil Chromium in der Sandbox nicht lädt. Die Pfadumstellung in `app.js` betrifft aber genau diese Spezifikationen. Das Playwright-Job auf `main` war vorher grün. Bitte den CI-Lauf auf dem Branch prüfen.
- **Ob die Änderungen den roten Main-CI-Schritt „Web/UI contract“ beheben,** ist unbekannt. Lokal war er vor und nach den Änderungen grün, die Logs sind nicht abrufbar (A2).
- **Keine echten Android-, Desktop- oder Web-Release-Builds** in Stufe A. Das ist Stufe B.
- **Cargo.lock** wurde nicht mit `cargo` gegengeprüft (Rust ist in der Sandbox nicht installiert).

---

## 8. Anhang: Reproduktion

```bash
# Gesamtsuite (dauert ~80 s; Exit 0 bedeutet NICHT, dass alle Gates liefen)
make test

# Ohne Build-Nebenwirkungen auf getrackte Dateien: vorher/nachher prüfen
git status --short

# CI-Simulation in frischem Klon (Node 20 wie in CI)
rm -rf /tmp/ci-sim && git clone -q . /tmp/ci-sim && cd /tmp/ci-sim
make test-web-contract && make test-action-chain-ui && make test-web-ui-chain

# Workflow-Syntax (ohne actionlint-Binary, Python + PyYAML)
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]; print('ok')"

# Haupt-CI-Status (GitHub CLI)
gh run list --limit 10
gh api repos/dang88bang-pixel/kaospad/actions/runs/34730881387/jobs --jq '.jobs | length'   # 0 ⇒ Parsefehler
```
