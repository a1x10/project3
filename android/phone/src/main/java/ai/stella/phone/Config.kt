package ai.stella.phone

import android.content.Context

object Config {
    private fun p(c: Context) = c.getSharedPreferences("stella", Context.MODE_PRIVATE)
    fun url(c: Context) = p(c).getString("url", "")!!.trimEnd('/')
    fun key(c: Context) = p(c).getString("key", "")!!
    fun set(c: Context, url: String, key: String) = p(c).edit().putString("url", url).putString("key", key).apply()
    fun configured(c: Context) = url(c).isNotEmpty() && key(c).isNotEmpty()
}
