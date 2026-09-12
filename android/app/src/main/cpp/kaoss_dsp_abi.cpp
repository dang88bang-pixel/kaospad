// Stabile C-ABI über dem C++-Kaoss-DSP-Kern.
//
// Dieselbe Datei wird zweimal gebaut:
//   * als WebAssembly-Modul  -> scripts/build_wasm.sh  -> dist/wasm/kaoss_dsp.wasm
//   * als natives Binary     -> tests/dsp_parity_harness.cpp (Referenzlauf)
//
// Dadurch rechnen Browser und Native *aus demselben Quelltext*; die Python-Spiegel
// (engines/dsp_chain.py) werden über tests/dsp_wasm_parity_test.mjs gegengeprüft.
// Über diese Grenze gehen keine Exceptions und keine C++-Typen.

#include <cstddef>
#include <cstdint>
#include <cstring>

#include "kaoss_dsp.hpp"

namespace {

constexpr std::uint32_t kAbiVersion = 1;

kaoss::KaossQuadEngine* as_engine(void* handle) {
  return static_cast<kaoss::KaossQuadEngine*>(handle);
}

}  // namespace

extern "C" {

// --------------------------------------------------------------------------- //
// Metainformationen
// --------------------------------------------------------------------------- //
std::uint32_t kaoss_dsp_abi_version() { return kAbiVersion; }

double kaoss_dsp_limiter_dbfs() { return -3.2; }

// FNV-1a über die Float-Bits: gleicher Kern -> gleicher Hash (Paritätsbeweis).
std::uint64_t kaoss_dsp_checksum(const float* input, std::uint32_t frames) {
  std::uint64_t hash = 1469598103934665603ULL;
  const auto* bytes = reinterpret_cast<const unsigned char*>(input);
  for (std::uint32_t i = 0; i < frames * sizeof(float); ++i) {
    hash ^= bytes[i];
    hash *= 1099511628211ULL;
  }
  return hash;
}

// --------------------------------------------------------------------------- //
// Limiter / Metering (audio_flinger_hook.cpp)
// --------------------------------------------------------------------------- //
float kaoss_dsp_brickwall_sample(float sample, float threshold_dbfs) {
  return kaoss::brickwall_soft_knee_sample(sample, threshold_dbfs);
}

std::uint32_t kaoss_dsp_brickwall_buffer(const float* input, float* output, std::uint32_t frames,
                                         float threshold_dbfs) {
  if (input == nullptr || output == nullptr) {
    return 0;
  }
  const std::vector<float> source(input, input + frames);
  const std::vector<float> limited = kaoss::brickwall_soft_knee_buffer(source, threshold_dbfs);
  std::memcpy(output, limited.data(), limited.size() * sizeof(float));
  return static_cast<std::uint32_t>(limited.size());
}

float kaoss_dsp_peak_dbfs(const float* input, std::uint32_t frames) {
  if (input == nullptr || frames == 0) {
    return -120.0F;
  }
  const std::vector<float> source(input, input + frames);
  return kaoss::peak_dbfs(source);
}

// --------------------------------------------------------------------------- //
// Transient-Splitter + 808 (dsp_transient_splitter.cpp)
// --------------------------------------------------------------------------- //
// out: [kind_id, frequency_hz, detection_latency_ms]
std::uint32_t kaoss_dsp_detect_transient(const float* input, std::uint32_t frames, double sample_rate_hz,
                                         double* out) {
  if (input == nullptr || out == nullptr) {
    return 0;
  }
  const std::vector<float> source(input, input + frames);
  const kaoss::TransientEvent event = kaoss::detect_mouth_transient(source, sample_rate_hz);
  out[0] = static_cast<double>(static_cast<int>(event.kind));
  out[1] = event.frequency_hz;
  out[2] = event.detection_latency_ms;
  return 3;
}

std::uint32_t kaoss_dsp_synthesize_808(float* output, std::uint32_t frames, double sample_rate_hz,
                                       double duration_ms, int triggered) {
  if (output == nullptr) {
    return 0;
  }
  kaoss::TransientEvent event;
  if (triggered != 0) {
    event.kind = kaoss::TransientEvent::Kind::Kick808;
    event.frequency_hz = 52.0;
  }
  const std::vector<float> synth = kaoss::synthesize_808(event, sample_rate_hz, duration_ms);
  const std::uint32_t count = static_cast<std::uint32_t>(synth.size() < frames ? synth.size() : frames);
  if (count > 0) {
    std::memcpy(output, synth.data(), count * sizeof(float));
  }
  for (std::uint32_t i = count; i < frames; ++i) {
    output[i] = 0.0F;
  }
  return count;
}

// --------------------------------------------------------------------------- //
// Kaoss Quad Engine (kaoss_quad_engine.cpp)
// --------------------------------------------------------------------------- //
void* kaoss_quad_create() { return static_cast<void*>(new kaoss::KaossQuadEngine()); }

void kaoss_quad_destroy(void* handle) { delete as_engine(handle); }

// Index außerhalb 0..3 wird geklemmt statt zu werfen (keine Exceptions in WASM).
int kaoss_quad_set_xy(void* handle, std::int32_t module, float x, float y) {
  if (handle == nullptr || module < 0 || module > 3) {
    return 0;
  }
  as_engine(handle)->set_xy(static_cast<std::size_t>(module), x, y);
  return 1;
}

int kaoss_quad_freeze(void* handle, std::int32_t module, int enabled) {
  if (handle == nullptr || module < 0 || module > 3) {
    return 0;
  }
  as_engine(handle)->freeze(static_cast<std::size_t>(module), enabled != 0);
  return 1;
}

// xy: 8 Floats (x0..x3, y0..y3), frozen: 4 Bytes, bpm: 1 Float
std::uint32_t kaoss_quad_read_state(void* handle, float* xy, unsigned char* frozen, float* bpm) {
  if (handle == nullptr || xy == nullptr || frozen == nullptr || bpm == nullptr) {
    return 0;
  }
  const kaoss::KaossQuadState& state = as_engine(handle)->state();
  for (std::size_t i = 0; i < 4; ++i) {
    xy[i] = state.x[i];
    xy[4 + i] = state.y[i];
    frozen[i] = state.frozen[i] ? 1 : 0;
  }
  *bpm = state.bpm;
  return 1;
}

std::uint32_t kaoss_quad_process(void* handle, const float* input, float* output, std::uint32_t frames) {
  if (handle == nullptr || input == nullptr || output == nullptr) {
    return 0;
  }
  const std::vector<float> source(input, input + frames);
  const std::vector<float> processed = as_engine(handle)->process(source);
  std::memcpy(output, processed.data(), processed.size() * sizeof(float));
  return static_cast<std::uint32_t>(processed.size());
}

}  // extern "C"
