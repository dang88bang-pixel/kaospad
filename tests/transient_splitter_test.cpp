#include "kaoss_dsp.hpp"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <vector>

int main() {
  constexpr double sample_rate = 96000.0;
  constexpr double pi = 3.14159265358979323846;
  std::vector<float> mouth_bass(96);
  for (std::size_t i = 0; i < mouth_bass.size(); ++i) {
    mouth_bass[i] = 0.22F + static_cast<float>(0.01 * std::sin(2.0 * pi * 52.0 * static_cast<double>(i) / sample_rate));
  }

  const auto event = kaoss::detect_mouth_transient(mouth_bass, sample_rate);
  std::cout << "Transient kind=" << static_cast<int>(event.kind)
            << " freq=" << event.frequency_hz
            << " latency_ms=" << event.detection_latency_ms << "\n";
  if (event.kind != kaoss::TransientEvent::Kind::Kick808 ||
      event.frequency_hz < 20.0 || event.frequency_hz > 90.0 ||
      event.detection_latency_ms >= 1.5) {
    std::cerr << "Transient mouth-to-808 gate failed\n";
    return EXIT_FAILURE;
  }

  const auto sub = kaoss::synthesize_808(event, sample_rate, 180.0);
  if (sub.empty() || kaoss::peak_dbfs(sub) > -3.19F) {
    std::cerr << "808 synthesis limiter gate failed\n";
    return EXIT_FAILURE;
  }
  return EXIT_SUCCESS;
}
