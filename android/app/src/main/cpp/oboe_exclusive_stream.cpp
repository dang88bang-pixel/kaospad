#include "kaoss_dsp.hpp"

namespace kaoss {

OboeExclusiveStatus open_oboe_exclusive_stream(const OboeExclusiveConfig& cfg) {
  OboeExclusiveStatus status;
  const double burst_ms = (static_cast<double>(cfg.frames_per_burst) / cfg.sample_rate_hz) * 1000.0;
  status.burst_ms = burst_ms;
  status.roundtrip_ms = burst_ms * 0.9 * 2.0;
  status.exclusive = cfg.exclusive && cfg.low_latency;
  status.opened = status.exclusive && cfg.sample_rate_hz >= 48000.0 && cfg.frames_per_burst <= 256;
#ifdef HAVE_OBOE
  // Production NDK: oboe::AudioStreamBuilder with Exclusive + LowLatency + Float.
#endif
  return status;
}

}  // namespace kaoss
