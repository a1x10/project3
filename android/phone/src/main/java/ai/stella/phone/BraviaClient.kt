package ai.stella.phone

import android.content.Context
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

/**
 * Sony Bravia по домашней сети (REST + IRCC). На телевизоре должно быть включено:
 * Настройки → Сеть → Настройка домашней сети → IP-управление → Аутентификация: «Обычная и Pre-Shared Key»,
 * Pre-Shared Key задать (например 0000), «Простое IP-управление» — вкл.; для включения из режима ожидания — «Удалённый запуск» вкл.
 */
object BraviaClient {
    private val JSON = "application/json".toMediaType()

    private fun base(c: Context) = "http://${Config.tvIp(c)}"

    private fun rpc(c: Context, service: String, method: String, params: JSONArray, version: String = "1.0"): JSONObject {
        val body = JSONObject().put("method", method).put("id", 1).put("params", params).put("version", version)
        val req = Request.Builder().url("${base(c)}/sony/$service")
            .header("X-Auth-PSK", Config.tvKey(c))
            .post(body.toString().toRequestBody(JSON)).build()
        Api.http.newCall(req).execute().use { r ->
            val text = r.body?.string().orEmpty()
            if (!r.isSuccessful) throw RuntimeException("ТВ ответил ${r.code}: проверьте PSK и «IP-управление»")
            val j = JSONObject(text)
            if (j.has("error")) throw RuntimeException("ТВ: ${j.getJSONArray("error")}")
            return j
        }
    }

    /** Коды кнопок пульта берём у самого телевизора, а не из памяти. */
    private val codes = HashMap<String, String>()

    private fun irccCode(c: Context, name: String): String {
        codes[name.lowercase()]?.let { return it }
        val list = rpc(c, "system", "getRemoteControllerInfo", JSONArray()).getJSONArray("result").getJSONArray(1)
        for (i in 0 until list.length()) {
            val o = list.getJSONObject(i)
            codes[o.getString("name").lowercase()] = o.getString("value")
        }
        return codes[name.lowercase()] ?: throw RuntimeException("у ТВ нет кнопки $name")
    }

    private fun ircc(c: Context, name: String) {
        val code = irccCode(c, name)
        val xml = """<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1"><IRCCCode>$code</IRCCCode></u:X_SendIRCC></s:Body></s:Envelope>"""
        val req = Request.Builder().url("${base(c)}/sony/IRCC")
            .header("X-Auth-PSK", Config.tvKey(c))
            .header("SOAPAction", "\"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC\"")
            .post(xml.toRequestBody("text/xml; charset=UTF-8".toMediaType())).build()
        Api.http.newCall(req).execute().use { if (!it.isSuccessful) throw RuntimeException("кнопка $name: ${it.code}") }
    }

    private fun setPower(c: Context, on: Boolean) {
        rpc(c, "system", "setPowerStatus", JSONArray().put(JSONObject().put("status", on)))
    }

    /** Вызов audio-API: версии от новой к старой (код 14 = версия не поддерживается). */
    private fun audio(c: Context, method: String, params: JSONArray): JSONObject {
        var last: RuntimeException? = null
        for (ver in listOf("1.2", "1.1", "1.0")) {
            try { return rpc(c, "audio", method, params, ver) } catch (e: RuntimeException) {
                if (e.message?.contains("[14,") != true) throw e
                last = e
            }
        }
        throw last ?: RuntimeException("audio API недоступен")
    }

    private fun setVolume(c: Context, level: Int) {
        audio(c, "setAudioVolume", JSONArray().put(JSONObject().put("target", "speaker").put("volume", level.toString())))
    }

    /** v: «+5» / «-5» (относительно) или «30» (точно). Относительную считаем сами: этот ТВ воспринимает «-5» как «минимум». */
    private fun volume(c: Context, v: String) {
        val relative = v.startsWith("+") || v.startsWith("-")
        if (!relative) { setVolume(c, v.toIntOrNull()?.coerceIn(0, 100) ?: throw RuntimeException("громкость $v")); return }
        val delta = v.toIntOrNull() ?: throw RuntimeException("громкость $v")
        try {
            val info = audio(c, "getVolumeInformation", JSONArray()).getJSONArray("result").getJSONArray(0)
            var cur = 0; var min = 0; var max = 100
            for (i in 0 until info.length()) {
                val o = info.getJSONObject(i)
                if (o.optString("target") == "speaker" || i == 0) {
                    cur = o.getInt("volume"); min = o.optInt("minVolume", 0); max = o.optInt("maxVolume", 100)
                    if (o.optString("target") == "speaker") break
                }
            }
            setVolume(c, (cur + delta).coerceIn(min, max))
        } catch (e: RuntimeException) {
            // запасной путь: кнопки пульта
            repeat(kotlin.math.abs(delta).coerceAtMost(25)) { ircc(c, if (delta > 0) "VolumeUp" else "VolumeDown"); Thread.sleep(90) }
        }
    }

    private fun input(c: Context, v: String) {
        val uri = when {
            v.startsWith("hdmi") -> "extInput:hdmi?port=${v.removePrefix("hdmi").trim().ifEmpty { "1" }}"
            v == "tv" -> "tv"
            else -> throw RuntimeException("вход «$v» не знаю: hdmi1–hdmi4 или tv")
        }
        rpc(c, "avContent", "setPlayContent", JSONArray().put(JSONObject().put("uri", uri)))
    }

    private fun app(c: Context, name: String) {
        val list = rpc(c, "appControl", "getApplicationList", JSONArray()).getJSONArray("result").getJSONArray(0)
        for (i in 0 until list.length()) {
            val o = list.getJSONObject(i)
            if (o.getString("title").contains(name, ignoreCase = true)) {
                rpc(c, "appControl", "setActiveApp", JSONArray().put(JSONObject().put("uri", o.getString("uri")))); return
            }
        }
        throw RuntimeException("на ТВ нет приложения «$name»")
    }

    private val KEYS = mapOf(
        "home" to "Home", "back" to "Return", "up" to "Up", "down" to "Down", "left" to "Left", "right" to "Right",
        "confirm" to "Confirm", "play" to "Play", "pause" to "Pause", "channel_up" to "ChannelUp", "channel_down" to "ChannelDown",
    )

    /** Возвращает null при успехе или текст ошибки (он уйдёт на очки как алерт). */
    fun run(c: Context, cmd: String, value: String): String? {
        if (Config.tvIp(c).isEmpty()) return "ТВ не настроен: укажите IP и PSK в приложении Stella"
        return try {
            when (cmd) {
                "power_on" -> setPower(c, true)
                "power_off" -> setPower(c, false)
                "volume_up" -> volume(c, "+${value.toIntOrNull() ?: 5}")
                "volume_down" -> volume(c, "-${value.toIntOrNull() ?: 5}")
                "volume_set" -> volume(c, (value.toIntOrNull() ?: 20).coerceIn(0, 100).toString())
                "mute" -> ircc(c, "Mute")
                "input" -> input(c, value.lowercase().replace(" ", ""))
                "app" -> app(c, value)
                "key" -> ircc(c, KEYS[value.lowercase()] ?: throw RuntimeException("кнопка «$value» не знаю"))
                "status" -> rpc(c, "system", "getPowerStatus", JSONArray())
                else -> return "команду ТВ «$cmd» не знаю"
            }
            null
        } catch (e: java.io.IOException) {
            "ТВ не отвечает (${Config.tvIp(c)}): включён ли он и вы в домашней Wi-Fi сети?"
        } catch (e: Exception) {
            e.message ?: "ошибка ТВ"
        }
    }
}
