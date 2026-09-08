#include "kaoss_dsp.hpp"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
  float threshold = -3.2F;
  for (int i = 1; i < argc; ++i) {
    const std::string arg(argv[i]);
    const std::string prefix = "--threshold=";
    if (arg.rfind(prefix, 0) == 0) {
      std::string value = arg.substr(prefix.size());
      const auto unit = value.find("dBFS");
      if (unit != std::string::npos) value.erase(unit);
      threshold = std::stof(value);
    }
  }

  std::vector<float> brutal_plosives;
  for (int i = 0; i < 4096; ++i) {
    brutal_plosives.push_back((i % 2 == 0 ? 1.0F : -1.0F) * (1.0F + (i % 17) * 0.2F));
  }
  const auto limited = kaoss::brickwall_soft_knee_buffer(brutal_plosives, threshold);
  const float peak = kaoss::peak_dbfs(limited);
  std::cout << "Limiter peak=" << peak << " dBFS threshold=" << threshold << " dBFS\n";
  if (peak > threshold + 0.01F || peak > 0.0F) {
    std::cerr << "Limiter gate failed\n";
    return EXIT_FAILURE;
  }
  return EXIT_SUCCESS;
}
