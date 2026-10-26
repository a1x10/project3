package ai.stella.phone

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    private lateinit var status: TextView

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(pad, pad, pad, pad) }
        val scroll = android.widget.ScrollView(this).apply { addView(root) }
        val url = EditText(this).apply { hint = "https://stella.example.com"; setText(Config.url(this@MainActivity)) }
        val key = EditText(this).apply { hint = "STELLA_API_KEY"; setText(Config.key(this@MainActivity)) }
        val tvIp = EditText(this).apply { hint = "IP телевизора, например 192.168.1.50"; setText(Config.tvIp(this@MainActivity)) }
        val tvKey = EditText(this).apply { hint = "Pre-Shared Key телевизора (PSK)"; setText(Config.tvKey(this@MainActivity)) }
        status = TextView(this)
        fun btn(t: String, f: () -> Unit) = Button(this).apply { text = t; setOnClickListener { f() } }

        root.addView(TextView(this).apply { text = "Stella — мост между очками, мессенджерами и сервером"; textSize = 18f })
        root.addView(url); root.addView(key)
        root.addView(TextView(this).apply { text = "\nТелевизор Sony Bravia (по желанию):" })
        root.addView(tvIp); root.addView(tvKey)
        root.addView(btn("1. Сохранить и запустить") {
            Config.set(this, url.text.toString().trim(), key.text.toString().trim())
            Config.setTv(this, tvIp.text.toString().trim(), tvKey.text.toString().trim())
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
            startForegroundService(Intent(this, StellaService::class.java)); refresh()
        })
        root.addView(btn("2. Доступ к уведомлениям") { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) })
        root.addView(btn("3. Специальные возможности (голосовые WhatsApp)") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) })
        root.addView(btn("4. Поверх других окон") {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
        })
        root.addView(btn("5. Не усыплять приложение") {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        })
        root.addView(status)
        setContentView(scroll)
    }

    override fun onResume() { super.onResume(); refresh() }

    private fun refresh() {
        val listener = NotifListener.instance != null
        val a11y = VoiceSendService.instance != null
        status.text = "\nСервер: ${if (Config.configured(this)) Config.url(this) else "не задан"}" +
            "\nУведомления: ${if (listener) "ок" else "нет доступа"}" +
            "\nГолосовые WhatsApp: ${if (a11y) "ок" else "не включено"}"
    }
}
