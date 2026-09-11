# `releases/` – zwei verschiedene Dinge, nicht verwechseln

## 1. `android/` → die echte, signierte APK aus CI/CD

**Das ist die installierbare APK.** Sie wird von
[`.github/workflows/android-signed-apk.yml`](../.github/workflows/android-signed-apk.yml)
gebaut, mit `apksigner` signiert (v1 + v2 + v3), vom Guard
[`scripts/verify_signed_apk.py`](../scripts/verify_signed_apk.py) geprüft und
sowohl in den GitHub Release `apk-latest` als auch nach `releases/android/`
publiziert.

```bash
gh release download apk-latest --pattern '*.apk' --clobber
adb install -r releases/android/KaossBeatboxStudio-v5.0.0-50000-universal-signed.apk
```

Inhalt, Verifikation, Signier-Identität: [`android/README.md`](android/README.md)
und [`docs/CI_CD_SIGNED_APK.md`](../docs/CI_CD_SIGNED_APK.md).

## 2. `KaossBeatboxStudio-v5.0.0-Universal-Signed.apk` → Offline-Stub (Negativ-Fixture)

```bash
make signed-apk        # erzeugt den Stub offline, ohne Gradle/JDK/Android SDK
make test-signed-apk   # prueft v1+v2-Struktur des Stubs
```

- Erzeugt von [`scripts/build_signed_apk.py`](../scripts/build_signed_apk.py):
  OpenSSL RSA-2048, **JAR v1** (`META-INF/KAOSS.RSA`) + eigener
  **APK-Signing-Block v2** (`APK Sig Block 42`)
- Zertifikat: `../android/signing/kaoss-release-cert.pem` (Offline-Projektkey, 10 Jahre)
- Privater Schlüssel wird lokal erzeugt (`android/signing/kaoss-release-key.pem`, nie im Git)
- Inhalt: binäres Manifest, **Stub-DEX**, PWA unter `assets/www/`, JNI-Quellen als Assets

Grenzen des Stubs: **kein `lib/<abi>/libkaoss_native.so`**, kein echter ART-Build,
kein Launch einer echten Activity. Er beweist die Offline-Signaturkette und dient
[`tests/release_artifact_guard_test.py`](../tests/release_artifact_guard_test.py)
als Negativ-Fixture – der Guard muss ihn ablehnen. Deshalb darf diese Datei
**nicht** durch eine echte APK ersetzt werden.

SHA-256: `KaossBeatboxStudio-v5.0.0-Universal-Signed.apk.sha256`.
Play-Store-AAB/Play App Signing und ein von Google ausgestelltes Upload-Zertifikat
sind separat; auch die CI-APK ist self-signed.
