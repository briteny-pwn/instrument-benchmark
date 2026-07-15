# Difficulty analysis

Adapter: MMCore

Failure modes: timeout, framework_semantic_mismatch, error_recovery

MMCore needs per-device timeout overrides while retaining the global default and exception semantics. The API crosses Core, DeviceInstance, and Java wrapper boundaries.
