# MMCore: per-device timeout setting

PR: https://github.com/micro-manager/mmCoreAndDevices/pull/914

MMCore needs per-device timeout overrides while retaining the global default and exception semantics. The API crosses Core, DeviceInstance, and Java wrapper boundaries.
