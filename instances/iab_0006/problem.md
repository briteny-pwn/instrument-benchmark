# Micro-Manager repair: DemoCamera:  Fixed DemoXYStage position reporting bugs and added a polling thread

Source PR: https://github.com/micro-manager/mmCoreAndDevices/pull/946

Polling thread fires OnXYStagePositionChanged callbacks during moves. The thread now wakes immediately when a move starts via a condition variable.

Only modify the pre-fix files under `repository/`. The simulator provides a fake Core/SDK contract; do not use real hardware or vendor SDKs.
