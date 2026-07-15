# DemoCamera: improve timing on Windows in Sequence mode. 

PR: https://github.com/micro-manager/mmCoreAndDevices/pull/730

Use timeBeginPeriod(1) to improve timing of Sleep call. Links agains Winmm.dll.
