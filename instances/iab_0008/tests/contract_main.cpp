#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

struct Check { const char* name; const char* marker; };
static const Check checks[] = {
    {"multi_roi_state", "usesMultiROI_"},
    {"multi_roi_api", "SetMultiROI"},
    {"roi_capacity", "roiCountMax"}
};
int main(int argc, char** argv) {
  if (argc != 3) return 2;
  const std::string category = argv[1];
  const std::filesystem::path root = argv[2];
  std::string source;
  for (auto const& p : std::filesystem::recursive_directory_iterator(root)) {
    if (!p.is_regular_file()) continue;
    auto ext = p.path().extension().string();
    if (ext == ".cpp" || ext == ".h" || ext == ".c" || ext == ".vcxproj") {
      std::ifstream in(p.path()); source.append(std::istreambuf_iterator<char>(in), {});
    }
  }
  std::vector<std::string> events;
  int failed = 0;
  std::cout << "{\"tests\":[";
  for (size_t i = 0; i < sizeof(checks)/sizeof(checks[0]); ++i) {
    bool ok = source.find(checks[i].marker) != std::string::npos;
    if (!ok) ++failed;
    if (i) std::cout << ",";
    std::cout << "{\"name\":\"" << checks[i].name << "\",\"passed\":" << (ok ? "true" : "false") << "}";
    if (category == "state_trace" && ok) events.push_back(checks[i].name);
  }
  std::cout << "]}" << std::endl;
  if (category == "state_trace") {
    const char* trace = std::getenv("IAB_TRACE_PATH");
    if (trace) { std::ofstream out(trace); out << "["; for (size_t i=0; i<events.size(); ++i) { if (i) out << ","; out << "{\"event\":\"" << events[i] << "\"}"; } out << "]"; }
  }
  return failed ? 1 : 0;
}
