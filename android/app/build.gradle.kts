import java.io.File
import java.util.Properties

plugins {
    id("com.android.application")
    kotlin("android")
}

// ---------------------------------------------------------------------------
// Signier-Credentials (Reihenfolge):
//   1. android/keystore.properties  (CI erzeugt sie, gitignored, Modus 0600)
//   2. Umgebungsvariablen KAOSS_KEYSTORE_FILE / _PASSWORD / _KEY_ALIAS / _KEY_PASSWORD
//   3. nichts davon -> kein SigningConfig, Gradle liefert app-release-unsigned.apk
// Der Private Key liegt niemals im Repository; siehe docs/CI_CD_SIGNED_APK.md.
// ---------------------------------------------------------------------------
val keystoreProperties = Properties().apply {
    val propsFile = rootProject.file("keystore.properties")
    if (propsFile.isFile) {
        propsFile.inputStream().use { load(it) }
    }
}

fun signCredential(propertyKey: String, envKey: String, fallback: String? = null): String? =
    keystoreProperties.getProperty(propertyKey)?.takeIf { it.isNotBlank() }
        ?: System.getenv(envKey)?.takeIf { it.isNotBlank() }
        ?: fallback

val resolvedStoreFile: File? = signCredential("storeFile", "KAOSS_KEYSTORE_FILE")
    ?.let { path -> if (File(path).isAbsolute) File(path) else rootProject.file(path) }
    ?.also { file ->
        check(file.isFile) { "Keystore nicht gefunden: ${file.absolutePath}" }
    }

android {
    namespace = "com.kaoss.studio"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.kaoss.studio"
        minSdk = 26
        targetSdk = 35
        versionCode = 50000
        versionName = "5.0.0"
        ndk {
            abiFilters += listOf("armeabi-v7a", "arm64-v8a", "x86_64")
        }
        externalNativeBuild {
            cmake {
                cppFlags += "-std=c++17"
                arguments += listOf("-DANDROID_STL=c++_shared")
            }
        }
    }
    signingConfigs {
        if (resolvedStoreFile != null) {
            create("ciRelease") {
                storeFile = resolvedStoreFile
                storePassword = signCredential("storePassword", "KAOSS_KEYSTORE_PASSWORD", "android")
                keyAlias = signCredential("keyAlias", "KAOSS_KEY_ALIAS", "kaoss")
                keyPassword = signCredential("keyPassword", "KAOSS_KEY_PASSWORD") ?: storePassword
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            val ci = signingConfigs.findByName("ciRelease")
            if (ci != null) {
                signingConfig = ci
                println("release signing: keystore=${ci.storeFile?.name} alias=${ci.keyAlias}")
            } else {
                println(
                    "WARN: kein Keystore gefunden (KAOSS_KEYSTORE_FILE oder android/keystore.properties) " +
                        "-> es entsteht ein UNSIGNIERTES app-release-unsigned.apk"
                )
            }
        }
    }
    ndkVersion = "26.1.10909125"
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
        }
    }
    sourceSets {
        getByName("main") {
            assets.srcDirs("src/main/assets")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
}
