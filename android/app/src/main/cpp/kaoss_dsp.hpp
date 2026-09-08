#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace kaoss {

struct AudioFlingerPipeConfig {
  double sample_rate_hz = 96000.0;
  std::uint32_t frames_per_buffer = 128;
  bool localhost_only = true;
};

struct AudioFlingerPipeStatus {
  bool locked = false;
  double estimated_roundtrip_ms = 0.0;
  std::string route = "127.0.0.1:8081";
};

AudioFlingerPipeStatus open_audioflinger_direct_pipe(const AudioFlingerPipeConfig& cfg);

float dbfs_to_linear(float dbfs);
float brickwall_soft_knee_sample(float sample, float threshold_dbfs = -3.2F);
std::vector<float> brickwall_soft_knee_buffer(const std::vector<float>& input,
                                              float threshold_dbfs = -3.2F);
float peak_dbfs(const std::vector<float>& buffer);

struct TransientEvent {
  enum class Kind { None, Kick808, SnareClap, HatRoll } kind = Kind::None;
  double frequency_hz = 0.0;
  double detection_latency_ms = 0.0;
};

TransientEvent detect_mouth_transient(const std::vector<float>& pcm,
                                      double sample_rate_hz = 96000.0);
std::vector<float> synthesize_808(const TransientEvent& event,
                                  double sample_rate_hz = 96000.0,
                                  double duration_ms = 180.0);

struct KaossQuadState {
  std::array<float, 4> x{};
  std::array<float, 4> y{};
  std::array<bool, 4> frozen{};
  float bpm = 92.4F;
};

class KaossQuadEngine {
 public:
  void set_xy(std::size_t module, float x, float y);
  void freeze(std::size_t module, bool enabled);
  const KaossQuadState& state() const { return state_; }
  std::vector<float> process(const std::vector<float>& input) const;

 private:
  KaossQuadState state_{};
};

}  // namespace kaoss
