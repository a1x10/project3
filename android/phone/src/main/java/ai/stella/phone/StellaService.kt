package ai.stella.phone

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import okhttp3.Request
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/** Держит SSE-канал с сервером 24/7 (foreground-сервис с иконкой) и выполняет команды сервера. */
class StellaService : Service() {
    private var source: EventSource? = null
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newCachedThreadPool()
    @Volatile private var running = false

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("stella", "Stella", NotificationManager.IMPORTANCE_LOW))
        val n = NotificationCompat.Builder(this, "stella").setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Стелла на связи").setOngoing(true).build()
        if (android.os.Build.VERSION.SDK_INT >= 29)
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else startForeground(1, n)
        running = true
        connect()
        return START_STICKY
    }

    override fun onDestroy() { running = false; source?.cancel(); super.onDestroy() }

    private fun connect() {
        if (!running || !Config.configured(this)) return
        val req = Request.Builder().url(Config.url(this) + "/events")
            .header("Authorization", "Bearer " + Config.key(this)).build()
        source = EventSources.createFactory(Api.sse).newEventSource(req, object : EventSourceListener() {
            override fun onEvent(es: EventSource, id: String?, type: String?, data: String) {
                try { handle(JSONObject(data)) } catch (_: Exception) {}
            }
            override fun onFailure(es: EventSource, t: Throwable?, response: Response?) = retry()
            override fun onClosed(es: EventSource) = retry()
        })
    }

    private fun retry() { if (running) main.postDelayed({ connect() }, 4000) }

    private fun handle(e: JSONObject) {
        if (e.optString("type") != "action") return
        val sender = e.optString("sender"); val key = e.optString("key"); val text = e.optString("text")
        when (e.optString("action")) {
            "reply" -> NotifListener.sendText(this, key, sender, text)
            "reply_voice" -> io.execute {
                val f = File(cacheDir, "voice/reply.ogg")
                if (Api.download(this, e.optString("audio"), f)) VoiceSendService.sendVoice(this, sender, f)
            }
        }
    }
}
