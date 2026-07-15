# Resolution summary

A C++ implementation of @hinderling's https://github.com/pymmcore-plus/pymmcore-plus/pull/614.

New CMMCore API:

```c++
void setDeviceTimeoutMs(const char* label, long timeoutMs);
void unsetDeviceTimeout(const char* label);
long getDeviceTimeoutMs(const char* label);
bool hasDeviceTimeout(const char* label);
```

(All 4 methods can throw.)

~~TODO: MMCore minor version should be bumped when merging.~~
