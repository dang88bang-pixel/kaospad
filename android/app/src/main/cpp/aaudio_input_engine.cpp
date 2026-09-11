// Real AAudio input stream for Android (NDK r26+, minSdk 26).
//
// Opens a Float32 mono input stream with LowLatency performance and prefers
// Exclusive sharing mode (falls back to Shared). The data callback pushes every
// block through the shared KaossAudioProcessor so the live DSP path (limiter,
// transient splitter, Kaoss Quad) runs inside the audio callback — this is the
// native half of Phase A "AudioRecord/AAudio Input an den DSP anschließen".
//
// On non-Android hosts this translation unit is compiled away (see
// ``audio_input_engine.cpp`` for the deterministic fixture used by CI/WASM).

#ifdef __ANDROID__

#include "audio_input_engine.hpp"

#include <aaudio/AAudio.h>

#include <atomic>
#include <cstdint>

namespace kaoss {
namespace {

AAudioStream* g_stream = nullptr;
std::atomic<bool> g_aaudio_running{false};
std::atomic<std::uint32_t> g_aaudio_xruns{0};

aaudio_data_callback_result_t on_audio_ready(AAudioStream* stream, void* user_data,
                                             void* audio_data, int32_t num_frames) {
  (void)stream;
  (void)user_data;
  if (audio_data != nullptr && num_frames > 0) {
    audio_input_processor().process_block(static_cast<const float*>(audio_data),
                                          static_cast<std::size_t>(num_frames));
  } else {
    // Null buffer or zero frames means an underrun/glitch on the input side.
    audio_input_processor().note_xrun();
    g_aaudio_xruns.fetch_add(1);
  }
  return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

void on_stream_error(AAudioStream* stream, void* user_data, aaudio_result_t error) {
  (void)stream;
  (void)user_data;
  if (error == AAUDIO_ERROR_DISCONNECTED) {
    // USB device pulled / BT link lost: signal a dropout and stop cleanly.
    audio_input_processor().note_xrun();
    g_aaudio_running.store(false);
  }
}

}  // namespace

bool aaudio_start_stream(const AudioInputConfig& config) {
  AAudioStreamBuilder* builder = nullptr;
  aaudio_result_t result = AAudio_createStreamBuilder(&builder);
  if (result != AAUDIO_OK || builder == nullptr) {
    return false;
  }

  AAudioStreamBuilder_setDirection(builder, AAUDIO_DIRECTION_INPUT);
  AAudioStreamBuilder_setFormat(builder, AAUDIO_FORMAT_PCM_FLOAT);
  AAudioStreamBuilder_setChannelCount(builder, 1);
  AAudioStreamBuilder_setSampleRate(builder, static_cast<int32_t>(config.sample_rate_hz));
  AAudioStreamBuilder_setFramesPerDataCallback(builder, static_cast<int32_t>(config.frames_per_burst));
  AAudioStreamBuilder_setPerformanceMode(builder, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
  AAudioStreamBuilder_setSharingMode(builder, AAUDIO_SHARING_MODE_EXCLUSIVE);
  AAudioStreamBuilder_setDataCallback(builder, on_audio_ready, nullptr);
  AAudioStreamBuilder_setErrorCallback(builder, on_stream_error, nullptr);

  result = AAudioStreamBuilder_openStream(builder, &g_stream);
  if (result != AAUDIO_OK && result != AAUDIO_ERROR_UNAVAILABLE && result != AAUDIO_ERROR_TIMEOUT) {
    // Exclusive mode is not always offered by the device HAL: retry shared.
    AAudioStreamBuilder_setSharingMode(builder, AAUDIO_SHARING_MODE_SHARED);
    result = AAudioStreamBuilder_openStream(builder, &g_stream);
  }
  AAudioStreamBuilder_delete(builder);

  if (result != AAUDIO_OK || g_stream == nullptr) {
    g_stream = nullptr;
    return false;
  }

  result = AAudioStream_requestStart(g_stream);
  if (result != AAUDIO_OK) {
    AAudioStream_close(g_stream);
    g_stream = nullptr;
    return false;
  }

  g_aaudio_running.store(true);
  g_aaudio_xruns.store(0);
  return true;
}

void aaudio_stop_stream() {
  if (g_stream != nullptr) {
    g_aaudio_running.store(false);
    AAudioStream_requestStop(g_stream);
    AAudioStream_close(g_stream);
    g_stream = nullptr;
  }
}

bool aaudio_is_exclusive() {
  if (g_stream == nullptr) {
    return false;
  }
  return AAudioStream_getSharingMode(g_stream) == AAUDIO_SHARING_MODE_EXCLUSIVE;
}

}  // namespace kaoss

#endif  // __ANDROID__
