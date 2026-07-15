# Fix race condition in AlliedVisionCamera property callbacks

PR: https://github.com/micro-manager/mmCoreAndDevices/pull/828

AlliedVision callbacks can race property allowed-value updates during SDK invalidation callbacks. The merged repair serializes callback mutations and ignores callbacks before property initialization.
