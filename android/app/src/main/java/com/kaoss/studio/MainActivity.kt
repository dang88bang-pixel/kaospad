package com.kaoss.studio

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val view = TextView(this)
        view.text = "Korg Kaoss AI Beatbox Studio // Offline Localhost IPC"
        view.textSize = 20f
        view.setTextColor(0xffff7a00.toInt())
        setContentView(view)
    }
}
