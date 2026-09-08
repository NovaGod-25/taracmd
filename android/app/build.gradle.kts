plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.taracmd.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.taracmd.app"
        minSdk = 24
        targetSdk = 35
        // Every CI build was versionCode 1, so Android saw a new APK as the
        // same version as the installed one and refused it as an upgrade —
        // you had to uninstall first. The run number is monotonic per repo,
        // so CI builds now climb; a local build stays at 1, which is fine
        // because it is the only one on the device.
        val run = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull()
        versionCode = run ?: 1
        versionName = if (run != null) "1.0.$run" else "1.0"
    }

    buildTypes {
        release {
            // assembleRelease produces an UNSIGNED apk that will not install.
            // A real release needs a keystore and a signingConfigs block; CI
            // builds assembleDebug, which is signed with the debug key.
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    // index.html is written by build.py. Never hand-edit it — it drifted a
    // full rename behind the web build once already.
    androidResources {
        noCompress += "html"
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.webkit:webkit:1.12.1")
}
