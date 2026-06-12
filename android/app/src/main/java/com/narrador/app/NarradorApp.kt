package com.narrador.app

import androidx.multidex.MultiDexApplication
import com.narrador.app.tts.TtsManager

class NarradorApp : MultiDexApplication() {
    lateinit var tts: TtsManager
        private set

    override fun onCreate() {
        super.onCreate()
        tts = TtsManager(this)
    }
}
