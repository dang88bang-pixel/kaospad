# `releases/android/` – die echte, signierte APK aus CI/CD

Dieses Verzeichnis wird **vom Workflow**
[`.github/workflows/android-signed-apk.yml`](../../.github/workflows/android-signed-apk.yml)
befüllt (Job `build-sign-publish`, Schritt *Signierte APK ins Repo committen*).

| Datei | Inhalt |
| --- | --- |
| `KaossBeatboxStudio-v<version>-<versionCode>-universal-signed.apk` | echter Gradle/AGP-Release-Build (ART-`classes.dex`, Native-DSP `lib/<abi>/libkaoss_native.so`, PWA unter `assets/www/`), `zipalign -p 4` + apksigner-Signatur (v2 + v3 verifiziert, v1-JAR mitgeschrieben) |
| `SHA256SUMS.txt` | `sha256sum -c SHA256SUMS.txt` |
| `SIGNING.txt` | Signier-Nachweis: Identität, Zertifikat-DN, Zertifikat-SHA-256, Schemata, Commit, Run-Link |
| `apksigner-report.txt` | Originalausgabe von `apksigner verify --verbose --print-certs` |
| `kaoss-ci-cert.pem` | öffentliches Signierzertifikat (PEM) – kein Private Key |
| `apk-verification.json` | maschinenlesbares Guard-Ergebnis (`scripts/verify_signed_apk.py`) |
| `jarsigner-report.txt` | v1-JAR-Nachweis (`jarsigner -verify`), da `apksigner` v1 ab minSdk 24 nicht prüft |

Es bleibt bewusst **genau eine** APK im Tree: jeder Build ersetzt die vorherige,
die Historie liegt im Release (`apk-latest` bzw. Tag `v*.*.*`) und in Git.

## Herunterladen / installieren

```bash
# aus dem GitHub Release (private Repo → gh muss eingeloggt sein)
gh release download apk-latest --repo dang88bang-pixel/kaospad --pattern '*.apk' --clobber

# oder direkt aus dem Repo-Tree
git pull
adb install -r releases/android/KaossBeatboxStudio-v5.0.0-50000-universal-signed.apk
```

Sideload ohne `adb`: APK aufs Gerät kopieren, „unbekannte Quellen“ erlauben, öffnen.
`minSdk 26` (Android 8.0), ABIs `armeabi-v7a`, `arm64-v8a`, `x86_64`.

## Selbst prüfen

```bash
sha256sum -c releases/android/SHA256SUMS.txt
python3 scripts/verify_signed_apk.py releases/android/*.apk \
  --apksigner-report releases/android/apksigner-report.txt
make test-ci-signed-apk          # kompletter CI/CD-Vertrag
```

Mit Android-Build-Tools lokal:

```bash
$ANDROID_HOME/build-tools/35.0.0/apksigner verify --verbose --print-certs releases/android/*.apk
```

## Abgrenzung zum Offline-Stub

`releases/KaossBeatboxStudio-v5.0.0-Universal-Signed.apk` (**ein Verzeichnis
höher**) ist der offline, ohne Gradle handgebaute Stub aus
`scripts/build_signed_apk.py`. Er hat kein `lib/<abi>/libkaoss_native.so` und
dient [`tests/release_artifact_guard_test.py`](../../tests/release_artifact_guard_test.py)
als **Negativ-Fixture** – er darf nicht überschrieben und nicht als Release-APK
publiziert werden. Der Guard `scripts/verify_signed_apk.py` lehnt ihn ab.

## Signier-Identität

`SIGNING.txt` nennt die Quelle des Keystores:

| Wert | Bedeutung |
| --- | --- |
| `repo-secret` | Keystore aus `secrets.KAOSS_KEYSTORE_BASE64` – persistent, empfohlen (`scripts/setup_signing_secrets.sh`) |
| `actions-cache` | persistenter Keystore aus dem Actions-Cache (`kaoss-signing-keystore-v1`), branch-scoped |
| `ephemeral-ci` | pro Lauf mit `keytool` erzeugter Self-Signed-Key; Signatur wechselt, Update über eine Alt-Installation schlägt fehl |

Private Keys liegen niemals in Git (`.gitignore`: `*.p12`, `*.jks`,
`android/keystore.properties`, `signing-cache/`).

Details: [`docs/CI_CD_SIGNED_APK.md`](../../docs/CI_CD_SIGNED_APK.md).
