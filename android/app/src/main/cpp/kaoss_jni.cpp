#include "audio_input_engine.hpp"
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

extern "C" JNIEXPORT jstring JNICALL
Java_com_kaoss_studio_KaossNative_startAudioInput(JNIEnv* env, jclass /*clazz*/, jdouble sample_rate,
                                                  jint frames, jint source) {
  kaoss::AudioInputConfig cfg;
  cfg.sample_rate_hz = sample_rate;
  cfg.frames_per_burst = static_cast<std::uint32_t>(frames);
  cfg.source = static_cast<kaoss::AudioInputSource>(source);
  const bool started = kaoss::audio_input_start(cfg);
  const auto status = kaoss::audio_input_status();
  std::ostringstream json;
  json << "{\"started\":" << (started ? "true" : "false")
       << ",\"native_aaudio\":" << (status.native_aaudio ? "true" : "false")
       << ",\"exclusive\":" << (status.exclusive ? "true" : "false")
       << ",\"backend\":\"" << json_escape(status.backend) << "\""
       << ",\"route\":\"" << json_escape(status.route) << "\""
       << ",\"sample_rate_hz\":" << status.sample_rate_hz
       << ",\"frames_per_burst\":" << status.frames_per_burst << "}";
  return to_jstring(env, json.str());
}

extern "C" JNIEXPORT void JNICALL
Java_com_kaoss_studio_KaossNative_stopAudioInput(JNIEnv* /*env*/, jclass /*clazz*/) {
  kaoss::audio_input_stop();
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_kaoss_studio_KaossNative_audioInputStatus(JNIEnv* env, jclass /*clazz*/) {
  const auto status = kaoss::audio_input_status();
  std::ostringstream json;
  json << "{\"running\":" << (status.running ? "true" : "false")
       << ",\"native_aaudio\":" << (status.native_aaudio ? "true" : "false")
       << ",\"exclusive\":" << (status.exclusive ? "true" : "false")
       << ",\"fallback_audiorecord\":" << (status.fallback_audiorecord ? "true" : "false")
       << ",\"backend\":\"" << json_escape(status.backend) << "\""
       << ",\"route\":\"" << json_escape(status.route) << "\""
       << ",\"sample_rate_hz\":" << status.sample_rate_hz
       << ",\"frames_per_burst\":" << status.frames_per_burst
       << ",\"blocks\":" << status.blocks << ",\"xruns\":" << status.xruns
       << ",\"peak_dbfs\":" << status.peak_dbfs << ",\"rms_dbfs\":" << status.rms_dbfs
       << ",\"last_transient\":\"" << json_escape(status.last_transient) << "\"}";
  return to_jstring(env, json.str());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_kaoss_studio_KaossNative_processAudioBlock(JNIEnv* env, jclass /*clazz*/, jfloatArray input) {
  const jsize n = env->GetArrayLength(input);
  std::vector<float> pcm(static_cast<std::size_t>(n));
  env->GetFloatArrayRegion(input, 0, n, pcm.data());
  const auto report = kaoss::audio_input_push_block(pcm.data(), pcm.size());
  std::ostringstream json;
  json << "{\"peak_dbfs\":" << report.peak_dbfs << ",\"input_peak_dbfs\":" << report.input_peak_dbfs
       << ",\"rms_dbfs\":" << report.rms_dbfs << ",\"transient\":\"" << json_escape(report.transient)
       << "\",\"transient_frequency_hz\":" << report.transient_frequency_hz
       << ",\"limiter_active\":" << (report.limiter_active ? "true" : "false")
       << ",\"frames\":" << report.frames << ",\"blocks\":" << report.block_index
       << ",\"checksum\":" << report.checksum << ",\"xruns\":" << kaoss::audio_input_status().xruns << "}";
  return to_jstring(env, json.str());
}
