# APK-Bereitstellung: geprüfte Alternativen

| Weg | Status in dieser Umgebung | Ergebnis |
|---|---|---|
| **A. Gradle + Android SDK + apksigner** | JDK/SDK-Download (Adoptium, Corretto, Azul, java.net, Debian HTTP) → TLS `SSL_ERROR_SYSCALL` / leere Antworten | nicht ausführbar |
| **B. Offizieller `gradle-wrapper.jar`** | `services.gradle.org` TLS blockiert | nicht ausführbar |
| **C. Play App Signing / Upload-Key** | braucht Google Play Console | nicht in CI |
| **D. OpenSSL Offline-Signer (gewählt)** | OpenSSL 3 vorhanden | **v1 JAR + v2 APK Sig Block 42**, volles Payload |
| **E. PWA / TWA** | `web/` + `make` PWA-ZIP | Alternative ohne Store, kein nativer Package-Manager |

Gewählt: **D**. Rebuild: `make signed-apk`.

Vollständiges Payload der APK:

- Binary `AndroidManifest.xml` (`com.kaoss.studio`, min 26, target 35)
- `classes.dex` (`MainActivity` + `<init>` bytecode)
- `resources.arsc`
- komplette PWA unter `assets/www/`
- Android-Quellen unter `assets/android-src/`
- Signatur RSA-2048, Zertifikat `android/signing/kaoss-release-cert.pem`

Wenn SDK erreichbar ist: `android/gradlew assembleRelease` + dasselbe Keystore ersetzen `apksigner`.
