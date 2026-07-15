# IAB-Sim-MVP phase-1 report

## Result

The phase-1 pipeline is executable end to end:

```text
real closed issue + merged PR
  -> pre-fix and post-fix commit provenance
  -> scored candidate
  -> reviewed evidence bundle
  -> focused pre-fix source snapshot + simulator
  -> observed pre-fix failure
  -> observed gold-patch pass
  -> replaceable model patch + JSON evaluation report
```

The deterministic validation result is recorded in [`reports/phase1_validation.json`](../reports/phase1_validation.json). It currently passes with 20 scored candidates, 5 verified candidates, and 3 executable instances.

## Candidate sources

The checked-in 20-candidate snapshot contains:

| Source | Count |
|---|---:|
| ophyd | 9 |
| bluesky | 4 |
| QCoDeS contrib drivers | 3 |
| QCoDeS | 2 |
| InstrumentKit | 2 |

All 20 score at least 50. The distribution is 9 reserve, 4 candidate, and 7 verified-candidate priority. Five of the priority set have completed the separate human-review evidence-bundle gate. The online miner also supports PyMeasure, areaDetector, ADSimDetector, and Micro-Manager; the deterministic phase-1 selection favors Python projects for executable feasibility.

## Filtering and scoring

Hard filters reject documentation-only, formatting-only, CI-only, dependency-only, import-only, non-instrument, hardware-only, private-SDK, unmerged, and commit-incomplete changes. Search-title exclusions are applied before API enrichment; the scoring stage rechecks provenance and instrument relevance.

The 100-point rubric follows `plan.md`: source evidence 20, instrument relevance 20, difficulty evidence 25, simulability 25, and executable evaluation evidence 10. Thresholds are verified candidate at 80, candidate at 65, reserve at 50, and drop below 50.

## Verified candidates

| ID | Source issue / PR | Repair concern | Score evidence |
|---|---|---|---|
| iab_0001 | ophyd #1242 / #1243 | class and instance connection-timeout semantics | timeout, initialization, framework lifecycle |
| iab_0002 | ophyd #1256 / #1257 | distinct `write_pv` constructor semantics | framework constructor mismatch |
| iab_0003 | ophyd #1218 / #1219 | configured trigger value ignored | device state and trigger semantics |
| iab_0004 | ophyd #1206 / #1207 | short write versus full EPICS array readback | stale tail data and asynchronous set completion |
| iab_0005 | InstrumentKit #439 / #440 | unconditional `auth=None` forwarding | connection factory and driver compatibility |

Each directory under `data/verified_candidates` contains the source summary, issue summary, diff statistics, seven-question difficulty analysis, simulation plan, evaluation oracle, and full commit provenance. These bundles are human-review inputs; they do not expose the gold patch to a model.

## Executable instances

### iab_0001 — ophyd connection timeout

The simulator provides connected and disconnected child signals and records the exact timeout passed by `Device.wait_for_connection`. Tests cover class default propagation, per-instance precedence, every-child traversal, timeout propagation, and the disconnected trace.

### iab_0003 — ophyd trigger value

The stateful detector accepts a configurable trigger token and transitions `idle -> acquiring -> complete`. Tests reject the upstream hard-coded value, duplicate triggers, swallowed simulator errors, and regressions to the default token.

### iab_0005 — InstrumentKit TCP/IP construction

The socket/communicator mock records connection and constructor behavior. Tests require legacy drivers to open without an `auth` keyword, authenticated drivers to receive explicit credentials, and explicit unsupported credentials to fail instead of being silently discarded.

For all three, the four required shell commands have been run in sequence. The pre-fix gate observed failure, the gold patch passed every layer, a fresh model-patch substitution using the gold diff passed, and `evaluation_report.json` was generated.

All three Dockerfiles were also built from the repository root and their default lifecycle commands completed successfully in `python:3.12-slim`. Patch application is implemented inside the evaluator with the Python standard library, so the runtime image does not need Git, GNU patch, pytest, network access, or an upstream framework installation.

## Evaluation layers

- Fail-to-pass directly encodes the upstream issue behavior.
- Regression protects the pre-existing default or authenticated path.
- State trace records commands, values, and before/after states.
- Gold differential compares ordered semantic checkpoints while ignoring timestamps and harmless extra events.
- Minefields exercise alternative values and error paths to reject hard-coding, duplicate actions, swallowed errors, incorrect precedence, and constructor bypasses.

The evaluator copies the committed pre-fix snapshot into an ignored workspace before applying any patch, so neither gold nor model evaluation mutates the benchmark source.

Model authoring uses a separately materialized bundle containing only the sanitized problem, exact pre-fix repository files, simulator, and its dependency-free source loader. Instance metadata, commit manifests, gold patches, expected traces, and benchmark tests remain outside that boundary. The phase-1 validator builds every bundle and scans it for post-fix URLs and SHAs.

### Source authenticity

Executable repositories contain the exact pre-fix bytes of every file modified by the resolving upstream PR. `source_manifest.json` records their Git blob SHA-1 values, and the validation gate recomputes them and matches the blob prefixes in the original upstream `.diff`. The checked-in `gold.patch` files are the complete upstream PR diffs, including upstream test changes. To keep execution dependency-free, the simulator loads and runs selected methods directly from the real source AST instead of importing a hand-written substitute or the full external framework.

## Limitations

- Executable snapshots contain all files touched by the resolving PR with verified upstream blob hashes, but not unrelated files from the full upstream checkout. Provenance SHAs and source links allow an auditor to reconstruct the complete repository.
- Three instances cover two frameworks and remain Python-heavy; C++/EPICS and Micro-Manager candidates are mining-only in phase 1.
- Simulator equivalence proves framework behavior under modeled states, not electrical, timing-jitter, transport, firmware, or safety behavior on physical hardware.
- Automatic scores prioritize review; they do not replace expert confirmation of benchmark difficulty.
- No model baseline or contamination study is claimed by this engineering milestone.

## Phase-2 real-calibration interface

The metadata keeps instrument category, failure modes, trace checkpoints, expected final state, and simulator type separate from source code. Phase 2 can add a `calibration/` record per instance containing hardware identity, firmware, transport, captured trace, tolerances, and simulator-to-hardware deviations without changing the model patch contract. The first calibration targets should be the trigger and TCP/IP constructor instances because their observable command traces have direct hardware analogues.
