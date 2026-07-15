# PVCAM: Fixed regression with shutter

PR: https://github.com/micro-manager/mmCoreAndDevices/pull/970

The `PrepareForAcq` callback must be called unconditionally to properly notify core whenever new acquisition is about to start.
