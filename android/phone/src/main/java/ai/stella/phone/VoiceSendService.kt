package ai.stella.phone

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.core.content.FileProvider
import java.io.File

/**
 * Отправка голосового в WhatsApp: делится аудио через системный Share, затем сама выбирает контакт
 * и жмёт «Отправить». Это автоматизация интерфейса — может ломаться после обновлений WhatsApp.
 * Нужны: специальные возможности (включить сервис) и «Поверх других окон».
 */
class VoiceSendService : AccessibilityService() {
    override fun onServiceConnected() { instance = this }
    override fun onUnbind(intent: Intent?): Boolean { instance = null; return super.onUnbind(intent) }
    override fun onInterrupt() {}

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        val job = pending ?: return
        if (System.currentTimeMillis() - job.started > 25_000) { pending = null; return }
        val root = rootInActiveWindow ?: return
        when (job.step) {
            0 -> { // экран выбора контакта: ищем имя и жмём
                val node = root.findAccessibilityNodeInfosByText(job.sender).firstOrNull() ?: return
                if (clickUp(node)) job.step = 1
            }
            1 -> { // экран подтверждения: кнопка отправки
                val send = findSend(root) ?: return
                if (clickUp(send)) { pending = null }
            }
        }
    }

    private fun findSend(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        for (label in listOf("Send", "Отправить")) {
            root.findAccessibilityNodeInfosByText(label).firstOrNull { it.isClickable || it.parent?.isClickable == true }
                ?.let { return it }
        }
        return null
    }

    private fun clickUp(n: AccessibilityNodeInfo): Boolean {
        var cur: AccessibilityNodeInfo? = n
        while (cur != null) {
            if (cur.isClickable) return cur.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            cur = cur.parent
        }
        return false
    }

    private class Job(val sender: String, val started: Long, var step: Int = 0)

    companion object {
        @Volatile var instance: VoiceSendService? = null
        @Volatile private var pending: Job? = null

        fun sendVoice(ctx: Context, sender: String, file: File) {
            if (instance == null) return   // сервис специальных возможностей не включён
            val uri = FileProvider.getUriForFile(ctx, "ai.stella.phone.files", file)
            pending = Job(sender, System.currentTimeMillis())
            ctx.startActivity(Intent(Intent.ACTION_SEND).apply {
                type = "audio/ogg"; `package` = "com.whatsapp"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            })
        }
    }
}
