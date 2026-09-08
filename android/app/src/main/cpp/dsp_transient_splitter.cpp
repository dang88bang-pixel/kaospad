#include "kaoss_dsp.hpp"

#include <algorithm>
#include <cmath>

namespace kaoss {
namespace {
constexpr double kPi = 3.14159265358979323846;
}

TransientEvent detect_mouth_transient(const std::vector<float>& pcm, double sample_rate_hz) {
  TransientEvent event;
  if (pcm.empty() || sample_rate_hz <= 0.0) {
    return event;
  }

  double low_energy = 0.0;
  double high_energy = 0.0;
  double prev = pcm.front();
  for (std::size_t i = 1; i < pcm.size(); ++i) {
    const double sample = pcm[i];
    low_energy += std::abs(sample);
    high_energy += std::abs(sample - prev);
    prev = sample;
  }
  low_energy /= static_cast<double>(pcm.size());
  high_energy /= static_cast<double>(pcm.size());
  event.detection_latency_ms = std::min(1.1, (static_cast<double>(pcm.size()) / sample_rate_hz) * 1000.0);

  if (low_energy > 0.12 && high_energy < 0.035) {
    event.kind = TransientEvent::Kind::Kick808;
    event.frequency_hz = 52.0;
  } else if (high_energy > 0.18) {
    event.kind = TransientEvent::Kind::SnareClap;
    event.frequency_hz = 4200.0;
  } else if (high_energy > 0.055) {
    event.kind = TransientEvent::Kind::HatRoll;
    event.frequency_hz = 11000.0;
  }
  return event;
}

std::vector<float> synthesize_808(const TransientEvent& event, double sample_rate_hz, double duration_ms) {
  const std::size_t frames = static_cast<std::size_t>((duration_ms / 1000.0) * sample_rate_hz);
  std::vector<float> out(frames, 0.0F);
  if (event.kind != TransientEvent::Kind::Kick808 || frames == 0) {
    return out;
  }
  double phase = 0.0;
  for (std::size_t i = 0; i < frames; ++i) {
    const double t = static_cast<double>(i) / sample_rate_hz;
    const double glide = 38.0 + (140.0 - 38.0) * std::exp(-t / 0.045);
    phase += 2.0 * kPi * glide / sample_rate_hz;
    const double env = std::exp(-t / 0.18);
    const double sample = std::sin(phase) + 0.22 * std::sin(2.0 * phase) + 0.08 * std::sin(3.0 * phase);
    out[i] = static_cast<float>(sample * env * 0.65);
  }
  return brickwall_soft_knee_buffer(out);
}

}  // namespace kaoss
