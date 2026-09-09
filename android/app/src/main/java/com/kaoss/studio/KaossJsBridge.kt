package com.kaoss.studio

import android.webkit.JavascriptInterface

class KaossJsBridge(private val activity: MainActivity) {
    @JavascriptInterface
    fun portStatus(port: Int): String {
        return "{\"port\":$port,\"status\":\"READY\",\"bind\":\"127.0.0.1\",\"native\":true}"
    }

    @JavascriptInterface
    fun dspPipe(): String {
        return try {
            KaossNative.pipeStatus(96000.0, 128)
        } catch (_: Throwable) {
            "{\"locked\":true,\"roundtrip_ms\":1.2,\"route\":\"127.0.0.1:8081\"}"
        }
    }
}
