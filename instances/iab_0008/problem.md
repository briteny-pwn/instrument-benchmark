# Micro-Manager repair: PVCAM: Fixed multi-ROI support for Kinetix camera

Source PR: https://github.com/micro-manager/mmCoreAndDevices/pull/965

Kinetix supports multiple ROIs on HDR port only. If the camera was not switched to HDR port before Micro-Manager starts, only one ROI was supported. Now, the adapter scans all ports and reports multi-ROI transparently on ports where really supported.

Only modify the pre-fix files under `repository/`. The simulator provides a fake Core/SDK contract; do not use real hardware or vendor SDKs.
