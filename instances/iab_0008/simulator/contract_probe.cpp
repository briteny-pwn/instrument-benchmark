#include <cstring>
#if defined(_WIN32)
#define IAB_EXPORT extern "C" __declspec(dllexport)
#else
#define IAB_EXPORT extern "C" __attribute__((visibility("default")))
#endif
struct Entry { const char* name; int value; };
static const Entry entries[] = {
#include "contract_entries.inc"
};
IAB_EXPORT int iab_contract_value(const char* name) {
  for (const auto& entry : entries) if (std::strcmp(entry.name, name) == 0) return entry.value;
  return -1;
}
