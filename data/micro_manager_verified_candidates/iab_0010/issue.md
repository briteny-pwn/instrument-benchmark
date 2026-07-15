# DemoCamera:  Fixed DemoXYStage position reporting bugs and added a polling thread

PR: https://github.com/micro-manager/mmCoreAndDevices/pull/946

The DemoCamera XY stage reports user-space positions while a move is active. The polling thread must wake on move start, serialize access to the timeout state, and notify Busy/position callbacks without stale coordinates.
