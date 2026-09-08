plugins { id("com.android.application") }

android {
    namespace = "com.kaoss.studio"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.kaoss.studio"
        minSdk = 26
        targetSdk = 35
        versionCode = 50000
        versionName = "5.0.0"
        externalNativeBuild { cmake { cppFlags += "-std=c++17" } }
    }
    externalNativeBuild { cmake { path = file("src/main/cpp/CMakeLists.txt") } }
}
