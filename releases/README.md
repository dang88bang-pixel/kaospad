# Signierte APK + Store-Alternativen (A)

Datei: `KaossBeatboxStudio-v5.0.0-Universal-Signed.apk`

> Alternative zu Store-Zugängen ⛔ — Sideload ohne Play Console: `adb install`, F-Droid, GitHub Releases, itch.io. Play Console nur für Monetarisierung nötig.

```bash
make signed-apk
```

- Signatur: RSA-2048, **JAR v1** (`META-INF/KAOSS.RSA`) + **APK Signature Scheme v2** (`APK Sig Block 42`)
- Zertifikat: `android/signing/kaoss-release-cert.pem` (Offline-Projektkey, 10 Jahre)
- Privater Schlüssel wird lokal erzeugt (`android/signing/kaoss-release-key.pem`, nicht im Git)
- Inhalt: Binary-Manifest, Stub-DEX `com.kaoss.studio`, PWA unter `assets/www/`

Play-Store-AAB/Play App Signing und ein von Google ausgestelltes Upload-Zertifikat sind getrennt; diese APK ist für Offline-Sideload und CI-Artefakt gedacht.

SHA-256 steht in `KaossBeatboxStudio-v5.0.0-Universal-Signed.apk.sha256`.

## Store-Alternativen (A) — ohne Play Console installierbar

```bash
# ADB Sideload (Dev & Test ohne Store)
adb install releases/KaossBeatboxStudio-v5.0.0-Universal-Signed.apk
adb install app/build/outputs/apk/debug/app-debug.apk   # nach -Psigning=false

# F-Droid (Self-Hosted Repo)
fdroid build && fdroid publish  # docs: https://f-droid.org/docs/Setup_an_F-Droid_App_Repo/

# GitHub Releases (automatisiert via softprops/action-gh-release)
# .github/workflows/multiplatform-ci-cd.yml → publish-release job
# itch.io → https://itch.io/docs/creators/getting-started
```

## Self-Signed Signing (A)

```bash
# Dev self-signed (keytool) — kostenlos, zero-cloud:
keytool -genkeypair -keystore android/signing/debug.jks -alias kaoss -keyalg RSA -keysize 2048 -validity 3650 -storepass android -keypass android -dname "CN=Kaoss Debug"
jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA-256 -keystore android/signing/debug.jks app-unsigned.apk kaoss
# oder offline v1+v2 Signer:
python3 scripts/build_signed_apk.py

# Gradle Alternativen (G/H):
./gradlew assembleDebug -Psigning=false          # unsigniert
CI_SIGNING=false ./gradlew assembleRelease       # unsigniert (CI Fallback)
gradle --no-daemon wrapper --gradle-version 8.7  # offline wrapper erzeugen
```

Siehe auch: `docs/ALTERNATIVE_LOESUNGSWEGE.md` und `docs/INSTALLATION.md`.
