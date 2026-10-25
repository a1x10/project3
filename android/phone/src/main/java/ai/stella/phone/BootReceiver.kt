package ai.stella.phone

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        if (Config.configured(c)) c.startForegroundService(Intent(c, StellaService::class.java))
    }
}
