package com.narrador.app.browser

import android.webkit.JavascriptInterface
import android.webkit.WebView
import com.narrador.app.NarradorApp
import org.json.JSONObject

class NarradorJsInterface(
    private val app: NarradorApp,
    private val webViewProvider: () -> WebView?,
    private val isNarrationEnabled: () -> Boolean,
) {
    @JavascriptInterface
    fun isEnabled(): Boolean = isNarrationEnabled()

    @JavascriptInterface
    fun speak(text: String, lang: String, rate: Float, pitch: Float, volume: Float, utteranceId: String) {
        if (!isNarrationEnabled() || text.isBlank()) {
            notifyDone(utteranceId)
            return
        }
        app.tts.langTag = lang.ifBlank { "es-ES" }
        app.tts.rate = rate
        app.tts.pitch = pitch
        app.tts.volume = volume
        app.tts.speak(text) {
            notifyDone(utteranceId)
        }
    }

    @JavascriptInterface
    fun cancel() {
        app.tts.stop()
    }

    @JavascriptInterface
    fun log(message: String) {
        android.util.Log.d("NarradorJS", message)
    }

    @JavascriptInterface
    fun getSettings(): String {
        return JSONObject()
            .put("enabled", isNarrationEnabled())
            .put("lang", app.tts.langTag)
            .put("rate", app.tts.rate.toDouble())
            .put("videoDuckVolume", 0.15)
            .toString()
    }

    private fun notifyDone(utteranceId: String) {
        val safe = utteranceId.replace("'", "\\'")
        webViewProvider()?.post {
            webViewProvider()?.evaluateJavascript(
                "window.NarradorHost && window.NarradorHost.onNativeSpeakDone('$safe');",
                null
            )
        }
    }
}
