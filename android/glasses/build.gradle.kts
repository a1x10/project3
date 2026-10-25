plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "com.stels.stella"
    compileSdk = 34
    defaultConfig { applicationId = "com.stels.stella"; minSdk = 26; targetSdk = 34; versionCode = 1; versionName = "1.0" }
    applicationVariants.all {
        outputs.all { (this as com.android.build.gradle.internal.api.BaseVariantOutputImpl).outputFileName = "stella-glasses.apk" }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
}
