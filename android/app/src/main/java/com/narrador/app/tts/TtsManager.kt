package com.narrador.app.tts

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

class TtsManager(context: Context) : TextToSpeech.OnInitListener {

    private val appContext = context.applicationContext
    private var tts: TextToSpeech? = null
    private var ready = false
    private val utteranceSeq = AtomicInteger(0)
    private val callbacks = ConcurrentHashMap<String, () -> Unit>()

    var rate: Float = 1f
        set(value) {
            field = value.coerceIn(0.5f, 2f)
        }

    var pitch: Float = 1f
        set(value) {
            field = value.coerceIn(0.5f, 2f)
        }

    var volume: Float = 1f
        set(value) {
            field = value.coerceIn(0f, 1f)
        }

    var langTag: String = "es-ES"
        set(value) {
            field = value
            applyLocale()
        }

    init {
        tts = TextToSpeech(appContext, this)
    }

    override fun onInit(status: Int) {
        ready = status == TextToSpeech.SUCCESS
        if (ready) {
            applyLocale()
            tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) {}

                override fun onDone(utteranceId: String?) {
                    utteranceId?.let { id ->
                        callbacks.remove(id)?.invoke()
                    }
                }

                @Deprecated("Deprecated in Java")
                override fun onError(utteranceId: String?) {
                    onDone(utteranceId)
                }

                override fun onError(utteranceId: String?, errorCode: Int) {
                    onDone(utteranceId)
                }
            })
        } else {
            Log.e(TAG, "TextToSpeech init failed: $status")
        }
    }

    private fun applyLocale() {
        val t = tts ?: return
        val parts = langTag.split("-", "_")
        val locale = when (parts.size) {
            1 -> Locale(parts[0])
            else -> Locale(parts[0], parts[1])
        }
        t.language = locale
    }

    fun isReady(): Boolean = ready

    fun speak(text: String, onDone: (() -> Unit)? = null): String {
        val id = "narrador-${utteranceSeq.incrementAndGet()}"
        if (!ready || text.isBlank()) {
            onDone?.invoke()
            return id
        }
        onDone?.let { callbacks[id] = it }
        val t = tts ?: return id
        t.stop()
        val params = Bundle()
        params.putFloat(TextToSpeech.Engine.KEY_PARAM_VOLUME, volume)
        t.setSpeechRate(rate)
        t.setPitch(pitch)
        @Suppress("DEPRECATION")
        t.speak(text, TextToSpeech.QUEUE_FLUSH, params, id)
        return id
    }

    fun stop() {
        callbacks.clear()
        tts?.stop()
    }

    fun shutdown() {
        stop()
        tts?.shutdown()
        tts = null
        ready = false
    }

    companion object {
        private const val TAG = "TtsManager"
    }
}
