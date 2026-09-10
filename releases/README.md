# Signierte APK

Datei: `KaossBeatboxStudio-v5.0.0-Universal-Signed.apk`

```bash
make signed-apk
```

- Signatur: RSA-2048, **JAR v1** (`META-INF/KAOSS.RSA`) + **APK Signature Scheme v2** (`APK Sig Block 42`)
- Zertifikat: `android/signing/kaoss-release-cert.pem` (Offline-Projektkey, 10 Jahre)
- Privater Schlüssel wird lokal erzeugt (`android/signing/kaoss-release-key.pem`, nicht im Git)
- Inhalt: Binary-Manifest, Stub-DEX `com.kaoss.studio`, PWA unter `assets/www/`

Play-Store-AAB/Play App Signing und ein von Google ausgestelltes Upload-Zertifikat sind getrennt; diese APK ist für Offline-Sideload und CI-Artefakt gedacht.

SHA-256 steht in `KaossBeatboxStudio-v5.0.0-Universal-Signed.apk.sha256`.
