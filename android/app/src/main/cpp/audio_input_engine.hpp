#pragma once

#include "kaoss_audio_processor.hpp"

#include <cstdint>
#include <string>

namespace kaoss {

enum class AudioInputSource : int {
  Auto = 0,
  InternalMic = 1,
  UsbC = 2,
  Bluetooth = 3,
};

struct AudioInputConfig {
  double sample_rate_hz = 96000.0;
  std::uint32_t frames_per_burst = 128;
  AudioInputSource source = AudioInputSource::Auto;
};

struct AudioInputStatus {
  bool running = false;
  bool opened = false;
  bool native_aaudio = false;
  bool exclusive = false;
  bool fallback_audiorecord = false;
  double sample_rate_hz = 0.0;
  std::uint32_t frames_per_burst = 0;
  std::uint64_t blocks = 0;
  std::uint32_t xruns = 0;
  double peak_dbfs = -120.0;
  double rms_dbfs = -120.0;
  std::string last_transient = "NONE";
  std::string backend = "none";  // "aaudio" | "audiorecord" | "fixture"
  std::string route = "none";
};

// ------------------------------------------------------------------------- //
// Cross-platform facade used by JNI / WASM / host tests.
// ------------------------------------------------------------------------- //

// Starts the best available input stream. On Android this opens a real AAudio
// stream; on desktop/CI/WASM it runs the deterministic fixture generator.
// Returns true when an input backend was opened. When Android AAudio cannot
// open, the Kotlin side falls back to an AudioRecord loop that calls
// ``audio_input_push_block`` instead.
bool audio_input_start(const AudioInputConfig& config);
void audio_input_stop();
AudioInputStatus audio_input_status();

// Push a raw Float32 mono block through the shared DSP core. Used by the
// Android AudioRecord fallback (and available to WASM for explicit buffers).
AudioProcessReport audio_input_push_block(const float* input, std::size_t frames);

// Shared DSP core: AAudio callback, AudioRecord fallback and status polling
// observe the same limiter / transient / Kaoss Quad state.
KaossAudioProcessor& audio_input_processor();

#ifdef __ANDROID__
// Implemented in aaudio_input_engine.cpp (NDK ``<aaudio/AAudio.h>``).
bool aaudio_start_stream(const AudioInputConfig& config);
void aaudio_stop_stream();
bool aaudio_is_exclusive();
#endif

}  // namespace kaoss
