// Nativer Referenzlauf des C++-DSP-Kerns für den 3-Wege-Paritäts-Check
// (native g++ <-> WebAssembly <-> Python-Spiegel engines/dsp_chain.py).
//
// Liest dist/parity/vectors.bin (von scripts/dsp_parity_vectors.py erzeugt) und
// schreibt dasselbe JSON-Layout wie tests/dsp_wasm_parity_test.mjs.

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

extern "C" {
std::uint32_t kaoss_dsp_abi_version();
double kaoss_dsp_limiter_dbfs();
std::uint64_t kaoss_dsp_checksum(const float* input, std::uint32_t frames);
float kaoss_dsp_brickwall_sample(float sample, float threshold_dbfs);
std::uint32_t kaoss_dsp_brickwall_buffer(const float* input, float* output, std::uint32_t frames,
                                         float threshold_dbfs);
float kaoss_dsp_peak_dbfs(const float* input, std::uint32_t frames);
std::uint32_t kaoss_dsp_detect_transient(const float* input, std::uint32_t frames, double sample_rate_hz,
                                         double* out);
std::uint32_t kaoss_dsp_synthesize_808(float* output, std::uint32_t frames, double sample_rate_hz,
                                       double duration_ms, int triggered);
void* kaoss_quad_create();
void kaoss_quad_destroy(void* handle);
int kaoss_quad_set_xy(void* handle, std::int32_t module, float x, float y);
int kaoss_quad_freeze(void* handle, std::int32_t module, int enabled);
std::uint32_t kaoss_quad_read_state(void* handle, float* xy, unsigned char* frozen, float* bpm);
std::uint32_t kaoss_quad_process(void* handle, const float* input, float* output, std::uint32_t frames);
}

namespace {

struct Reader {
  const unsigned char* data;
  std::size_t size;
  std::size_t pos = 0;

  bool read(void* out, std::size_t bytes) {
    if (pos + bytes > size) {
      return false;
    }
    std::memcpy(out, data + pos, bytes);
    pos += bytes;
    return true;
  }

  template <typename T>
  bool scalar(T* out) {
    return read(out, sizeof(T));
  }
};

std::string json_number(double value) {
  char buffer[64];
  std::snprintf(buffer, sizeof(buffer), "%.9g", value);
  return buffer;
}

std::string json_array(const std::vector<float>& values) {
  std::string out = "[";
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i != 0) {
      out += ",";
    }
    out += json_number(values[i]);
  }
  out += "]";
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s <vectors.bin> <impl-name>\n", argv[0]);
    return 2;
  }
  FILE* file = std::fopen(argv[1], "rb");
  if (file == nullptr) {
    std::fprintf(stderr, "cannot open %s\n", argv[1]);
    return 2;
  }
  std::fseek(file, 0, SEEK_END);
  const long length = std::ftell(file);
  std::fseek(file, 0, SEEK_SET);
  std::vector<unsigned char> raw(static_cast<std::size_t>(length));
  if (length > 0 && std::fread(raw.data(), 1, raw.size(), file) != raw.size()) {
    std::fclose(file);
    std::fprintf(stderr, "short read on %s\n", argv[1]);
    return 2;
  }
  std::fclose(file);

  Reader reader{raw.data(), raw.size()};
  char magic[4];
  std::uint32_t version = 0;
  std::uint32_t cases = 0;
  if (!reader.read(magic, 4) || std::memcmp(magic, "KVEC", 4) != 0) {
    std::fprintf(stderr, "bad vector magic\n");
    return 2;
  }
  reader.scalar(&version);
  reader.scalar(&cases);

  std::printf("{\"impl\":\"%s\",\"abi\":%u,\"limiter_dbfs\":%s,\"cases\":[", argv[2],
              kaoss_dsp_abi_version(), json_number(kaoss_dsp_limiter_dbfs()).c_str());

  for (std::uint32_t index = 0; index < cases; ++index) {
    std::uint32_t name_len = 0;
    reader.scalar(&name_len);
    std::string name(name_len, '\0');
    reader.read(&name[0], name_len);
    double rate = 0.0;
    reader.scalar(&rate);
    std::uint32_t frames = 0;
    reader.scalar(&frames);
    std::vector<float> pcm(frames);
    reader.read(pcm.data(), frames * sizeof(float));
    std::vector<float> xy(8, 0.0F);
    reader.read(xy.data(), 8 * sizeof(float));
    std::uint32_t s808_frames = 0;
    reader.scalar(&s808_frames);
    double s808_duration = 0.0;
    reader.scalar(&s808_duration);

    // 1) Limiter
    std::vector<float> limited(frames, 0.0F);
    kaoss_dsp_brickwall_buffer(pcm.data(), limited.data(), frames, -3.2F);

    // 2) Transient + 808
    double transient[3] = {0.0, 0.0, 0.0};
    kaoss_dsp_detect_transient(pcm.data(), frames, rate, transient);
    std::vector<float> synth(s808_frames, 0.0F);
    kaoss_dsp_synthesize_808(synth.data(), s808_frames, rate, s808_duration, 1);

    // 3) Kaoss Quad (Vinyl/Looper bewusst aus: identischer Kern wie Python)
    void* engine = kaoss_quad_create();
    for (std::int32_t module = 0; module < 4; ++module) {
      kaoss_quad_set_xy(engine, module, xy[module], xy[4 + module]);
    }
    std::vector<float> processed(frames, 0.0F);
    kaoss_quad_process(engine, pcm.data(), processed.data(), frames);
    std::vector<float> state_xy(8, 0.0F);
    std::vector<unsigned char> frozen(4, 0);
    float bpm = 0.0F;
    kaoss_quad_read_state(engine, state_xy.data(), frozen.data(), &bpm);
    kaoss_quad_destroy(engine);

    char hash[24];
    std::snprintf(hash, sizeof(hash), "%016llx",
                  static_cast<unsigned long long>(kaoss_dsp_checksum(limited.data(), frames)));

    if (index != 0) {
      std::printf(",");
    }
    std::printf(
        "{\"name\":\"%s\",\"frames\":%u,\"sample_rate_hz\":%s,"
        "\"peak_dbfs\":%s,\"limited_peak_dbfs\":%s,\"sample\":%s,\"checksum\":\"%s\","
        "\"transient\":{\"kind_id\":%d,\"frequency_hz\":%s,\"detection_latency_ms\":%s},"
        "\"limited\":%s,\"processed\":%s,\"s808\":%s,"
        "\"state\":{\"xy\":%s,\"frozen\":[%u,%u,%u,%u],\"bpm\":%s}}",
        name.c_str(), frames, json_number(rate).c_str(),
        json_number(kaoss_dsp_peak_dbfs(pcm.data(), frames)).c_str(),
        json_number(kaoss_dsp_peak_dbfs(limited.data(), frames)).c_str(),
        json_number(kaoss_dsp_brickwall_sample(1.0F, -3.2F)).c_str(), hash,
        static_cast<int>(transient[0]), json_number(transient[1]).c_str(), json_number(transient[2]).c_str(),
        json_array(limited).c_str(), json_array(processed).c_str(), json_array(synth).c_str(),
        json_array(state_xy).c_str(), frozen[0], frozen[1], frozen[2], frozen[3], json_number(bpm).c_str());
  }

  std::printf("]}\n");
  return 0;
}
