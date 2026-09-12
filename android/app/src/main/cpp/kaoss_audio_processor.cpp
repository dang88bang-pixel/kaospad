#include "kaoss_audio_processor.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace kaoss {
namespace {

std::uint64_t fnv1a_float_block(const std::vector<float>& block) {
  std::uint64_t hash = 0xcbf29ce484222325ULL;
  for (const float sample : block) {
    std::uint32_t bits = 0;
    static_assert(sizeof(bits) == sizeof(sample), "float and uint32_t must match");
    std::memcpy(&bits, &sample, sizeof(bits));
    for (int shift = 0; shift < 32; shift += 8) {
      hash ^= static_cast<std::uint8_t>((bits >> shift) & 0xffU);
      hash *= 0x100000001b3ULL;
    }
  }
  return hash;
}

const char* transient_kind_name(TransientEvent::Kind kind) {
  switch (kind) {
    case TransientEvent::Kind::Kick808:
      return "KICK808";
    case TransientEvent::Kind::SnareClap:
      return "SNARE_CLAP";
    case TransientEvent::Kind::HatRoll:
      return "HAT_ROLL";
    case TransientEvent::Kind::None:
    default:
      return "NONE";
  }
}

}  // namespace

KaossAudioProcessor::KaossAudioProcessor(double sample_rate_hz, std::uint32_t frames_per_burst)
    : sample_rate_hz_(sample_rate_hz), frames_per_burst_(frames_per_burst) {
  scratch_.resize(static_cast<std::size_t>(frames_per_burst));
}

void KaossAudioProcessor::set_sample_rate(double sample_rate_hz) {
  std::lock_guard<std::mutex> lock(mutex_);
  sample_rate_hz_ = sample_rate_hz;
}

void KaossAudioProcessor::set_xy(std::size_t module, float x, float y) {
  std::lock_guard<std::mutex> lock(mutex_);
  quad_.set_xy(module, x, y);
}

void KaossAudioProcessor::freeze(std::size_t module, bool enabled) {
  std::lock_guard<std::mutex> lock(mutex_);
  quad_.freeze(module, enabled);
}

KaossQuadState KaossAudioProcessor::quad_state() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return quad_.state();
}

AudioProcessReport KaossAudioProcessor::process_block(const float* input, std::size_t frames) {
  if (frames == 0 || input == nullptr) {
    note_xrun();
    return last_report();
  }

  // Copy the input once so the Kaoss Quad engine can run on its own buffer.
  scratch_.assign(input, input + frames);
  const auto transient = detect_mouth_transient(scratch_, sample_rate_hz_);
  float input_peak = 0.0F;
  double rms_sum = 0.0;
  for (const float sample : scratch_) {
    input_peak = std::max(input_peak, std::abs(sample));
    rms_sum += static_cast<double>(sample) * static_cast<double>(sample);
  }

  const auto processed = quad_.process(scratch_);
  const double output_peak = static_cast<double>(peak_dbfs(processed));

  AudioProcessReport report;
  report.input_peak_dbfs = input_peak > 0.0F ? 20.0 * std::log10(input_peak) : -120.0;
  report.peak_dbfs = output_peak;
  report.rms_dbfs = rms_sum > 0.0 ? 10.0 * std::log10(rms_sum / static_cast<double>(frames)) : -120.0;
  report.transient = transient_kind_name(transient.kind);
  report.transient_frequency_hz = transient.frequency_hz;
  report.transient_latency_ms = transient.detection_latency_ms;
  report.limiter_active = report.input_peak_dbfs > -3.2 + 1e-4;
  report.frames = static_cast<std::uint32_t>(frames);
  report.checksum = fnv1a_float_block(processed);

  {
    std::lock_guard<std::mutex> lock(mutex_);
    blocks_ += 1;
    report.block_index = blocks_;
    switch (transient.kind) {
      case TransientEvent::Kind::Kick808:
        kick_ += 1;
        break;
      case TransientEvent::Kind::SnareClap:
        snare_ += 1;
        break;
      case TransientEvent::Kind::HatRoll:
        hat_ += 1;
        break;
      case TransientEvent::Kind::None:
      default:
        break;
    }
    report.kick_total = kick_;
    report.snare_total = snare_;
    report.hat_total = hat_;
    last_ = report;
  }
  return report;
}

void KaossAudioProcessor::note_xrun() {
  std::lock_guard<std::mutex> lock(mutex_);
  xruns_ += 1;
}

AudioProcessReport KaossAudioProcessor::last_report() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return last_;
}

std::uint64_t KaossAudioProcessor::blocks() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return blocks_;
}

std::uint32_t KaossAudioProcessor::xruns() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return xruns_;
}

void KaossAudioProcessor::reset() {
  std::lock_guard<std::mutex> lock(mutex_);
  quad_ = KaossQuadEngine();
  blocks_ = 0;
  xruns_ = 0;
  kick_ = 0;
  snare_ = 0;
  hat_ = 0;
  last_ = AudioProcessReport();
}

}  // namespace kaoss
