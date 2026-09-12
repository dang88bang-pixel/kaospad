// Host test for the portable audio-input -> DSP core.
//
// Verifies the same code path the Android AAudio callback / AudioRecord loop
// and the WASM web fallback use: limiter, transient splitter, determinism and
// the cross-platform input-engine facade (deterministic fixture on hosts).
// Compiles with a plain C++17 compiler (no Android NDK, no Emscripten); see the
// `build` target in the Makefile for the exact invocation.

#include "audio_input_engine.hpp"

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

namespace {

int checks = 0;

void check(const std::string& label, bool condition, const std::string& detail = "") {
  if (!condition) {
    std::cerr << "FAIL: " << label << (detail.empty() ? "" : " // " + detail) << "\n";
    std::exit(EXIT_FAILURE);
  }
  checks += 1;
}

std::vector<float> sine(float freq, double sample_rate, std::size_t frames, float amp = 0.6F) {
  std::vector<float> out(frames);
  for (std::size_t i = 0; i < frames; ++i) {
    out[i] = amp * std::sin(2.0 * 3.14159265358979323846 * freq * (static_cast<double>(i) / sample_rate));
  }
  return out;
}

std::vector<float> noise(std::size_t frames) {
  std::vector<float> out(frames);
  std::uint32_t state = 0x12345678U;
  for (std::size_t i = 0; i < frames; ++i) {
    state = state * 1664525U + 1013904223U;
    out[i] = static_cast<float>((static_cast<double>(state >> 8) / 16777216.0) - 1.0);
  }
  return out;
}

std::vector<float> silence(std::size_t frames) { return std::vector<float>(frames, 0.0F); }

}  // namespace

int main() {
  // 1. Limiter contract: brutal full-scale input must come out at <= -3.2 dBFS.
  {
    kaoss::KaossAudioProcessor proc(96000.0, 128);
    std::vector<float> brutal(128);
    for (int i = 0; i < 128; ++i) {
      brutal[i] = (i % 2 == 0 ? 1.0F : -1.0F);
    }
    const auto report = proc.process_block(brutal.data(), brutal.size());
    check("limiter peak <= -3.2 dBFS", report.peak_dbfs <= -3.2 + 0.01,
          "peak=" + std::to_string(report.peak_dbfs));
    check("limiter active on overs", report.limiter_active, "input_peak=" + std::to_string(report.input_peak_dbfs));
    check("block index increments", report.block_index == 1, "block_index=" + std::to_string(report.block_index));
  }

  // 2. Transient splitter: 52 Hz mouth bass -> KICK808, noise -> SNARE_CLAP.
  {
    kaoss::KaossAudioProcessor proc(48000.0, 512);
    const auto kick = proc.process_block(sine(52.0, 48000.0, 512).data(), 512);
    check("mouth bass -> KICK808", kick.transient == "KICK808", kick.transient);
    check("kick frequency ~52 Hz", std::abs(kick.transient_frequency_hz - 52.0) < 1.0,
          std::to_string(kick.transient_frequency_hz));
    const auto snare = proc.process_block(noise(512).data(), 512);
    check("noise -> SNARE_CLAP", snare.transient == "SNARE_CLAP", snare.transient);
    const auto rest = proc.process_block(silence(512).data(), 512);
    check("silence -> NONE", rest.transient == "NONE", rest.transient);
    check("transient counters", proc.last_report().kick_total == 1 && proc.last_report().snare_total == 1,
          "kick=" + std::to_string(proc.last_report().kick_total) +
              " snare=" + std::to_string(proc.last_report().snare_total));
  }

  // 3. Determinism: identical blocks -> identical checksum; counter advances.
  {
    kaoss::KaossAudioProcessor proc(96000.0, 128);
    const auto block = sine(52.0, 96000.0, 128, 0.4F);
    const auto first = proc.process_block(block.data(), block.size());
    const auto second = proc.process_block(block.data(), block.size());
    check("deterministic checksum", first.checksum == second.checksum,
          std::to_string(first.checksum) + " vs " + std::to_string(second.checksum));
    check("blocks advance", proc.blocks() == 2, std::to_string(proc.blocks()));
  }

  // 4. Kaoss Quad control surfaces forwarded through the processor.
  {
    kaoss::KaossAudioProcessor proc(48000.0, 128);
    proc.set_xy(0, 0.9F, 0.1F);
    proc.freeze(0, true);
    const auto state = proc.quad_state();
    check("xy forwarded", std::abs(state.x[0] - 0.9F) < 1e-4F && std::abs(state.y[0] - 0.1F) < 1e-4F,
          "x=" + std::to_string(state.x[0]) + " y=" + std::to_string(state.y[0]));
    check("freeze forwarded", state.frozen[0], "frozen=" + std::to_string(state.frozen[0]));
    // A frozen module ignores later XY movement (Kaoss Quad semantics).
    proc.set_xy(0, 0.2F, 0.8F);
    check("frozen module holds xy", std::abs(proc.quad_state().x[0] - 0.9F) < 1e-4F,
          "x=" + std::to_string(proc.quad_state().x[0]));
  }

  // 5. Cross-platform input facade (deterministic fixture on this host).
  {
    kaoss::AudioInputConfig cfg;
    cfg.sample_rate_hz = 48000.0;
    cfg.frames_per_burst = 128;
    cfg.source = kaoss::AudioInputSource::InternalMic;
    check("fixture start returns true", kaoss::audio_input_start(cfg));
    std::this_thread::sleep_for(std::chrono::milliseconds(120));
    const auto status = kaoss::audio_input_status();
    check("fixture running", status.running, "backend=" + status.backend);
    check("fixture processed blocks", status.blocks > 0, "blocks=" + std::to_string(status.blocks));
    kaoss::audio_input_stop();
    const auto stopped = kaoss::audio_input_status();
    check("fixture stopped", !stopped.running, "running=" + std::to_string(stopped.running));
  }

  // 6. Xrun accounting via the shared processor.
  {
    kaoss::KaossAudioProcessor proc(48000.0, 128);
    proc.note_xrun();
    proc.note_xrun();
    check("xrun counter", proc.xruns() == 2, std::to_string(proc.xruns()));
    proc.reset();
    check("reset clears xruns", proc.xruns() == 0 && proc.blocks() == 0,
          "xruns=" + std::to_string(proc.xruns()));
  }

  std::cout << "audio input processor + engine fixture verified: " << checks << " checks\n";
  return EXIT_SUCCESS;
}
