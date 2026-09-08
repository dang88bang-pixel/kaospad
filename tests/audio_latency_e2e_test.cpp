#include "kaoss_dsp.hpp"

#include <cstdlib>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
  double max_latency_ms = 1.2;
  for (int i = 1; i < argc; ++i) {
    const std::string arg(argv[i]);
    const std::string prefix = "--max-latency=";
    if (arg.rfind(prefix, 0) == 0) {
      std::string value = arg.substr(prefix.size());
      const auto ms = value.find("ms");
      if (ms != std::string::npos) value.erase(ms);
      max_latency_ms = std::stod(value);
    }
  }

  const auto status = kaoss::open_audioflinger_direct_pipe({96000.0, 128, true});
  std::cout << "AudioFlinger direct-pipe simulator: route=" << status.route
            << " roundtrip_ms=" << status.estimated_roundtrip_ms << "\n";
  if (!status.locked || status.estimated_roundtrip_ms > max_latency_ms) {
    std::cerr << "Latency gate failed\n";
    return EXIT_FAILURE;
  }
  return EXIT_SUCCESS;
}
