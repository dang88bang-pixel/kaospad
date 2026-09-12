#include "kaoss_dsp.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <stdexcept>

namespace kaoss {
namespace {

// Modul-Index-Guard: Der Native/JNI-Build wirft (Testbarkeit), der
// Realtime-/WASM-Build (KAOSS_NO_EXCEPTIONS) darf keine Exceptions haben.
// Die C-ABI (kaoss_dsp_abi.cpp) klemmt Indizes vorher, dieser Pfad ist dort
// unerreichbar.
[[noreturn]] void invalid_kaoss_module() {
#ifdef KAOSS_NO_EXCEPTIONS
  std::abort();
#else
  throw std::out_of_range("Kaoss module index must be 0..3");
#endif
}

}  // namespace

void KaossQuadEngine::set_xy(std::size_t module, float x, float y) {
  if (module >= state_.x.size()) {
    invalid_kaoss_module();
  }
  if (!state_.frozen[module]) {
    state_.x[module] = std::clamp(x, 0.0F, 1.0F);
    state_.y[module] = std::clamp(y, 0.0F, 1.0F);
  }
}

void KaossQuadEngine::freeze(std::size_t module, bool enabled) {
  if (module >= state_.frozen.size()) {
    invalid_kaoss_module();
  }
  state_.frozen[module] = enabled;
}

std::vector<float> KaossQuadEngine::process(const std::vector<float>& input) const {
  std::vector<float> output = input;
  const float drive = 1.0F + state_.x[0] * 0.35F;
  const float filter = 1.0F - state_.y[2] * 0.42F;
  const float ambience = state_.x[3] * state_.y[3] * 0.08F;
  float previous = 0.0F;
  for (float& sample : output) {
    const float delayed = previous * ambience;
    previous = sample;
    sample = brickwall_soft_knee_sample((sample * drive * filter) + delayed);
  }
  return output;
}

}  // namespace kaoss
