plugins {
    id("com.android.application")
    kotlin("android")
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
    // Signing: H · CI/CD Alternative — CI_SIGNING=false oder -Psigning=false → unsigniert bauen
    // Für Dev/CI ohne Secrets: ./gradlew assembleDebug -Psigning=false oder CI_SIGNING=false gradle assembleDebug
    // Für Release: Secrets KAOSS_KEYSTORE_* setzen (siehe .github/workflows/multiplatform-ci-cd.yml)
    // Dev self-signed fallback: keytool -genkeypair -keystore signing/debug.jks -alias kaoss -keyalg RSA -keysize 2048 -validity 3650 -storepass android -keypass android -dname "CN=Kaoss Debug"
    signingConfigs {
        val signingEnabled = (findProperty("signing")?.toString()?.lowercase() != "false")
                && (System.getenv("CI_SIGNING")?.lowercase() != "false")
        if (!signingEnabled) {
            println("[Kaoss] Signing disabled via -Psigning=false / CI_SIGNING=false — building unsigned")
        }
        val keystorePath = System.getenv("KAOSS_KEYSTORE_FILE")
        if (signingEnabled && !keystorePath.isNullOrBlank()) {
            create("ciRelease") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("KAOSS_KEYSTORE_PASSWORD") ?: "android"
                keyAlias = System.getenv("KAOSS_KEY_ALIAS") ?: "kaoss"
                keyPassword = System.getenv("KAOSS_KEY_PASSWORD") ?: "android"
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            val signingEnabled = (findProperty("signing")?.toString()?.lowercase() != "false")
                    && (System.getenv("CI_SIGNING")?.lowercase() != "false")
            val ci = signingConfigs.findByName("ciRelease")
            if (signingEnabled && ci != null) {
                signingConfig = ci
            } else if (!signingEnabled) {
                println("[Kaoss] release build unsigned (CI_SIGNING=false)")
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
