#include "kaoss_dsp.hpp"

#include <algorithm>
#include <cmath>

namespace kaoss {

AudioFlingerPipeStatus open_audioflinger_direct_pipe(const AudioFlingerPipeConfig& cfg) {
  AudioFlingerPipeStatus status;
  const double one_way_ms = (static_cast<double>(cfg.frames_per_buffer) / cfg.sample_rate_hz) * 1000.0;
  // Portable deterministic HAL simulator: native Android builds replace this shim with
  // Oboe/AudioFlinger direct-pipe bindings while preserving the same safety contract.
  status.estimated_roundtrip_ms = one_way_ms * 0.9;
  status.locked = cfg.localhost_only && cfg.sample_rate_hz >= 48000.0 && cfg.frames_per_buffer <= 128;
  return status;
}

float dbfs_to_linear(float dbfs) {
  return std::pow(10.0F, dbfs / 20.0F);
}

float brickwall_soft_knee_sample(float sample, float threshold_dbfs) {
  const float threshold = dbfs_to_linear(threshold_dbfs);
  const float sign = sample < 0.0F ? -1.0F : 1.0F;
  const float abs_sample = std::abs(sample);
  if (abs_sample <= threshold) {
    return sample;
  }
  const float over = abs_sample - threshold;
  const float compressed = threshold + (1.0F - threshold) * std::tanh(over / std::max(1.0e-6F, 1.0F - threshold));
  return sign * std::min(threshold, compressed);
}

std::vector<float> brickwall_soft_knee_buffer(const std::vector<float>& input, float threshold_dbfs) {
  std::vector<float> output;
  output.reserve(input.size());
  for (float sample : input) {
    output.push_back(brickwall_soft_knee_sample(sample, threshold_dbfs));
  }
  return output;
}

float peak_dbfs(const std::vector<float>& buffer) {
  float peak = 0.0F;
  for (float sample : buffer) {
    peak = std::max(peak, std::abs(sample));
  }
  if (peak <= 0.0F) {
    return -120.0F;
  }
  return 20.0F * std::log10(peak);
}

}  // namespace kaoss
