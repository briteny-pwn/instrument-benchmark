# IAB-Sim-MVP

Simulation-first Instrument Access Benchmark is a repair benchmark derived from real, resolved instrument-integration issues and merged pull requests. Phase 1 deliberately excludes clean-room “read a manual and write an SDK” tasks. Each executable task starts from upstream pre-fix behavior and evaluates a repair against a deterministic device simulation.

## Phase-1 status

- 20 scored candidates from the configured upstream repositories.
- 5 human-reviewable verified candidates with issue/PR/commit provenance, difficulty analysis, simulation plan, and evaluation oracle.
- 3 executable repair instances.
- Micro-Manager phase: 20 scored candidates, 10 verified candidates, and five
  C++ DeviceAdapters instances (`iab_0006`–`iab_0010`).
- Every executable instance proves pre-fix failure and gold-patch success locally.
- Model patches can be supplied to the same evaluator, which emits a JSON report across fail-to-pass, regression, state trace, gold differential, and minefield layers.

These counts describe engineering readiness, not model-ranking validity or transfer to physical hardware. Real-hardware calibration is a phase-2 concern.

## Repository layout

```text
configs/sources.yaml              upstream source registry
schemas/instance.schema.json      canonical instance metadata contract
data/candidates.json              deterministic 20-candidate snapshot
data/scored_candidates.json       scored and graded snapshot
data/verified_candidates/         five evidence bundles
instances/iab_*/                  executable repair instances
evaluator/                        patch runner and trace differential
iab/                              shared mining/scoring primitives
scripts/                          mine, curate, score, build, validate
docs/phase1_report.md              phase-1 evidence report
legacy/level1/                    archived earlier clean-room benchmark
```

The archived Level 1 work is retained for provenance but is not part of IAB-Sim-MVP and must not be counted in phase-1 results.

## Candidate pipeline

```text
GitHub closed issue + merged PR
  -> capture base and merge commits
  -> hard-filter non-instrument and non-code changes
  -> score evidence and simulability
  -> human-review evidence bundle
  -> executable focused snapshot
  -> pre-fix fail / gold pass gate
```

Refresh candidates with a GitHub token when available:

```bash
GITHUB_TOKEN=... python3 scripts/mine_github_issues.py --limit 20
python3 scripts/curate_candidates.py
python3 scripts/score_candidates.py data/candidates.json
python3 scripts/build_verified_candidates.py
```

The token is used only in request headers and is never persisted. The checked-in snapshots make evaluation independent of GitHub availability.

## Running an executable instance

Each instance supports the lifecycle required by `plan.md`:

```bash
cd instances/iab_0003
bash setup.sh
bash reproduce_pre_fix.sh
bash apply_gold_patch.sh
bash evaluate.sh
```

`reproduce_pre_fix.sh` succeeds only if the fail-to-pass test fails on the unpatched source. `evaluate.sh` succeeds only if all evaluation layers pass and writes `.work/evaluation_report.json`.

Each executable repository contains every file changed by its upstream PR, downloaded at the recorded base commit. The acceptance gate recomputes Git blob hashes and checks that the original upstream PR diff starts from those blobs. Target methods are executed from their real AST in dependency-free simulator shells, so a benchmark does not need to import the rest of ophyd or InstrumentKit.

To evaluate a model-generated unified diff against a fresh pre-fix copy:

```bash
cd instances/iab_0003
bash evaluate.sh /absolute/path/to/model.patch
```

Only the patch under evaluation is applied. The committed pre-fix snapshot is never mutated.

Build the model-visible bundle separately from hidden evaluation material:

```bash
python3 scripts/build_model_bundle.py iab_0003
```

The output contains only `problem.md`, the exact pre-fix `repository/`, and `simulator/`. It excludes instance provenance, source manifests, gold patches, post-fix commits, expected traces, and hidden tests.

Build an instance container from the repository root so the shared evaluator is included:

```bash
docker build -f instances/iab_0003/Dockerfile -t iab-0003 .
docker run --rm iab-0003
```

## Executable instances

| Instance | Real source | Failure | Simulator |
|---|---|---|---|
| `iab_0001` | ophyd issue #1242 / PR #1243 | Device connection-timeout default and override semantics | deterministic child-signal mock |
| `iab_0003` | ophyd issue #1218 / PR #1219 | configured trigger value ignored | stateful detector trigger simulator |
| `iab_0005` | InstrumentKit issue #439 / PR #440 | `auth=None` breaks legacy TCP/IP driver constructors | socket/communicator mock |

## Evaluation semantics

- `fail_to_pass`: reproduces the reported upstream failure.
- `regression`: preserves documented existing behavior.
- `state_trace`: records device-facing actions and state transitions.
- `gold_differential`: compares ordered semantic checkpoints while allowing extra implementation events and timestamps.
- `minefield`: rejects hard-coded simulator values, duplicate actions, swallowed errors, invalid precedence, and bypassed constructor semantics.

The evaluator and unified-diff applier use only the Python standard library. Mining additionally uses PyYAML.

## Validation

Run the project-wide gate:

```bash
python3 scripts/validate_phase1.py
```

It checks counts, provenance, metadata, required files, pre-fix failure, gold-patch success, model-patch substitution, and JSON report generation for all executable instances.

See [the instance schema](docs/instance_schema.md), [the phase-1 report](docs/phase1_report.md), and [the Micro-Manager phase report](docs/micro_manager_phase_report.md) for the full contract and limitations.
