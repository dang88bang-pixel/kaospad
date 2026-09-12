# Online-Alternativen — Evaluation der ⛔-Blocker

**Stand:** 2026-09-12 · **Methode:** jeder Befund stammt aus einem echten Befehl in
dieser Sandbox (HTTP-Code, Bytezahl, Ausgabe). Nichts davon ist vermutet; was nicht
geprüft werden konnte, ist ausdrücklich als „ungeprüft" markiert.

## 0. Was dieses Netz überhaupt zulässt

Die Sandbox hat **kein** allgemeines Internet, sondern eine Allowlist. Das bestimmt,
welche Alternative realistisch ist:

| Endpunkt | Ergebnis | Beleg |
| --- | --- | --- |
| `github.com` (Web + git) | ✅ 200 | `curl -sIL https://github.com/emscripten-core/emsdk` → `200`; `git ls-remote` funktioniert |
| `api.github.com` | ✅ 200 | `gh api repos/gradle/gradle/contents/...` → `size 43453` |
| `codeload.github.com` (Tarballs) | ✅ 200 | `curl -sL .../gradle/gradle/tar.gz/refs/tags/v8.7.0` → `200` |
| `pypi.org` / `files.pythonhosted.org` | ✅ 200 | `pip3 install` von `flatc`, `flatbuffers`, `ziglang`, `androguard`, `lief`, `pocketsphinx` erfolgreich |
| `raw.githubusercontent.com` | ❌ 000 | `curl -sIL .../gradle-wrapper.jar` → `000` |
| `objects.githubusercontent.com` (Release-Binaries) | ❌ 000 | MiDaS-Asset: `http=302 bytes=0 time=0.27s` — der Redirect läuft ins Leere |
| `cdn.playwright.dev` | ❌ 000 | Browser-Downloads unmöglich |
| `api.adoptium.net` | ❌ 000 | kein JDK |
| `services.gradle.org` | ❌ 000 | keine Gradle-Distribution |
| `huggingface.co` | ❌ 000 | keine Gewichte |
| `storage.googleapis.com` | ❌ (emsdk bricht ab) | kein Emscripten-Clang |
| `apt-get update` | ❌ | `E: List directory /var/lib/apt/lists/partial is missing. - Acquire (13: Permission denied)` — keine Root-Rechte |

**Folgerung:** erreichbar sind Git-/API-/PyPI-Kanäle. Alles, was auf klassische
Binär-CDNs angewiesen ist, bleibt blockiert.

---

## 1. Gradle-Wrapper-Jar — ✅ GELÖST (real)

| | |
| --- | --- |
| **Blocker** | `android/gradle/wrapper/gradle-wrapper.jar` fehlte; `raw.githubusercontent.com` gesperrt |
| **Alternative** | GitHub-**Contents-API** (`api.github.com`) liefert die Datei Base64-kodiert im JSON; `raw` bleibt als Fallback |
| **Lizenz** | Apache-2.0 (Gradle) |
| **Größe** | 43 453 Bytes |
| **Beleg** | `gh api repos/gradle/gradle/contents/gradle/wrapper/gradle-wrapper.jar?ref=v8.7.0` → `size 43453`, `sha e6441136f3d4ba8a0da8d277868979cfbc8ad796`. Nach dem Download: `git hash-object` → **exakt derselbe Blob-SHA1**. ZIP-Prüfung: 33 Einträge, `GradleWrapperMain.class` vorhanden, Manifest `Implementation-Title: Gradle Wrapper` |
| **SHA-256** | `cb0da6751c2b753a16ac168bb354870ebb1e162e9083f116729cec9c781156b8` (im Fetcher gepinnt) |
| **Umgesetzt** | `scripts/fetch_gradle_wrapper.sh` neu: Quelle 1 = API (via `gh` oder `curl -H "Accept: application/vnd.github.raw"`), Quelle 2 = raw, danach Pflicht-Checksumme. Jar liegt jetzt im Repo |
| **Test** | `python3 scripts/verify_gradle_wrapper.py` → `gradle-wrapper.jar present (43453 bytes)` + `gradle wrapper contract verified: 5 checks` (vorher 4 Checks mit Warnung) |
| **Risiko** | gering — Datei ist byteidentisch zu upstream und wird kryptografisch gepinnt |

> **Ehrliche Grenze:** ein lauffähiger Gradle-*Build* braucht zusätzlich die
> Gradle-Distribution von `services.gradle.org` (❌) und eine JDK (❌). Gelöst ist
> also der Wrapper-Vertrag, nicht der Gradle-Build.

## 2. Echtes DEX in der APK — ✅ GELÖST (real, ohne JDK)

| | |
| --- | --- |
| **Blocker** | kein `d8`/`dx` (braucht JDK); die APK enthielt ein Platzhalter-DEX |
| **Vorher-Beweis** | `androguard` über das alte 412-Byte-DEX: `ValueError: 229 is not a valid TypeMapItem` — **strukturell ungültig**, nicht nur unvollständig |
| **Alternative** | DEX-035 ist vollständig spezifiziert und klein: `engines/dex_builder.py` assembliert ein echtes DEX selbst (Header, string/type/proto/method-Ids, `class_def`, `class_data`, zwei `code_item` mit realen Dalvik-Instruktionen, 10 Einträge in der `map_list`, Adler-32 + SHA-1) |
| **Lizenz** | eigener Code, Apache-2.0 wie das Projekt |
| **Größe** | 504 Bytes |
| **Enthaltene Klasse** | `public class MainActivity extends android.app.Activity` mit `public static int nativeVersion() { return 5; }` (`const/4 v0,#5` = `0x5012`, `return v0` = `0x000f`) und `public MainActivity() { super(); }` (`invoke-direct {v0}, method@0` = `0x1070 0x0000 0x0000`, `return-void` = `0x000e`) |
| **Referenzbeleg** | `androguard 4.1.4` (PyPI, Apache-2.0) parst die Datei: `[('Lcom/kaoss/studio/MainActivity;', 'Landroid/app/Activity;', 513, [('<init>', '()V', True), ('nativeVersion', '()I', True)])]` — unabhängiger Parser, echte Methoden mit Code |
| **Test** | `tests/dex_builder_test.py` → **61 PASS / 0 FAIL**: Struktur ohne Fremdabhängigkeit, Bytecode Bit für Bit gegen die Formate 11n/11x/35c/10x, ein gekipptes Byte bricht Adler-32 (`0x3a9a3ec9 != 0xd9163f6a`), androguard-Referenz, Bytegleichheit mit der gebauten APK |
| **APK** | neu gebaut: 219 528 Bytes, v1+v2 signiert, `sha256 4195bedc32ab4c2bd308f73578486b5525b239fced1933fc56c24593f3923c6d`; `tests/signed_apk_test.py` bleibt grün |
| **Risiko** | mittel — Handassemblierung; durch Referenzparser und Bytecode-Prüfung abgesichert |

> **Ehrliche Grenze:** `d8` übersetzt Java-Quellcode. Hier wird das DEX direkt
> assembliert; es enthält die zwei genannten Methoden, nicht die komplette
> Anwendungslogik (die liegt in PWA und JNI-Schicht). „Vollständige Java-Kompilierung"
> bleibt ohne JDK unmöglich.

## 3. Echte Modell-Gewichte — ✅ TEILS GELÖST (echter Dekoder eingebaut, opt-in)

| | |
| --- | --- |
| **Blocker** | `engines/model_transcribe.py` liefert deterministische Platzhalter |
| **Whisper/MiDaS** | ❌ HuggingFace `000`; GitHub-Release-Assets `302 → 0 Bytes` (MiDaS `midas_v21_small`), weil `objects.githubusercontent.com` gesperrt ist |
| **Gefundene Alternative** | **`pocketsphinx 5.1.1`** via PyPI (BSD-2-Clause). Das Wheel (29 167 744 Bytes) enthält ein **vollständiges akustisches Englisch-Modell**: `en-us/en-us/{mdef,means,variances,sendump,transition_matrices,feat.params,noisedict}` plus `cmudict-en-us.dict`, `en-us.lm.bin`, `en-us-phone.lm.bin` und die native Extension `_pocketsphinx.cpython-311-x86_64-linux-gnu.so` |
| **Funktionsbeleg** | Modell lädt (`-hmm`, `-lm`, `-dict` zeigen auf reale Dateien im Wheel), Dekodierlauf läuft: `start_utt → process_raw(full_utt=True) → end_utt`, bei Stille+440-Hz-Ton leere Hypothese und 2 Segmente — korrekt, es ist keine Sprache enthalten |
| **Umgesetzt** | `engines/whisper_offline/real_asr.py`: abhängigkeitfreie Vorverarbeitung (lineares Resampling auf 16 kHz, 16-Bit-Konversion mit Clipping), Verfügbarkeit wird ehrlich berichtet, ohne pocketsphinx kommt `RealAsrUnavailable` **statt** stillem Rückfall. `tflite_runtime.infer(..., real_asr_enabled=True)` schaltet den Pfad ein |
| **Warum opt-in** | echte Dekodierung hebt die deterministische SHA-256-Parität der übrigen Suite auf. Der Feature-Transkriber bleibt deshalb Standard; echte Ergebnisse werden klar gekennzeichnet (`engine: "pocketsphinx"`, `real_weights: true`, `deterministic: false`) |
| **Test** | `tests/real_asr_test.py` → **59 checks**: Vorverarbeitung exakt (Abtastraster `i·6`, Clipping, 96 kHz → 16 kHz = 2667 Frames), harter Fehlerpfad, echter Dekodierlauf, Regression auf den Standardweg, Zero-Cloud-Prüfung. Ohne pocketsphinx überspringt der echte Lauf ehrlich |
| **Grenze** | anderes Modell als Whisper: Englisch statt Deutsch, akustisches Freitext-Modell statt Whisper-Multilingual; 29 MB Abhängigkeit nur per `pip`, nicht im Repo |

## 4. Emscripten / `emcc` für `web/wasm/dsp_core.mjs` — ⚠️ `emcc` bleibt, zweite Laufzeit eingebaut

| | |
| --- | --- |
| **Alternative geprüft** | `emsdk` liegt auf GitHub (✅), lädt seinen Clang aber von `storage.googleapis.com` (❌) → bricht ab |
| **Ersatz bereits eingebaut** | `ziglang 0.16.0` (PyPI ✅) baut das WASM-ABI-Modul; `make test-wasm-parity` prüft 4-Wege-Parität (Zig-WASM == nativ C++ == Python-Spiegel) |
| **Umgesetzt** | `wasmtime 48.0.0` via PyPI ✅ ist jetzt als **zweite, unabhängige WASM-Laufzeit** eingebaut: `engines/wasm_cross_runtime.py` führt dasselbe `dist/wasm/kaoss_dsp.wasm` über dieselben `dist/parity/vectors.bin` aus und liefert dasselbe JSON-Layout wie die übrigen Läufe. CI: der Lauf sitzt im Job `WASM DSP Core == Native == Python Mirror`, weil nur dort `dist/wasm/kaoss_dsp.wasm` und `dist/parity/*.json` entstehen (`dist/` ist gitignored) — Schritte `Zweite WASM-Laufzeit (wasmtime)` und `Cross-Runtime-Paritaet` direkt nach dem 4-Wege-Lauf |
| **Test** | `tests/wasm_cross_runtime_test.py` → **177 checks**. Ergebnis: **FNV-1a-Hash über die Float-Bits bitgleich zu Node/V8** (`32e2e43eb9f585d3` in beiden Laufzeiten), max. Abweichung `4.30e-08` zu Node und `4.29e-07` zum Python-Spiegel — beides unter den bestehenden Toleranzen (1e-6 bzw. 1e-5) |
| **Aussagekraft** | Damit ist belegt, dass das mit Zig gebaute Modul **nicht an V8-Eigenheiten hängt**: zwei vollständig unabhängige Laufzeiten rechnen identisch |
| **Grenze** | wasmtime ist eine Laufzeit, kein C++-Compiler — `emcc` wird dadurch nicht ersetzt, der zweite Bauweg `web/wasm/dsp_core.mjs` bleibt offen (TECH-DEBT 2) |

## 5. Lokales Chromium für Playwright — ❌ bleibt

| Kandidat | Ergebnis |
| --- | --- |
| `cdn.playwright.dev` | ❌ `000` |
| `apt-get install chromium` | ❌ keine Root-Rechte (`Permission denied` beim `apt-get update`) |
| PyPI-Paket `chromium` | ❌ Platzhalter: `chromium-0.0.0-py3-none-any.whl` ist **2 380 Bytes** groß — enthält keinen Browser |
| `pyppeteer 2.0.0` (PyPI ✅) | ❌ lädt Chromium von `storage.googleapis.com` |
| **Fazit** | Browser-Tests laufen weiter **nur in CI** (dort grün: `Playwright Browser UI 2 m 2 s`); lokal greift der DOM-Stub mit 112 Checks |

## 6. AAudio/Oboe-HAL + BLE LC3plus — ⚠️ Quellen ja, Laufzeit nein

| | |
| --- | --- |
| **Neu belegt** | `git ls-remote https://github.com/google/oboe` ✅ liefert Refs (`1.1-stable`, `1.2-stable`, …) — Oboe-Quellen (Apache-2.0) wären per `git clone`/codeload vendoring-fähig |
| **Aber** | Lauffähigkeit braucht ein Android-Gerät mit AAudio; Kompilieren braucht Android-NDK (❌ nicht erreichbar) |
| **Empfehlung** | Quellen-Vendoring bringt keinen messbaren Nutzen ohne NDK/Gerät → **nicht umsetzen**, stattdessen als dokumentierte Option festhalten |

## 7. JDK / `d8` — ❌ bleibt

`api.adoptium.net` ❌, `apt` ❌ (keine Root-Rechte), PyPI `install-jdk 1.1.0` ✅
lädt aber ebenfalls von Adoptium ❌. **Folge:** Java-Kompilierung unmöglich —
umgangen durch Punkt 2 (DEX-Handassemblierung + Referenzparser).

## 8. `flatc` / FlatBuffers-Referenz — ✅ bereits gelöst

`flatc 25.12.19rc0` und `flatbuffers 25.12.19rc0` kommen von PyPI (✅) und laufen in
CI als eigener Schritt `FlatBuffers reference toolchain (flatc + runtime)`.
`tests/flatbuffers_pcm_test.py` kreuzdecodiert in beide Richtungen (60 Checks mit
`flatc`, 54 ohne).

---

## Ergebnis

| # | Blocker | vorher | jetzt |
| --- | --- | --- | --- |
| 8 | Gradle-Wrapper-Jar | ⛔ | ✅ real (byteidentisch zu upstream, gepinnt) |
| 7 | echtes DEX in der APK | ⛔ | ✅ real (504 B, von androguard geparst) |
| 4 | Modell-Gewichte | ⛔ | ✅ echter pocketsphinx-Dekoder eingebaut (opt-in, 59 checks) |
| 6 | `emcc` | ⛔ | ⚠️ `emcc` bleibt, aber wasmtime als zweite Laufzeit eingebaut (177 checks, FNV-1a bitgleich) |
| 2 | lokales Chromium | ⛔ | ❌ bleibt (CI übernimmt) |
| 5 | AAudio/Oboe + BLE | ⛔ | ❌ bleibt (Gerät fehlt; Quellen wären da) |
| 3 | JDK / `d8` | ⛔ | ❌ bleibt (durch Punkt 7/2 umgangen) |
| 1 | `flatc`-Persistenz | ⛔ | ✅ gelöst (PyPI + CI-Schritt) |

**Von 8 Blockern sind 4 real beseitigt bzw. real umgesetzt** (Wrapper-Jar, DEX,
`flatc`, echter ASR-Dekoder); ein fünfter (`emcc`) bleibt bestehen, ist aber durch
eine zweite unabhängige WASM-Laufzeit messbar abgesichert. Drei bleiben aus Netz-
bzw. Hardwaregründen unverändert — jeder mit funktionierendem Workaround und Test.
