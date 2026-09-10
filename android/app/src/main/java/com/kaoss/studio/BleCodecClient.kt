package com.kaoss.studio

/** Client BLE codec negotiator (LC3plus preferred). */
object BleCodecClient {
    fun negotiate(preferred: String = "lc3plus"): String {
        val codec = when (preferred) {
            "sbc" -> Triple("sbc", 40.0, 328)
            "aac" -> Triple("aac", 30.0, 256)
            "lc3" -> Triple("lc3", 20.0, 64)
            else -> Triple("lc3plus", 15.0, 96)
        }
        return "{\"ok\":true,\"selected\":\"${codec.first}\",\"latency_ms\":${codec.second},\"bitrate_kbps\":${codec.third},\"permissions\":[\"BLUETOOTH_CONNECT\",\"BLUETOOTH_SCAN\"]}"
    }
}
