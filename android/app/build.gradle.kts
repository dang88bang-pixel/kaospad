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
    signingConfigs {
        val keystorePath = System.getenv("KAOSS_KEYSTORE_FILE")
        if (!keystorePath.isNullOrBlank()) {
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
            val ci = signingConfigs.findByName("ciRelease")
            if (ci != null) {
                signingConfig = ci
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
