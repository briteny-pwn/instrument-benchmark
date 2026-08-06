# OpenFIBSEM Lift-out Benchmark Instance Design

Date: 2026-08-06

Status: approved and implemented

Target architecture: distributed `instrument` / `instance` / `evaluator`

Proposed instance ID: `fibsem_liftout_v1`

## Objective

Add a distributed benchmark instance in which a candidate independently
implements a four-step FIB-SEM lift-out experiment against a hidden
OpenFIBSEM three-dimensional simulator. The experiment must:

1. prepare and cut a sample while retaining a controlled source bridge;
2. connect the manipulator needle to the sample by deposition, then cut the
   source bridge;
3. transfer the sample to a scenario-provided target pose and connect it to
   the target by a second deposition;
4. cut the needle connection, retract the needle, and leave the sample
   attached at the target.

Before these four scored steps, the candidate must pass a non-scored Preflight
gate covering basic microscope functions. Every step produces an observable
3D scene, component meshes, and SEM/FIB images. The evaluator scores trusted
simulator state and a complete event journal rather than similarity to a gold
workflow or claims in candidate output.

The public nominal scenario is accompanied by four hidden fixed scenarios and
five deterministic seeded scenarios. Hidden scenarios vary sample dimensions,
initial needle offset, and target pose while preserving a common schema and a
pre-validated solvable workspace.

## Non-goals

- This instance does not claim transfer to a physical microscope.
- It does not evaluate image-based autonomous feature detection. Scenario
  geometry and target frames are supplied as structured inputs.
- It does not require a candidate to reproduce the patterns, helper functions,
  or mesh sequence in `example/simulator_workflow.py`.
- It does not compare candidate meshes point-for-point with a reference run.
- It does not include post-placement lamella thinning.
- It does not expose OpenFIBSEM simulator internals, PyVista meshes, trusted
  component labels, hidden scenarios, or scoring implementation to the
  candidate.

## Repository responsibilities

### `instrument`

The orchestrator repository owns only generic distribution and invocation
concerns:

- `configs/fibsem_liftout_v1.yaml` selects the instance and evaluator IDs,
  repository checkouts, candidate submission, limits, fixed/seeded scenario
  counts, and artifact report path.
- The run contract is extended to register `fibsem_liftout_v1` without adding
  FIB-SEM semantics to the generic orchestrator.
- The trusted evaluator image build includes the pinned evaluator checkout and
  the pinned OpenFIBSEM runtime needed by the sim sibling.
- The final report records all repository commits, the pinned OpenFIBSEM source
  commit, evaluator/candidate/sim image identities, Docker evidence, artifact
  hashes, and cleanup outcomes.

The orchestrator never imports OpenFIBSEM, the hidden simulator service, the
geometry oracle, or scoring code on the host.

The three-repository architecture accepts independently sourced instances.
Each evaluator selects its own locked runtime profile; instances do not inherit
another instance's dependencies or execution semantics. In particular, the
FIBSEM evaluator image is built from `fibsem-evaluator.Dockerfile`, the pinned
OpenFIBSEM source, and the FIBSEM wheelhouse only. It does not contain or depend
on the PyVISA runtime profile.

### `instance`

The public instance repository owns candidate-visible material only:

```text
fibsem_liftout_v1/
  ACCEPTANCE.md
  Dockerfile
  image.lock.yaml
  instance.yaml
  prompt.md
  result.schema.json
  scenario.schema.json
  scenarios/nominal.json
  docs/
    experiment-contract.md
    allowed-api.md
    artifacts.md
    coordinate-frames.md
  fibsem_iab/
    __init__.py
    client.py
    microscope.py
    protocol.py
    structures.py
  starter/
    __init__.py
    solution.py
  tests/
    test_public_client.py
    test_public_protocol.py
    test_visible_boundary.py
```

It contains no OpenFIBSEM simulator implementation, reference workflow,
trusted mesh labels, hidden scenario values, evaluator journal, geometry
oracle, expected metrics, score weights, or adversarial submissions.

### `evaluator`

The private evaluator repository owns all benchmark truth:

```text
evaluators/fibsem_liftout_v1/
  evaluator.yaml
  simulator_service/
    service.py
    broker.py
    journal.py
    instrumented_microscope.py
    checkpoint_exporter.py
    scenario.py
  scenarios/
    hidden_small.json
    hidden_large.json
    hidden_needle_offset.json
    hidden_target_pose.json
  geometry/
    connectivity.py
    metrics.py
    oracle.py
  scoring.py
  reports.py
  reference/solution.py
  negatives/
  tests/
```

The evaluator pins the trusted OpenFIBSEM simulator source and its dependencies.
The initial implementation targets the current simulator behavior represented
by local OpenFIBSEM commit `2ebccb8b`; the final lock records the full commit,
source tree digest, dependency lock, and image digest.

## Distributed runtime architecture

Each world uses the existing trusted-outer-evaluator pattern with two workload
siblings:

```text
trusted outer evaluator (Docker authority)
  ├── candidate sibling, UID 10001, network=none
  │     solution.py + public fibsem_iab client + scenario input
  │
  └── sim sibling, UID 11001, network=none
        hidden OpenFIBSEM simulator + journal + checkpoint exporter + oracle input

candidate sibling ── run-scoped Unix socket ──> sim sibling
```

Both siblings have read-only root filesystems, all capabilities dropped,
`no-new-privileges`, resource limits, and no network. Only the trusted outer
evaluator receives the Docker socket. The candidate sees a read-only transport
directory and a bounded writable result directory. It does not see simulator
files, world generation state, evidence, trusted artifacts, or the outer
request/report.

The sim sibling sees no candidate workspace. It writes its journal, trusted
snapshots, and step artifacts to an evaluator-only evidence mount. After the
candidate stops, the outer evaluator validates this evidence and publishes a
read-only artifact bundle alongside the final report.

## Candidate contract

The candidate implements only:

```python
def run_experiment(microscope, scenario, checkpoint, output_dir) -> dict:
    ...
```

The candidate bootstrap constructs the public `fibsem_iab` microscope proxy,
loads the concrete scenario supplied for the current world, and invokes the
function. The concrete hidden scenario values are visible to the candidate at
runtime because they describe the task to solve; they are not visible to the
model author before evaluation.

Arguments have the following contracts:

- `microscope` implements the documented, serializable subset of public
  OpenFIBSEM operations.
- `scenario` is an immutable object validated against
  `scenario.schema.json`.
- `checkpoint(step_id, summary=None)` accepts exactly `step_1` through
  `step_4`, once each and in order. It asks the trusted sim service to freeze a
  semantic state, acquire images, export meshes, and record artifact hashes.
- `output_dir` is candidate-writable and may contain only `result.json` and
  bounded candidate diagnostics. The trusted step artifacts are produced
  separately and published by the evaluator.

The returned dictionary must equal the object written to `result.json`. It
contains the instance ID, scenario ID, four requested checkpoint IDs, optional
candidate notes, and overall completion status. It is diagnostic input only;
it is not trusted for scoring.

## Allowed and forbidden APIs

The public proxy exposes a documented subset of OpenFIBSEM behavior:

- connection and capability status;
- SEM/FIB image acquisition and image metadata;
- stage position, bounded absolute/relative movement, and stop;
- manipulator state, position, insertion, bounded movement, retraction, and
  stop;
- public beam, detector, and imaging settings needed by the experiment;
- public pattern construction and execution for cutting and deposition;
- pattern pause, resume, stop, and completion status;
- GIS/deposition operations required by the public task;
- the generic checkpoint/export request.

Only JSON-compatible scalars, bounded arrays, quantities, enums, image arrays,
and public setting records cross the Unix socket. The protocol uses bounded,
length-prefixed messages, unique request IDs, strict tagged values, exact
operation schemas, and typed errors.

The candidate may not:

- import or copy `example.simulator_workflow` or another complete workflow;
- import `fibsem.model3d`, `SimulatorMicroscope`, PyVista, the evaluator, or
  hidden simulator packages;
- call names beginning with `_` on the proxy or mutate simulator meshes;
- access hidden files, evidence mounts, Docker, subprocesses, or the network;
- synthesize trusted artifacts or replace files produced by the checkpoint
  exporter.

Static import scanning and runtime audit/protocol checks both enforce the
boundary. A public method not listed in `allowed-api.md` is rejected even if a
simulator implementation happens to contain it.

## Scenario contract

Each scenario provides:

- `scenario_id` and deterministic seed;
- source, sample, needle, target, and Preflight-coupon frames;
- planned sample dimensions and protected region;
- allowed cutting and deposition work envelopes;
- needle approach frame and attachment face;
- target pose and attachment face;
- movement bounds, safe approach distance, and collision exclusions;
- imaging and patterning limits;
- public units and coordinate-frame definitions.

The nominal template follows the repository's current lift-out scale. Its
planned sample dimensions are `14 um × 8 um × 10 um`, with a needle attachment
on the sample side face and a distinct target substrate reached by a large
stage transfer. Exact frames, poses, pattern limits, and other nominal values
live in `scenarios/nominal.json`; every hidden scenario uses the same keys and
units.

All task coordinates are expressed through named frames rather than raw global
mesh coordinates. A candidate therefore computes actions from `scenario`
instead of relying on nominal constants.

## Preflight gate

Preflight is required but carries no capability points. It must finish before
the first destructive operation in the task ROI. It checks:

1. `ping` and connection status;
2. valid SEM and FIB images with finite pixel data and metadata;
3. a small stage move followed by return within tolerance;
4. safe manipulator insertion, a small bounded move, and retraction;
5. a small cut in the isolated Preflight coupon with observable negative volume
   change;
6. a small deposition in the isolated coupon with observable positive volume
   change.

The coupon is separated from the task ROI by at least two characteristic sample
lengths. Coupon operations cannot create connectivity to the task sample,
source, needle, or target. Preflight failure stops the world and triggers safe
cleanup.

## Four scored steps

### Step 1: sample preparation and cutting

The candidate locates the provided ROI, acquires baseline SEM/FIB images,
creates a protection layer, mills and polishes trenches, and performs a U-cut.
It may choose its own pattern decomposition. At `checkpoint("step_1")`:

- sample-to-source connectivity is true through one controlled bridge region;
- sample-to-needle and sample-to-target connectivity are false;
- the sample is one principal connected component;
- retained sample volume is at least 75% of planned sample volume;
- all material changes remain inside the allowed Step 1 work envelope.

### Step 2: needle attachment and source separation

The candidate inserts and aligns the needle, creates a first deposition joint,
verifies the joint, cuts the remaining source bridge, and performs a small
carry movement. At `checkpoint("step_2")`:

- sample-to-source connectivity is false;
- sample-to-needle connectivity is true with a sufficient joint section;
- sample-to-target connectivity is false;
- the sample follows the needle during the carry movement;
- journal order proves the needle joint existed before the source bridge was
  cut.

### Step 3: transfer and target attachment

The candidate transfers the needle-supported sample to the scenario target,
aligns the sample with `target_pose`, and creates a second deposition joint. At
`checkpoint("step_3")`:

- sample-to-source connectivity remains false;
- sample-to-needle and sample-to-target connectivity are both true;
- sample position and orientation are inside adaptive tolerances;
- the target joint lies inside the declared target attachment region;
- journal order proves target alignment preceded target deposition.

### Step 4: needle separation and final acceptance

The candidate cuts only the needle-side connection, preserves the target-side
joint, retracts the needle, and acquires final SEM/FIB images. At
`checkpoint("step_4")`:

- sample-to-source and sample-to-needle connectivity are false;
- sample-to-target connectivity is true;
- the needle is retracted beyond the safe distance and has no collision;
- final sample pose remains inside tolerance;
- retained sample volume is at least 65% of planned sample volume;
- the simulator is idle, with no active patterning or unsafe movement.

## Necessary partial order

The journal must prove:

```text
Preflight complete
  < destructive task-ROI operation
  < Step 1 checkpoint
  < needle deposition established
  < source bridge cut
  < Step 2 checkpoint
  < transfer
  < target pose reached
  < target deposition established
  < Step 3 checkpoint
  < needle joint cut
  < needle retracted
  < Step 4 checkpoint
```

Operations that commute, such as diagnostic SEM/FIB images or harmless state
queries, are not globally ordered. The evaluator checks only dependencies
needed for physical correctness and safety.

## Adaptive geometry tolerances

Let:

```text
L = cube_root(planned_sample_volume)
```

The default tolerances are:

- position: `clamp(0.08 * L, 0.5 um, 2.0 um)`;
- effective joint scale: `clamp(0.03 * L, 0.2 um, 1.0 um)`;
- final orientation: `5 degrees`;
- safe needle retraction: `clamp(0.50 * L, 5 um, 20 um)`.

Connectivity is computed by the trusted oracle using labeled component meshes,
a scale-aware contact epsilon smaller than the effective joint scale, and a
minimum connected cross-section. Mere bounding-box overlap is insufficient.
The oracle records raw and normalized distance, overlap, contact, connected
component, pose, and volume metrics in each world report.

The values above are part of the public contract. Hidden scenarios vary
geometry, not the meaning of success.

## Trusted event journal

The instrumented microscope records every public operation with:

- run, world, connection, request, and operation identity;
- monotonic sequence and timestamp;
- validated arguments or their bounded digest representation;
- result, typed rejection, or infrastructure error;
- before/after semantic state and mesh digests when state changes;
- signed material-volume change and affected work envelope;
- pattern type, purpose, and execution lifecycle;
- stage/manipulator pose transitions and collision results;
- checkpoint request, snapshot, export, and artifact hashes;
- cleanup source and terminal state.

Events form a canonical SHA-256 hash chain. Large arrays and meshes are stored
as trusted artifacts and represented in the journal by shape, size, and digest;
their event records are never omitted. The evaluator independently validates
sequence, hashes, identities, event pairing, lifecycle completeness, and final
summary accounting.

## Checkpoint artifacts

The trusted exporter produces this bundle for each scored step:

```text
artifacts/<world_id>/step_N/
  scene.glb
  scene.stl
  sem.png
  fib.png
  checkpoint.json
  components/
    source.stl
    sample.stl
    needle.stl
    target.stl
    deposition.stl
```

- `scene.glb` preserves the complete scene, component hierarchy, transforms,
  and distinct materials for interactive viewing.
- `scene.stl` is a merged geometry export.
- component STL files support independent inspection and geometry tools.
- `sem.png` and `fib.png` are trusted images acquired at the checkpoint.
- `checkpoint.json` contains schema version, identities, scenario digest,
  journal sequence/hash, semantic connectivity, pose/volume metrics, and all
  artifact sizes and SHA-256 hashes.

All paths are regular files below the declared artifact root. The collector
rejects symlinks, hard links, unexpected files, oversized artifacts, malformed
meshes/images, digest mismatches, and GLB/STL component bounds inconsistent with
the trusted snapshot.

## Scenario matrix

The complete suite contains ten worlds:

| World | Sample scale | Needle offset | Target pose |
|---|---:|---:|---:|
| public `nominal` | `1.00` | nominal | nominal |
| hidden `small` | `0.75` | nominal | nominal |
| hidden `large` | `1.25` | nominal | nominal |
| hidden `needle_offset` | `1.00` | each axis up to `0.20L` | nominal |
| hidden `target_pose` | `1.00` | nominal | translation up to `0.50L`, rotation up to `8°` |
| `seeded_01` through `seeded_05` | `0.75–1.25` | combined bounded offset | combined bounded translation/rotation |

Seeded worlds use fixed evaluator-owned seeds. Generation rejects initial
collisions, unreachable poses, insufficient cutting margins, invalid work
envelopes, and degenerate meshes. Every checked-in or generated world must pass
the reference solution before it can enter evaluation. The same seed and
evaluator version must produce byte-identical canonical JSON scenario bytes.

Every world runs in fresh candidate and sim siblings. Candidate state, Python
module state, artifacts, sockets, and meshes never carry between worlds.

## Scoring

Capability score is 0–100:

| Dimension | Points | Evidence |
|---|---:|---|
| Step 1 | 20 | preparation, work envelope, controlled bridge, sample integrity |
| Step 2 | 25 | needle pose/joint, order, source separation, carry movement |
| Step 3 | 25 | connection continuity, target pose, target joint, dual connectivity |
| Step 4 | 20 | selective cut, target retention, safe retraction, final state |
| Artifacts | 10 | complete valid GLB, merged/component STL, PNG, JSON evidence |

Each world receives partial credit from its observed trusted state. A missing
checkpoint earns no later-step points but does not erase earlier valid evidence.
Suite dimension scores are arithmetic means across all ten worlds.

Preflight contributes no points. It is a non-compensable gate so a candidate
cannot earn experiment points from a simulator whose basic operations were not
demonstrated.

Evidence confidence is independent of capability score. It reports journal,
geometry, artifact, scenario, reproducibility, and infrastructure coverage.

## Strict gates

Overall strict pass requires:

- Preflight success in every world;
- public nominal plus all four fixed hidden worlds strict-pass;
- at least four of five seeded worlds strict-pass;
- every passing world satisfies all necessary partial-order constraints;
- no world ends in an unsafe terminal state, including a failed seeded world;
- no forbidden workflow, private simulator API, hidden-file, subprocess,
  Docker, or network access;
- all mandatory connectivity gates use trusted geometry evidence;
- suite score is at least 90;
- evaluator infrastructure remains valid and non-retryable candidate outcomes
  are represented inside the report.

## Failure handling and cleanup

Candidate outcomes include:

- `candidate_timeout`;
- `candidate_exception`;
- `invalid_checkpoint`;
- `missing_or_invalid_artifact`;
- `unsafe_motion` or `collision`;
- `geometry_operation_failed`;
- `forbidden_access`;
- `invalid_result`.

These are normal evaluation results. Valid evidence collected before failure
may earn partial credit, but strict pass is false.

Trusted build, container, Docker daemon, journal-finalization, evidence-read,
or artifact-export failures are retry-eligible infrastructure failures and
cannot be converted into candidate scores.

On every exit path the sim service:

1. cancels and freezes active operations;
2. stops patterning and stage/manipulator movement;
3. records a pre-cleanup snapshot;
4. retracts the needle when possible without moving the placed sample;
5. records a post-cleanup snapshot and safety result;
6. finalizes the journal and summary atomically;
7. exits before the outer evaluator removes both workload siblings.

Cleanup events are labeled `candidate` or `forced`; forced cleanup cannot count
as candidate compliance.

## Validation and adversarial coverage

### Unit and contract tests

- public protocol and client round trips;
- scenario and result schema validation;
- static visible/hidden boundary scans;
- deterministic scenario generation;
- geometry connectivity, pose, volume, and tolerance calculations on synthetic
  meshes;
- hash-chain, snapshot, GLB, STL, PNG, and artifact collector validation;
- partial-order and score boundary tests;
- forced-safe cleanup and infrastructure classification.

### Reference acceptance

The reference solution must:

- pass all ten worlds from clean containers;
- score 100 and strict-pass;
- produce parseable, bounded artifacts at all four checkpoints;
- produce semantically identical normalized reports, canonical geometry
  hashes, and image hashes on repeated runs with the same seeds; container IDs,
  wall-clock timestamps, and other run-local identities are excluded from the
  comparison;
- leave no labeled containers, sockets, temporary roots, or active simulator
  operations.

### Negative submissions

Targeted negatives must prove failure for:

- cutting the source bridge before needle deposition;
- depositing at the needle but never cutting the source bridge;
- moving a mesh or claiming a checkpoint without experiment API evidence;
- hard-coding nominal dimensions or coordinates;
- reaching the target but omitting target deposition;
- cutting the needle before a valid target joint exists;
- cutting both the needle joint and target joint;
- leaving the needle connected or failing to retract it;
- copying nominal artifacts into hidden worlds;
- importing the existing workflow or private simulator/mesh APIs;
- writing fake checkpoint files or tampering with trusted artifacts;
- timing out or crashing during each of the four steps.

## Acceptance criteria

The instance is ready only when:

1. all public files are hash-pinned by `instance.yaml`;
2. the candidate image contains only public client/runtime material and no
   simulator or evaluator implementation;
3. the evaluator image contains a reproducibly pinned OpenFIBSEM runtime;
4. the dual-container isolation tests pass on native Linux Docker;
5. the reference suite passes ten worlds with score 100;
6. every targeted negative fails its intended gate;
7. scenario generation and repeated reference runs are deterministic;
8. every checkpoint artifact renders or parses successfully and agrees with
   trusted geometry;
9. failure injection proves forced cleanup and retry classification;
10. final reports contain complete repository, image, journal, geometry,
    artifact, and cleanup provenance.

Success on this simulation benchmark demonstrates correct OpenFIBSEM API use,
stateful lift-out sequencing, geometry-aware adaptation, and safe cleanup under
the modeled worlds. It does not establish safe operation on physical hardware.
