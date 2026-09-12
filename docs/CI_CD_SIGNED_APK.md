# CI/CD: signierte Android-APK aus GitHub Actions

Stand: 2026-09-12 · Workflow: [`.github/workflows/android-signed-apk.yml`](../.github/workflows/android-signed-apk.yml) ·
Job: `build-sign-publish` · Guard: [`scripts/verify_signed_apk.py`](../scripts/verify_signed_apk.py)

Ziel: **bei jedem Push eine echte, signierte APK** – gebaut mit Gradle/AGP in der
Cloud (echtes `classes.dex`, Native-DSP `lib/<abi>/libkaoss_native.so`, PWA in
`assets/www/`), mit `apksigner` signiert (v1 + v2 + v3), verifiziert und an drei
Orten bereitgestellt:

1. **GitHub Release** `apk-latest` (rolling) bzw. Tag `v*.*.*` – Asset-Download per `gh`
2. **Repo-Tree** `releases/android/` – die APK plus Signier-Nachweis, von CI committet
3. **Workflow-Artefakt** `signed-android-release` (30 Tage)

## Pipeline

```
push / tag / workflow_dispatch / pull_request
        │
        ├─ actions/checkout (fetch-depth 0, persist-credentials)
        ├─ setup-java 17 (temurin) ─ android-actions/setup-android
        ├─ sdkmanager: platforms;android-35, build-tools;35.0.0, ndk;26.1.10909125, cmake;3.22.1
        ├─ gradle/actions/setup-gradle 8.7      (kein Wrapper-Jar im Repo)
        ├─ web/ → android/app/src/main/assets/www/  (additiv, PWA-Sync)
        ├─ android/local.properties (sdk.dir, ndk.dir)
        │
        ├─ SIGNIER-IDENTITÄT auflösen
        │     1. secrets.KAOSS_KEYSTORE_BASE64      → repo-secret   (persistent, empfohlen)
        │     2. actions/cache  kaoss-signing-keystore-v1 → actions-cache (persistent, branch-scoped)
        │     3. keytool -genkeypair (RSA-2048, 10a) → ephemeral-ci  (neu pro Lauf, wird gecacht)
        │     → android/keystore.properties (0600, gitignored) + KAOSS_KEYSTORE_FILE
        │     → Vorflug: keytool -list (Keystore muss für JDK 17 lesbar sein)
        │
        ├─ gradle :app:assembleRelease             → app-release.apk (AGP-signiert)
        ├─ apksigner sign --v1 --v2 --v3 true      → Schemata explizit erzwungen
        ├─ staging: KaossBeatboxStudio-v<versionName>-<versionCode>-universal-signed.apk + SHA256SUMS.txt
        ├─ VERIFIKATION
        │     zipalign -c -v 4                     (16-KB-Check informationell)
        │     apksigner verify --verbose --print-certs → apksigner-report.txt
        │     apksigner verify --print-certs-pem       → kaoss-ci-cert.pem
        │     jarsigner -verify (v1-Nachweis, informationell)
        │     scripts/verify_signed_apk.py --apksigner-report … --json …
        │     scripts/verify_signed_apk.py --selftest  (Guard testet sich selbst)
        ├─ gradle :app:bundleRelease (continue-on-error) + jarsigner -verify → optionales AAB
        ├─ SIGNING.txt + RELEASE-NOTES.md
        ├─ actions/cache/save (nur wenn Keystore neu erzeugt wurde)
        ├─ actions/upload-artifact
        ├─ gh release create|upload --clobber|edit → Release
        └─ git commit + push → releases/android/   (nicht bei PR, nicht bei Tags)
```

## Trigger

| Event | Build | Release | Repo-Commit |
| --- | --- | --- | --- |
| `push` auf `main` / `arena/*` (Pfade `android/**`, `web/**`, `scripts/**`, `tests/**`, `Makefile`, Workflow) | ja | ja (`apk-latest`) | ja |
| `push` Tag `v*.*.*` | ja | ja (Tag-Release) | nein |
| `workflow_dispatch` | ja | laut Input `publish_release` | laut Input `commit_to_repo` |
| `pull_request` | ja (Verifikation) | nein | nein |

`pull_request`-Läufe nutzen nie den Actions-Cache und schreiben nichts zurück –
sie beweisen nur, dass der Build signiert und guard-grün ist.

## Signier-Identität persistent machen (empfohlen)

Der Bot-Token der Agent-Sandbox darf **keine Secrets** schreiben
(`HTTP 403: Resource not accessible by integration`). Darum: einmal mit deinem
`gh`-Login (Scope `admin:repo`) ausführen:

```bash
./scripts/setup_signing_secrets.sh            # erzeugt Keystore + setzt 4 Secrets
./scripts/setup_signing_secrets.sh --help
./scripts/setup_signing_secrets.sh --keystore ~/bestehend.p12 --alias kaoss --password '…'
./scripts/setup_signing_secrets.sh --print-base64   # nur Ausgabe für die Web-UI
```

Gesetzte Secrets:

| Secret | Inhalt |
| --- | --- |
| `KAOSS_KEYSTORE_BASE64` | PKCS12/JKS-Keystore, base64 (eine Zeile) |
| `KAOSS_KEYSTORE_PASSWORD` | Store-Passwort |
| `KAOSS_KEY_ALIAS` | Alias, Standard `kaoss` |
| `KAOSS_KEY_PASSWORD` | Key-Passwort (bei PKCS12 = Store-Passwort) |

Manuell: *Settings → Secrets and variables → Actions → New repository secret*.

Das Skript legt zusätzlich den **öffentlichen** Teil nach
`android/signing/kaoss-ci-release-cert.pem` (+ Fingerprint-Datei) – nur diese
beiden Dateien committen, nie `.p12`/`-key.pem` (`.gitignore` blockt sie).

### Fallback ohne Secrets

Solange kein Secret existiert, erzeugt CI pro Lauf einen Self-Signed-Key
(`ephemeral-ci`) und legt ihn in den Actions-Cache
(`kaoss-signing-keystore-v1`). Folge-Builds desselben Zweigs signieren dann mit
demselben Key (`actions-cache`). Grenzen:

* Cache-Einträge verfallen nach 7 Tagen ohne Nutzung → danach neue Identität.
* Caches sind branch-scoped: `main` erbt nicht von Feature-Branches (umgekehrt schon).
* PR-Läufe und Tag-Läufe können eine andere Identität haben als Branch-Läufe.

Für eine **dauerhaft stabile** Signatur (Update über bestehende Installation,
vergleichbare Fingerprints) sind die Secrets der einzige verlässliche Weg.

## Bereitstellen / Herunterladen (gh CLI)

```bash
# Build anstoßen
gh workflow run "Android signed APK (CI/CD + GitHub Release)" --ref main
gh run list --workflow android-signed-apk.yml --limit 5
gh run watch <run-id>

# Release ansehen / laden
gh release view apk-latest --json tagName,assets,url
gh release download apk-latest --pattern '*.apk' --clobber
gh release download apk-latest --pattern 'SIGNING.txt' --output -

# APK aus dem Repo-Tree
git pull && ls -l releases/android/
adb install -r releases/android/KaossBeatboxStudio-v5.0.0-50000-universal-signed.apk
```

## Verifikation

```bash
python3 scripts/verify_signed_apk.py releases/android/*.apk \
  --apksigner-report releases/android/apksigner-report.txt
python3 scripts/verify_signed_apk.py --selftest     # Guard-Selftest (4 Szenarien)
make test-ci-signed-apk                             # kompletter CI/CD-Vertrag
make verify-signed-apk
$ANDROID_HOME/build-tools/35.0.0/apksigner verify --verbose --print-certs <apk>
sha256sum -c releases/android/SHA256SUMS.txt
```

Der Guard verlangt: `PK`-Magic, binäres AXML-Manifest, `classes.dex`,
`resources.arsc`, `lib/<abi>/libkaoss_native.so` für alle drei ABIs,
`libc++_shared.so`, `assets/www/index.html`, Mindestgröße 500 kB,
APK-Signing-Block-Magic und einen `apksigner`-Report mit `Verifies`,
`v2=true`, genau einem Signer samt Zertifikat-SHA-256.

**v1 (JAR-Signatur):** `apksigner verify` prüft v1 erst ab `minSdk < 24`. Bei
`minSdk 26` steht dort also `Verified using v1 scheme (JAR signing): false`,
obwohl AGP `META-INF/<ALIAS>.SF`/`.RSA` schreibt. Der v1-Nachweis läuft deshalb
über `jarsigner -verify` (informationell, weil Android 8+ v2/v3 genügt);
`--require-v1` ist nur für APKs mit `minSdk < 24` sinnvoll.

**Negativ-Fixture:** `releases/KaossBeatboxStudio-v5.0.0-Universal-Signed.apk`
ist der offline handgebaute Stub ohne `lib/*.so`. Er muss bleiben, wie er ist –
[`tests/release_artifact_guard_test.py`](../tests/release_artifact_guard_test.py)
und [`tests/signed_apk_test.py`](../tests/signed_apk_test.py) hängen daran.
Die echte APK lebt deshalb ausschließlich in `releases/android/`.

## Troubleshooting

| Symptom | Ursache / Fix |
| --- | --- |
| Run scheitert in 0 s, „workflow file issue“, 0 Jobs | YAML-Fehler. Klassiker: `- name: Guard: …` – Doppelpunkt im Step-Namen muss gequotet werden. Lokal: `python3 -c "import yaml;yaml.safe_load(open('.github/workflows/x.yml'))"` |
| `app-release-unsigned.apk` | `KAOSS_KEYSTORE_FILE`/`android/keystore.properties` fehlten. Gradle loggt dann `WARN: kein Keystore gefunden …` |
| `Keystore nicht gefunden: …` | Secret-Base64 war mehrzeilig/kaputt. Neu: `base64 -w0` (eine Zeile), `--print-base64` nutzen |
| `apksigner` meldet `DOES NOT VERIFY` | Signierschritt prüfen; APK nie nach dem Signieren mit `zipalign` neu ausrichten (Reihenfolge: align → sign) |
| Guard: `v1 JAR-Signatur gefordert, aber v1=False` | erwartbar bei `minSdk ≥ 26`: `apksigner verify` überspringt die v1-Prüfung. Kein `--require-v1` verwenden, v1 per `jarsigner -verify` nachweisen |
| Repo-Commit-Push scheitert | Branch hat sich bewegt; der Schritt rebased und versucht es 3×. Sonst Job neu laufen lassen |
| Cache-Miss nach Tagen | erwartbar, dann `ephemeral-ci`; Secrets beseitigen das dauerhaft |
| 16-KB-Alignment-Warnung | informationell (Android 15+); NDK `r27`+ und AGP 8.5.1+ nötig, um sie zu erfüllen |

## Grenzen (ehrlich)

* **Self-Signed**: kein von Google ausgestelltes Upload-Zertifikat, kein
  Play App Signing. Für Play-Veröffentlichung muss der dort hinterlegte
  Upload-Key als `KAOSS_KEYSTORE_BASE64` registriert werden.
* Die APK ist **universal** (alle drei ABIs in einer Datei) und unminifiziert
  (`isMinifyEnabled = false`) – größer als ein ABI-Split, dafür ein Artefakt.
* Kein `gradle-wrapper.jar` im Repo (`scripts/verify_gradle_wrapper.py` warnt
  bewusst); CI nutzt `gradle/actions/setup-gradle` mit Gradle 8.7.
* Hardware-HALs (Oboe/AAudio exklusiv, USB-UAC2, BLE-Codec) sind im APK als
  Shim-Implementierungen enthalten; echte Vendor-SDKs gehören nicht in CI.
