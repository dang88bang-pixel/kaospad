package com.kaoss.studio

object KaossNative {
    init {
        try {
            System.loadLibrary("kaoss_native")
        } catch (_: UnsatisfiedLinkError) {
            // Unit tests and desktop preview run without the NDK .so.
        }
    }

    @JvmStatic external fun pipeStatus(sampleRate: Double, frames: Int): String
    @JvmStatic external fun limiterPeak(input: FloatArray): Float
    @JvmStatic external fun detectTransient(input: FloatArray, sampleRate: Double): String
    @JvmStatic external fun oboeExclusive(sampleRate: Double, frames: Int): String

    // Live Audio-Input -> DSP (Phase A): AAudio-first, AudioRecord fallback.
    @JvmStatic external fun startAudioInput(sampleRate: Double, frames: Int, source: Int): String
    @JvmStatic external fun stopAudioInput()
    @JvmStatic external fun audioInputStatus(): String
    @JvmStatic external fun processAudioBlock(input: FloatArray): String
}
