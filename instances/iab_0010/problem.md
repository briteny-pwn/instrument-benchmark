# Micro-Manager repair: Update TSI device adapter load files to work with SDK 2.0.1 DLLs

Source PR: https://github.com/micro-manager/mmCoreAndDevices/pull/124

SDK has new functions and a reworked load file for DLLs. Changes are required for TSI camera users with SDK v2.0.1.

Only modify the pre-fix files under `repository/`. The simulator provides a fake Core/SDK contract; do not use real hardware or vendor SDKs.
