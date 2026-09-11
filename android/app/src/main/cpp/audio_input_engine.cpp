#include "audio_input_engine.hpp"

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace kaoss {
namespace {

KaossAudioProcessor g_processor;
std::mutex g_status_mutex;
AudioInputStatus g_status;

std::thread g_fixture_thread;
std::atomic<bool> g_fixture_running{false};

constexpr double kPi = 3.14159265358979323846;

// Deterministic fixture generator for desktop/CI/WASM where no physical input
// exists. It alternates mouth-bass (KICK808), snare noise (SNARE_CLAP) and
// silence so the live DSP path and its status counters stay observable.
void fixture_generate(float* out, std::size_t frames, double sample_rate, std::size_t block) {
  const std::size_t cycle = block % 8;
  for (std::size_t i = 0; i < frames; ++i) {
    double sample = 0.0;
    if (cycle < 3) {
      // Low-frequency mouth bass (~52 Hz) -> KICK808 detection.
      const double t = static_cast<double>(block * frames + i) / sample_rate;
      sample = 0.6 * std::sin(2.0 * kPi * 52.0 * t);
    } else if (cycle == 3 || cycle == 4) {
      // Deterministic pseudo-noise -> SNARE_CLAP detection.
      const std::uint32_t seed = static_cast<std::uint32_t>(block * frames + i);
      const std::uint32_t noise = seed * 1664525U + 1013904223U;
      sample = ((static_cast<double>(noise >> 8) / 16777216.0) - 1.0);
    }
    out[i] = static_cast<float>(sample);
  }
}

void fixture_loop(double sample_rate, std::uint32_t frames) {
  std::vector<float> buffer(static_cast<std::size_t>(frames));
  std::uint64_t block = 0;
  const auto burst = std::chrono::microseconds(
      static_cast<std::uint64_t>((static_cast<double>(frames) / sample_rate) * 1.0e6 * 0.5));
  while (g_fixture_running.load()) {
    fixture_generate(buffer.data(), buffer.size(), sample_rate, block);
    audio_input_processor().process_block(buffer.data(), buffer.size());
    block += 1;
    std::this_thread::sleep_for(burst);
  }
}

void set_status_from_processor() {
  const auto report = g_processor.last_report();
  std::lock_guard<std::mutex> lock(g_status_mutex);
  g_status.blocks = g_processor.blocks();
  g_status.xruns = g_processor.xruns();
  g_status.peak_dbfs = report.peak_dbfs;
  g_status.rms_dbfs = report.rms_dbfs;
  g_status.last_transient = report.transient;
}

}  // namespace

KaossAudioProcessor& audio_input_processor() { return g_processor; }

bool audio_input_start(const AudioInputConfig& config) {
  audio_input_stop();
  g_processor.set_sample_rate(config.sample_rate_hz);
  {
    std::lock_guard<std::mutex> lock(g_status_mutex);
    g_status = AudioInputStatus();
    g_status.sample_rate_hz = config.sample_rate_hz;
    g_status.frames_per_burst = config.frames_per_burst;
  }

#ifdef __ANDROID__
  if (aaudio_start_stream(config)) {
    std::lock_guard<std::mutex> lock(g_status_mutex);
    g_status.running = true;
    g_status.opened = true;
    g_status.native_aaudio = true;
    g_status.exclusive = aaudio_is_exclusive();
    g_status.backend = "aaudio";
    g_status.route = g_status.exclusive ? "aaudio://input/exclusive" : "aaudio://input/shared";
    return true;
  }
  std::lock_guard<std::mutex> lock(g_status_mutex);
  g_status.running = false;
  g_status.opened = false;
  g_status.backend = "audiorecord";
  g_status.route = "audiorecord://fallback";
  return false;  // Kotlin AudioInputController falls back to AudioRecord.
#else
  // Desktop/CI/WASM: deterministic fixture so the contract stays live without
  // physical hardware. Production Android builds take the AAudio branch above.
  g_fixture_running.store(true);
  g_fixture_thread = std::thread(fixture_loop, config.sample_rate_hz, config.frames_per_burst);
  std::lock_guard<std::mutex> lock(g_status_mutex);
  g_status.running = true;
  g_status.opened = true;
  g_status.backend = "fixture";
  g_status.route = "fixture://deterministic/127.0.0.1:8081";
  return true;
#endif
}

void audio_input_stop() {
#ifdef __ANDROID__
  aaudio_stop_stream();
#else
  if (g_fixture_running.exchange(false)) {
    if (g_fixture_thread.joinable()) {
      g_fixture_thread.join();
    }
  }
#endif
  {
    std::lock_guard<std::mutex> lock(g_status_mutex);
    g_status.running = false;
  }
  set_status_from_processor();
}

AudioInputStatus audio_input_status() {
  set_status_from_processor();
  std::lock_guard<std::mutex> lock(g_status_mutex);
#ifdef __ANDROID__
  g_status.exclusive = aaudio_is_exclusive();
  g_status.running = g_status.native_aaudio && g_status.running;
#endif
  return g_status;
}

AudioProcessReport audio_input_push_block(const float* input, std::size_t frames) {
  const auto report = g_processor.process_block(input, frames);
  std::lock_guard<std::mutex> lock(g_status_mutex);
  g_status.running = true;
  g_status.fallback_audiorecord = true;
  g_status.backend = "audiorecord";
  g_status.route = "audiorecord://input/float32";
  g_status.sample_rate_hz = g_status.sample_rate_hz > 0.0 ? g_status.sample_rate_hz : 96000.0;
  g_status.frames_per_burst = static_cast<std::uint32_t>(frames);
  g_status.blocks = g_processor.blocks();
  g_status.xruns = g_processor.xruns();
  g_status.peak_dbfs = report.peak_dbfs;
  g_status.rms_dbfs = report.rms_dbfs;
  g_status.last_transient = report.transient;
  return report;
}

}  // namespace kaoss
