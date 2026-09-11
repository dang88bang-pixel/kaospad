package com.kaoss.studio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Live audio-input -> DSP controller (Phase A).
 *
 * Strategy:
 *  1. Native AAudio (JNI -> libkaoss_native): Exclusive/LowLatency Float32
 *     stream whose data callback runs the DSP inside the audio callback.
 *  2. If AAudio cannot open (device HAL, permissions), fall back to an
 *     [AudioRecord] capture loop that pushes every Float32 block through
 *     [KaossNative.processAudioBlock] so the same limiter / transient /
 *     Kaoss Quad core runs regardless of backend.
 */
class AudioInputController(private val context: Context) {

    companion object {
        const val SOURCE_AUTO = 0
        const val SOURCE_INTERNAL_MIC = 1
        const val SOURCE_USB_C = 2
        const val SOURCE_BLUETOOTH = 3
    }

    private val running = AtomicBoolean(false)
    @Volatile private var fallbackActive = false
    @Volatile private var fallbackBlocks = 0L
    @Volatile private var fallbackXruns = 0
    @Volatile private var fallbackSampleRate = 0
    @Volatile private var fallbackFrames = 0
    private var record: AudioRecord? = null
    private var captureThread: Thread? = null

    fun hasRecordPermission(): Boolean =
        context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    fun start(sampleRateHz: Int, framesPerBurst: Int, source: Int): String {
        if (!hasRecordPermission()) {
            return json {
                put("started", false)
                put("reason", "RECORD_AUDIO not granted")
                put("backend", "none")
            }
        }
        stop()

        // 1) Native AAudio stream (preferred low-latency path).
        val native = try {
            JSONObject(KaossNative.startAudioInput(sampleRateHz.toDouble(), framesPerBurst, source))
        } catch (t: Throwable) {
            null
        }
        if (native?.optBoolean("started", false) == true) {
            running.set(true)
            return native.toString()
        }

        // 2) AudioRecord fallback.
        return startAudioRecord(sampleRateHz, framesPerBurst, source)
    }

    private fun startAudioRecord(sampleRateHz: Int, frames: Int, source: Int): String {
        val encoding = AudioFormat.ENCODING_PCM_FLOAT
        val minBuffer = AudioRecord.getMinBufferSize(sampleRateHz, AudioFormat.CHANNEL_IN_MONO, encoding)
        val bufferSize = maxOf(minBuffer, frames * 4)
        val record = AudioRecord(
            MediaRecorder.AudioSource.UNPROCESSED,
            sampleRateHz,
            AudioFormat.CHANNEL_IN_MONO,
            encoding,
            bufferSize,
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            return json {
                put("started", false)
                put("reason", "AudioRecord not initialized")
                put("backend", "audiorecord")
            }
        }

        record.startRecording()
        this.record = record
        fallbackActive = true
        fallbackSampleRate = sampleRateHz
        fallbackFrames = frames
        running.set(true)

        captureThread = Thread({
            val pcm = FloatArray(frames)
            while (fallbackActive) {
                val read = record.read(pcm, 0, frames, AudioRecord.READ_BLOCKING)
                when {
                    read <= 0 -> fallbackXruns++
                    read < frames -> {
                        fallbackXruns++
                        KaossNative.processAudioBlock(pcm.copyOf(read.coerceAtLeast(0)))
                    }
                    else -> KaossNative.processAudioBlock(pcm)
                }
                fallbackBlocks++
            }
        }, "kaoss-audiorecord-capture").also { it.start() }

        return json {
            put("started", true)
            put("native_aaudio", false)
            put("exclusive", false)
            put("fallback_audiorecord", true)
            put("backend", "audiorecord")
            put("route", "audiorecord://input/float32")
            put("sample_rate_hz", sampleRateHz)
            put("frames_per_burst", frames)
        }
    }

    fun status(): String {
        val obj = try {
            JSONObject(KaossNative.audioInputStatus())
        } catch (t: Throwable) {
            JSONObject()
        }
        obj.put("fallback_audiorecord", fallbackActive)
        obj.put("fallback_blocks", fallbackBlocks)
        obj.put("fallback_xruns", fallbackXruns)
        obj.put("permission_record_audio", hasRecordPermission())
        return obj.toString()
    }

    fun stop() {
        running.set(false)
        fallbackActive = false
        captureThread?.join(500)
        captureThread = null
        record?.let {
            runCatching { it.stop() }
            it.release()
        }
        record = null
        fallbackBlocks = 0
        fallbackXruns = 0
        KaossNative.stopAudioInput()
    }

    private inline fun json(block: JSONObject.() -> Unit): String =
        JSONObject().apply(block).toString()
}
