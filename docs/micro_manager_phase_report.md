# Micro-Manager DeviceAdapters phase

This phase adds 20 scored candidates and 10 verified evidence bundles from the
official `micro-manager/mmCoreAndDevices` repository. The parent repository and
submodule relationship are recorded in candidate metadata; the executable
snapshots are pinned to the adapter repository's pre-fix and merge commits.

Five focused instances are executable (`iab_0006`–`iab_0010`): DemoCamera stage
polling, AlliedVision property callbacks, PVCAM multi-ROI, MMCore per-device
timeouts, and TSI SDK loading. Each uses public upstream source and a local
fake Core/transport or SDK contract, so no vendor SDK or hardware is required.
The C++ harness compiles with C++17 and emits per-assertion results plus an
ordered trace. Linux runs behavior tests; macOS and Windows CI jobs perform
compile/export/load smoke checks.

Evidence policy: these candidates use `merged_pr_with_reproduction`. The merged
PR body, upstream diff, exact base/merge SHA, and deterministic reproduction
contract are required; a separate closed issue is optional when the PR itself
contains the failure description. This reflects the actual upstream history and
does not invent issue links.

Reports use schema v2. `strict_pass` remains the all-required-tests gate while
`evaluation_score` is the weighted 0–100 partial score. Gold patches for all
five instances pass strictly and score 100 locally; the project validator also
checks the model bundle boundary and legacy phase-1 compatibility.
