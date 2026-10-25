package ai.stella.phone

import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.Intent
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/** Перехватывает уведомления мессенджеров, шлёт на сервер и умеет отвечать из шторки (RemoteInput). */
class NotifListener : NotificationListenerService() {
    private val io = Executors.newSingleThreadExecutor()

    override fun onListenerConnected() { instance = this }
    override fun onListenerDisconnected() { if (instance === this) instance = null }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName !in APPS || !Config.configured(this)) return
        val n = sbn.notification
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        val ex = n.extras
        val sender = ex.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: return
        val text = ex.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: return
        if (text.matches(Regex("\\d+ (new )?(messages|сообщен.*)", RegexOption.IGNORE_CASE))) return

        val reply = n.actions?.firstOrNull { a -> a.remoteInputs?.isNotEmpty() == true }
        if (reply != null) replies[sbn.key] = Reply(sbn.key, sbn.packageName, sender, reply)

        io.execute {
            Api.post(this, "/notify", JSONObject()
                .put("app", APPS[sbn.packageName]).put("sender", sender).put("text", text).put("key", sbn.key))
        }
    }

    class Reply(val key: String, val pkg: String, val sender: String, val action: Notification.Action)

    companion object {
        val APPS = mapOf(
            "com.whatsapp" to "whatsapp", "com.whatsapp.w4b" to "whatsapp",
            "org.telegram.messenger" to "telegram",
            "com.google.android.apps.messaging" to "sms", "com.samsung.android.messaging" to "sms",
        )
        val replies = ConcurrentHashMap<String, Reply>()
        @Volatile var instance: NotifListener? = null

        /** Находим уведомление по ключу, иначе по имени отправителя (ключ мог смениться). */
        fun findReply(key: String, sender: String): Reply? =
            replies[key] ?: replies.values.lastOrNull { it.sender.equals(sender, ignoreCase = true) }

        fun sendText(ctx: android.content.Context, key: String, sender: String, text: String): Boolean {
            val r = findReply(key, sender) ?: return false
            val ri = r.action.remoteInputs ?: return false
            val intent = Intent()
            val b = Bundle()
            ri.forEach { b.putCharSequence(it.resultKey, text) }
            RemoteInput.addResultsToIntent(ri, intent, b)
            return try {
                r.action.actionIntent.send(ctx, 0, intent); true
            } catch (e: PendingIntent.CanceledException) { false }
        }
    }
}
