package ai.stella.phone

import android.content.Context
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

object Api {
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()
    /** Отдельный клиент без таймаута чтения для SSE. */
    val sse: OkHttpClient = http.newBuilder().readTimeout(0, TimeUnit.SECONDS).build()

    fun post(c: Context, path: String, json: JSONObject): Boolean = try {
        val req = Request.Builder().url(Config.url(c) + path)
            .header("Authorization", "Bearer " + Config.key(c))
            .post(json.toString().toRequestBody("application/json".toMediaType())).build()
        http.newCall(req).execute().use { it.isSuccessful }
    } catch (e: Exception) { false }

    fun download(c: Context, path: String, dest: File): Boolean = try {
        val req = Request.Builder().url(Config.url(c) + path)
            .header("Authorization", "Bearer " + Config.key(c)).build()
        http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) return false
            dest.parentFile?.mkdirs()
            dest.outputStream().use { out -> r.body!!.byteStream().copyTo(out) }
            true
        }
    } catch (e: Exception) { false }
}
