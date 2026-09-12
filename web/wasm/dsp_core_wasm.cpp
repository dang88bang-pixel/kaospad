// Emscripten entry point for the portable Kaoss DSP core.
//
// Exposes the exact same limiter / transient / Kaoss Quad math that runs in the
// Android AAudio callback and the AudioRecord loop as a WASM module, so the
// browser path computes identical numbers. Built by scripts/build_wasm.sh:
//
//   emcc web/wasm/dsp_core_wasm.cpp <portable core .cpp files> \
//        -Iandroid/app/src/main/cpp ...
//
// The web UI falls back to a pure-JS mirror (web/src/dsp-core.js) whenever the
// WASM module cannot be loaded (offline cache miss, missing Emscripten build).

#include <emscripten/emscripten.h>

#include <cstdint>
#include <cstring>
#include <vector>

#include "kaoss_audio_processor.hpp"
#include "kaoss_dsp.hpp"

namespace {

kaoss::KaossAudioProcessor g_processor(96000.0, 128);

int transient_to_int(const kaoss::TransientEvent::Kind kind) {
  switch (kind) {
    case kaoss::TransientEvent::Kind::Kick808:
      return 1;
    case kaoss::TransientEvent::Kind::SnareClap:
      return 2;
    case kaoss::TransientEvent::Kind::HatRoll:
      return 3;
    case kaoss::TransientEvent::Kind::None:
    default:
      return 0;
  }
}

std::vector<float> copy_input(const float* data, int len) {
  std::vector<float> pcm(static_cast<std::size_t>(len));
  if (len > 0 && data != nullptr) {
    std::memcpy(pcm.data(), data, sizeof(float) * static_cast<std::size_t>(len));
  }
  return pcm;
}

}  // namespace

extern "C" {

// Peak after the brickwall soft-knee limiter (dBFS).
EMSCRIPTEN_KEEPALIVE
float kaoss_wasm_limiter_peak(const float* data, int len) {
  if (len <= 0 || data == nullptr) {
    return -120.0F;
  }
  const auto limited = kaoss::brickwall_soft_knee_buffer(copy_input(data, len));
  return kaoss::peak_dbfs(limited);
}

// Transient splitter. kind_out: 0 none, 1 kick, 2 snare, 3 hat.
EMSCRIPTEN_KEEPALIVE
void kaoss_wasm_detect_transient(const float* data, int len, double sample_rate, int* kind_out,
                                 double* frequency_out, double* latency_out) {
  const auto event = kaoss::detect_mouth_transient(copy_input(data, len), sample_rate);
  if (kind_out != nullptr) {
    *kind_out = transient_to_int(event.kind);
  }
  if (frequency_out != nullptr) {
    *frequency_out = event.frequency_hz;
  }
  if (latency_out != nullptr) {
    *latency_out = event.detection_latency_ms;
  }
}

// Full block through the shared processor: limiter + transient + Kaoss Quad.
// Returns the output peak (dBFS); out_transient receives the kind int.
EMSCRIPTEN_KEEPALIVE
float kaoss_wasm_process_block(const float* data, int len, double sample_rate, int* out_transient) {
  if (len <= 0 || data == nullptr) {
    if (out_transient != nullptr) {
      *out_transient = 0;
    }
    return -120.0F;
  }
  g_processor.set_sample_rate(sample_rate);
  const auto pcm = copy_input(data, len);
  const auto report = g_processor.process_block(pcm.data(), pcm.size());
  if (out_transient != nullptr) {
    *out_transient = transient_to_int(
        report.transient == "KICK808"      ? kaoss::TransientEvent::Kind::Kick808
        : report.transient == "SNARE_CLAP" ? kaoss::TransientEvent::Kind::SnareClap
        : report.transient == "HAT_ROLL"   ? kaoss::TransientEvent::Kind::HatRoll
                                           : kaoss::TransientEvent::Kind::None);
  }
  return static_cast<float>(report.peak_dbfs);
}

EMSCRIPTEN_KEEPALIVE
void kaoss_wasm_set_xy(int module, float x, float y) {
  if (module >= 0 && module < 4) {
    g_processor.set_xy(static_cast<std::size_t>(module), x, y);
  }
}

EMSCRIPTEN_KEEPALIVE
void kaoss_wasm_freeze(int module, int enabled) {
  if (module >= 0 && module < 4) {
    g_processor.freeze(static_cast<std::size_t>(module), enabled != 0);
  }
}

// Synthesize a KICK808 voice into a caller-owned buffer; returns frames written.
EMSCRIPTEN_KEEPALIVE
int kaoss_wasm_synth_808(double sample_rate, double duration_ms, float* out, int max_len) {
  if (out == nullptr || max_len <= 0) {
    return 0;
  }
  kaoss::TransientEvent event;
  event.kind = kaoss::TransientEvent::Kind::Kick808;
  event.frequency_hz = 52.0;
  const auto voice = kaoss::synthesize_808(event, sample_rate, duration_ms);
  const int frames = static_cast<int>(voice.size() < static_cast<std::size_t>(max_len)
                                          ? voice.size()
                                          : static_cast<std::size_t>(max_len));
  std::memcpy(out, voice.data(), sizeof(float) * static_cast<std::size_t>(frames));
  return frames;
}

}  // extern "C"
