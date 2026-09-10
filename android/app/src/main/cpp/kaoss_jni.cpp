#include "kaoss_dsp.hpp"

#include <jni.h>

#include <sstream>
#include <string>
#include <vector>

namespace {

std::string json_escape(const std::string& value) {
  std::string out;
  out.reserve(value.size());
  for (char ch : value) {
    if (ch == '"' || ch == '\\') {
      out.push_back('\\');
    }
    out.push_back(ch);
  }
  return out;
}

jstring to_jstring(JNIEnv* env, const std::string& value) {
  return env->NewStringUTF(value.c_str());
}

}  // namespace

extern "C" JNIEXPORT jstring JNICALL
Java_com_kaoss_studio_KaossNative_pipeStatus(JNIEnv* env, jclass /*clazz*/, jdouble sample_rate,
                                             jint frames) {
  kaoss::AudioFlingerPipeConfig cfg;
  cfg.sample_rate_hz = sample_rate;
  cfg.frames_per_buffer = static_cast<std::uint32_t>(frames);
  const auto status = kaoss::open_audioflinger_direct_pipe(cfg);
  std::ostringstream json;
  json << "{\"locked\":" << (status.locked ? "true" : "false")
       << ",\"roundtrip_ms\":" << status.estimated_roundtrip_ms << ",\"route\":\""
       << json_escape(status.route) << "\"}";
  return to_jstring(env, json.str());
}

extern "C" JNIEXPORT jfloat JNICALL
Java_com_kaoss_studio_KaossNative_limiterPeak(JNIEnv* env, jclass /*clazz*/, jfloatArray input) {
  const jsize n = env->GetArrayLength(input);
  std::vector<float> pcm(static_cast<std::size_t>(n));
  env->GetFloatArrayRegion(input, 0, n, pcm.data());
  const auto limited = kaoss::brickwall_soft_knee_buffer(pcm);
  return kaoss::peak_dbfs(limited);
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_kaoss_studio_KaossNative_detectTransient(JNIEnv* env, jclass /*clazz*/, jfloatArray input,
                                                  jdouble sample_rate) {
  const jsize n = env->GetArrayLength(input);
  std::vector<float> pcm(static_cast<std::size_t>(n));
  env->GetFloatArrayRegion(input, 0, n, pcm.data());
  const auto event = kaoss::detect_mouth_transient(pcm, sample_rate);
  const char* kind = "NONE";
  if (event.kind == kaoss::TransientEvent::Kind::Kick808) {
    kind = "KICK808";
  } else if (event.kind == kaoss::TransientEvent::Kind::SnareClap) {
    kind = "SNARE_CLAP";
  } else if (event.kind == kaoss::TransientEvent::Kind::HatRoll) {
    kind = "HAT_ROLL";
  }
  std::ostringstream json;
  json << "{\"kind\":\"" << kind << "\",\"frequency_hz\":" << event.frequency_hz
       << ",\"latency_ms\":" << event.detection_latency_ms << "}";
  return to_jstring(env, json.str());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_kaoss_studio_KaossNative_oboeExclusive(JNIEnv* env, jclass /*clazz*/, jdouble sample_rate,
                                                jint frames) {
  kaoss::OboeExclusiveConfig cfg;
  cfg.sample_rate_hz = sample_rate;
  cfg.frames_per_burst = static_cast<std::uint32_t>(frames);
  const auto status = kaoss::open_oboe_exclusive_stream(cfg);
  std::ostringstream json;
  json << "{\"opened\":" << (status.opened ? "true" : "false") << ",\"exclusive\":"
       << (status.exclusive ? "true" : "false") << ",\"burst_ms\":" << status.burst_ms
       << ",\"roundtrip_ms\":" << status.roundtrip_ms << ",\"xrun_count\":" << status.xrun_count
       << ",\"route\":\"" << json_escape(status.route) << "\"}";
  return to_jstring(env, json.str());
}
