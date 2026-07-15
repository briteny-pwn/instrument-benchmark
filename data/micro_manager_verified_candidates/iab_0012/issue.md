# PVCAM: Removed polling for acquisition state

PR: https://github.com/micro-manager/mmCoreAndDevices/pull/941

Polling doesn't work reliably with recent fast cameras. Registering an EOF callback handler is the recommended way for many years already. Removed all the logic related to polling, including a property for selecting between polling and callbacks.

As a side change I have fixed auto-shutter that was not always closed at the acquisition end, because it was inside modified code. This has been reported and fix proposed in PR #907.
