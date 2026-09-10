# Online recherchierte Alternativen (JDK/SDK/APK)

Recherche 2026-09-10. Quellen unten. Kein lokales SDK in dieser Box.

## Kurzfassung

Ohne Android-SDK gibt es **kein** offiziell lauffähiges APK ([3](https://stackoverflow.com/questions/42778865/is-it-possible-to-build-an-android-apk-without-using-sdk)). Die praxisnahen Umgehungen verlagern den Build **in die Cloud** oder wrappen die **PWA**.

## Optionen (nach Machbarkeit hier)

| # | Option | Braucht lokales JDK/SDK? | APK-Qualität | In dieser Box |
|---|---|---|---|---|
| **1** | **GitHub Actions** `ubuntu-latest` + Temurin + `gradlew assembleRelease` | nein (Runner hat SDK) | echte DEX, WebView, Signatur | **ja**, Repo ist auf GitHub |
| **2** | **PWABuilder / Bubblewrap TWA** | Cloud oder Node+JDK | Chrome Custom Tab, kleine APK | PWABuilder-Web tot/TLS; lokal Node-Tools oft CDN |
| **3** | **Capacitor / Cordova / Ionic** | SDK oder Cloud-Build | WebView-Shell | SDK fehlt |
| **4** | **Expo EAS / FlutterFlow / RapidNative** | Account, Cloud | RN/Flutter, nicht unser Kotlin | Account + Upload |
| **5** | **No-Code** (Adalo, Thunkable, AppsGeyser, Newly) | nein | fremde Runtime, nicht unser Code | ungeeignet |
| **6** | **PyPI `jdk4py`** | — | nur **JRE** (`java`/`keytool`, kein `javac`) | schon installiert, reicht nicht für D8/aapt2 |
| **7** | **Python-DEX/Smali** | — | Disassembler, kein Ersatz für `d8` | nicht produktionsfähig |

## 1. GitHub Actions (beste Alternative ohne lokales SDK)

GitHub-Runner laden JDK+SDK selbst ([1](https://github.com/wasishah33/android-apk-builder), [2](https://corenna.dev/blog/how-to-build-apk-from-github)). Ablauf: Workflow → Artifact `app-release.apk`.

Kernschritte laut Doku:

- `actions/setup-java` Temurin 17  
- `android-actions/setup-android` oder SDK-Cache  
- `./gradlew :app:assembleRelease`  
- Artifact / Release-Asset  

Passt zu diesem Repo (`android/` + Offline-Keystore-Secret). **Kein** Play Store nötig ([CI ohne Store](https://medium.com/@ashfaque-khokhar/build-and-download-an-android-apk-automatically-with-github-actions-6b5c66e9d1d6)).

## 2. PWA → APK (TWA)

- **Bubblewrap:** liest `manifest.webmanifest`, erzeugt TWA-APK (~1 MB), Chrome statt eigener WebView ([SO](https://stackoverflow.com/questions/76307541/what-is-the-advantage-of-bubblewrap-vs-android-native-webview)).  
- **PWABuilder** / PWA2APK: URL eintragen, AAB/APK laden ([Reddit](https://www.reddit.com/r/webdev/comments/1n08e6g/is-there-an-easy-way-to-convert-a-pwa-file-into/), [SaasToStore](https://saastostore.com/blog/pwa-to-apk)).  
- Nachteil: Live-URL oder HTTPS-Host; `file://`/`assets/www` allein reicht für TWA nicht. Native Oboe/USB fallen weg.

## 3. Web-Wrapper (Capacitor)

Empfohlen, wenn PWA-Score niedrig / kein Service Worker ([SaasToStore](https://saastostore.com/blog/pwa-to-apk)). Build trotzdem **SDK oder EAS-Cloud**.

## 4. Online-Builder

FlutterFlow, RapidNative, Adalo, Thunkable, AppsGeyser, Newly ([RapidNative](https://www.rapidnative.com/android-app-builder-online), [Newly](https://newly.app/guides/android-app-maker)): erzeugen **andere** Apps, nicht `com.kaoss.studio` aus diesem Tree.

## 5. „Ohne Studio“ ist nicht „ohne SDK“

Flutter/RN/KMP brauchen weiter Android-SDK-Tools ([CompleteEra](https://completeera.com/build-android-app-without-android-studio-a-comprehensive-guide/)). CLI ohne Studio braucht `aapt2`+`d8`+`apksigner` ([Gist CLI](https://gist.github.com/felix021/e7179596244ee81852c646f904adddf6)).

## Empfehlung für Kaoss

1. **Sofort nutzbar:** PWA-ZIP + HTTP-UI (bereits bereit).  
2. **Echte installierbare APK:** Workflow `.github/workflows/android-signed-apk.yml` — Temurin 17, SDK 35, NDK 26, Gradle 8.7, `assembleRelease`, Artifact. Start: GitHub → Actions → *Android signed APK* → *Run workflow*.  
3. **Store-TWA:** PWA öffentlich hosten, dann PWABuilder.  
4. Lokales `assembleRelease` erst nach freiem TLS zu `dl.google.com` / Adoptium.
