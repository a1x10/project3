package com.stels.stella

import android.Manifest
import android.annotation.SuppressLint
import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

/**
 * Клиент очков: полноэкранный WebView с зелёным HUD (/hud на сервере).
 * Камера и микрофон отдаются странице; тачпад дужки приходит как DPAD/Enter/Back и обрабатывается в JS.
 */
class MainActivity : AppCompatActivity() {
    private companion object { const val TAG = "Stella" }
    private lateinit var web: WebView
    private val prefs by lazy { getSharedPreferences("stella", MODE_PRIVATE) }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        Log.i(TAG, "start")
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        web = WebView(this).apply {
            setBackgroundColor(0xFF000000.toInt())
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            webViewClient = object : WebViewClient() {
                override fun onReceivedError(v: WebView, r: android.webkit.WebResourceRequest, e: android.webkit.WebResourceError) {
                    Log.w(TAG, "load error: ${e.description}")
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onPermissionRequest(r: PermissionRequest) = r.grant(r.resources)
            }
        }
        setContentView(web)
        @Suppress("DEPRECATION")
        web.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        requestPermissions(arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO), 1)
    }

    override fun onRequestPermissionsResult(code: Int, p: Array<out String>, r: IntArray) {
        super.onRequestPermissionsResult(code, p, r)
        open()
    }

    private fun open() {
        val url = prefs.getString("url", null)
        if (url == null) askUrl() else web.loadUrl("$url/hud")
    }

    private fun askUrl() {
        val input = EditText(this).apply { hint = "https://stella.example.com" }
        AlertDialog.Builder(this).setTitle("Адрес сервера Stella").setView(input).setCancelable(false)
            .setPositiveButton("OK") { _, _ ->
                prefs.edit().putString("url", input.text.toString().trim().trimEnd('/')).apply(); open()
            }.show()
    }

    override fun onKeyDown(k: Int, e: KeyEvent): Boolean {
        // Back с тачпада отдаём странице как Escape; Menu сбрасывает адрес сервера
        if (k == KeyEvent.KEYCODE_BACK) {
            web.evaluateJavascript("window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))", null); return true
        }
        if (k == KeyEvent.KEYCODE_MENU) { prefs.edit().remove("url").apply(); askUrl(); return true }
        return super.onKeyDown(k, e)
    }

    override fun onResume() { super.onResume(); web.onResume() }
    override fun onPause() { web.onPause(); super.onPause() }
}
