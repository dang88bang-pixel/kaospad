#pragma once

#include "kaoss_dsp.hpp"

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>

namespace kaoss {

// Result of one real-time audio block pushed through the Kaoss DSP chain.
struct AudioProcessReport {
  double peak_dbfs = -120.0;         // output peak after limiter
  double input_peak_dbfs = -120.0;   // input peak before limiter
  double rms_dbfs = -120.0;
  std::string transient = "NONE";    // "NONE" | "KICK808" | "SNARE_CLAP" | "HAT_ROLL"
  double transient_frequency_hz = 0.0;
  double transient_latency_ms = 0.0;
  bool limiter_active = false;       // true when input exceeded the threshold
  std::uint64_t block_index = 0;
  std::uint64_t checksum = 0;        // FNV-1a over the processed Float32 block
  std::uint32_t frames = 0;
  std::uint32_t kick_total = 0;
  std::uint32_t snare_total = 0;
  std::uint32_t hat_total = 0;
};

// Thread-safe real-time DSP core shared by the AAudio data callback, the
// Android AudioRecord fallback loop and the WASM web fallback. Keeps the exact
// same limiter / transient / Kaoss Quad math as the Python mirror
// (``engines/dsp_chain.py``) so native, browser and CI agree on numbers.
class KaossAudioProcessor {
 public:
  explicit KaossAudioProcessor(double sample_rate_hz = 96000.0,
                               std::uint32_t frames_per_burst = 128);

  void set_sample_rate(double sample_rate_hz);

  // Kaoss Quad control surface (mirrors ``KaossQuadEngine``).
  void set_xy(std::size_t module, float x, float y);
  void freeze(std::size_t module, bool enabled);
  KaossQuadState quad_state() const;

  // Real-time path. May be called from an AAudio data callback / AudioRecord
  // thread / WASM worker. The block is processed in-place on a scratch buffer;
  // no allocation happens on the hot path after the first call.
  AudioProcessReport process_block(const float* input, std::size_t frames);

  // An underrun/glitch/disconnect is signalled by the stream layer.
  void note_xrun();

  // Thread-safe snapshot for UI / status polling.
  AudioProcessReport last_report() const;
  std::uint64_t blocks() const;
  std::uint32_t xruns() const;

  void reset();

 private:
  mutable std::mutex mutex_;
  KaossQuadEngine quad_;
  double sample_rate_hz_;
  std::uint32_t frames_per_burst_;
  std::uint64_t blocks_ = 0;
  std::uint32_t xruns_ = 0;
  std::uint32_t kick_ = 0;
  std::uint32_t snare_ = 0;
  std::uint32_t hat_ = 0;
  AudioProcessReport last_;
  mutable std::vector<float> scratch_;
};

}  // namespace kaoss
