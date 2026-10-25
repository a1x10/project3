import java.util.Properties

plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }

// Адрес и ключ берутся из android/local.properties (в git не попадает):
//   stella.url=https://stellaalex.duckdns.org
//   stella.key=ВАШ_STELLA_API_KEY
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
android {
    namespace = "com.stels.stella"
    compileSdk = 34
    defaultConfig { applicationId = "com.stels.stella"; minSdk = 26; targetSdk = 34; versionCode = 1; versionName = "1.0"
        buildConfigField("String", "STELLA_URL", "\"${localProps.getProperty("stella.url", "")}\"")
        buildConfigField("String", "STELLA_KEY", "\"${localProps.getProperty("stella.key", "")}\"")
    }
    buildFeatures { buildConfig = true }
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
