# OpenFIBSEM Lift-out Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the complete `fibsem_liftout_v1` four-step benchmark across the distributed `instance`, `evaluator`, and `instrument` repositories, with an isolated OpenFIBSEM simulator, trusted checkpoint artifacts, hidden scenarios, scoring, and end-to-end evidence.

**Architecture:** The public instance ships a typed, bounded Unix-socket client and concrete scenario input but no simulator internals. A trusted outer evaluator starts a candidate sibling and an OpenFIBSEM sim sibling, journals every allowed operation, freezes four semantic checkpoints, exports trusted mesh/image artifacts, and scores geometry plus necessary partial order. The generic instrument orchestrator validates the three repository contracts, stages the pinned OpenFIBSEM source into the evaluator build, and validates the final schema-version-3 report and provenance.

**Tech Stack:** Python 3.11, JSON Schema 2020-12, PyYAML, Unix domain sockets, Docker Engine API/CLI, OpenFIBSEM 0.5.5 at commit `2ebccb8b9721234ca66bb94de36d0f7cfe047af9`, PyVista/VTK, Pillow, NumPy, pytest/unittest.

## Global Constraints

- Benchmark repositories remain exactly `instrument`, `instance`, and `evaluator`; OpenFIBSEM is a pinned external source input, not a fourth benchmark contract.
- Candidate entrypoint is `run_experiment(microscope, scenario, checkpoint, output_dir) -> dict`.
- Candidate calls `checkpoint("step_1")` through `checkpoint("step_4")` exactly once and in order.
- Preflight is a mandatory, non-scored gate before destructive task-ROI operations.
- The suite is one public nominal world, four hidden fixed worlds, and five deterministic seeded worlds.
- Candidates may use only the documented `fibsem_iab` API and generic checkpoint callback; importing a complete workflow, `fibsem.model3d`, `SimulatorMicroscope`, evaluator packages, PyVista, subprocess, Docker, or network access is forbidden.
- Every checkpoint publishes `scene.glb`, merged `scene.stl`, SEM/FIB PNG files, `checkpoint.json`, and component STL files.
- Geometry tolerances use `L = cube_root(planned_sample_volume)`, position `clamp(0.08L, 0.5um, 2.0um)`, joint scale `clamp(0.03L, 0.2um, 1.0um)`, orientation `5 degrees`, and retraction `clamp(0.50L, 5um, 20um)`.
- Strict pass requires Preflight in every world, all five fixed worlds, at least four of five seeded worlds, valid partial order in each passing world, no unsafe terminal world, no forbidden access, trusted connectivity evidence, and suite score at least 90.
- Candidate sibling runs as `10001:10001`; sim sibling runs as `11001:11001`; both use `network=none`, read-only root filesystems, all capabilities dropped, and `no-new-privileges`.
- Preserve unrelated user changes, including `instance/.DS_Store`; never stage them.

## Repository File Map

### `instance`

- `fibsem_liftout_v1/instance.yaml`: public contract, hashes, limits, API boundary, and scoring declaration.
- `fibsem_liftout_v1/scenario.schema.json`: candidate-visible scenario contract.
- `fibsem_liftout_v1/result.schema.json`: candidate diagnostic result contract.
- `fibsem_liftout_v1/scenarios/nominal.json`: only checked-in public world.
- `fibsem_liftout_v1/fibsem_iab/protocol.py`: bounded canonical JSON RPC framing and typed errors.
- `fibsem_liftout_v1/fibsem_iab/structures.py`: immutable public vectors, poses, images, patterns, and scenario records.
- `fibsem_liftout_v1/fibsem_iab/microscope.py`: documented OpenFIBSEM-compatible proxy.
- `fibsem_liftout_v1/fibsem_iab/client.py`: environment bootstrap and checkpoint callback.
- `fibsem_liftout_v1/starter/solution.py`: intentionally incomplete candidate entrypoint using only public imports.
- `fibsem_liftout_v1/docs/*.md`, `prompt.md`, `ACCEPTANCE.md`: public task and API documentation.
- `fibsem_liftout_v1/Dockerfile`, `.dockerignore`, `image.lock.yaml`, `runtime/*`: locked candidate image.
- `fibsem_liftout_v1/tests/*.py`, repository `tests/test_fibsem_instance.py`: public contracts, protocol, hashes, and secrecy.

### `evaluator`

- `evaluators/fibsem_liftout_v1/models.py`: scenario, tolerance, semantic-state, and report types.
- `evaluators/fibsem_liftout_v1/scenario.py`: fixed-world loading and deterministic seeded generation.
- `evaluators/fibsem_liftout_v1/scenarios/*.json`: four hidden fixed worlds.
- `evaluators/fibsem_liftout_v1/protocol.py`: trusted side of bounded RPC protocol.
- `evaluators/fibsem_liftout_v1/journal.py`: canonical hash-chain journal.
- `evaluators/fibsem_liftout_v1/backend.py`: OpenFIBSEM simulator adapter and semantic mesh registry.
- `evaluators/fibsem_liftout_v1/instrumented_microscope.py`: allowed-operation dispatcher, validation, and audit.
- `evaluators/fibsem_liftout_v1/checkpoint_exporter.py`: atomic GLB/STL/PNG/JSON exports.
- `evaluators/fibsem_liftout_v1/service.py`: sim sibling lifecycle and forced cleanup.
- `evaluators/fibsem_liftout_v1/geometry/*.py`: connectivity, volume, pose, joint, and artifact consistency oracle.
- `evaluators/fibsem_liftout_v1/scoring.py`, `reports.py`: step scoring, gates, confidence, and schema-version-3 report.
- `evaluators/fibsem_liftout_v1/reference/solution.py`: adaptive reference workflow using public API only.
- `evaluators/fibsem_liftout_v1/negatives/*.py`: targeted adversarial candidates.
- `instrument_benchmark_evaluator/fibsem_run.py`: ten-world outer-evaluator suite.
- `instrument_benchmark_evaluator/container/fibsem_sim_runner.py`: sim sibling container lifecycle and evidence collection.
- `instrument_benchmark_evaluator/cli.py`, `contracts.py`, `candidate_backend.py`: instance dispatch and FIBSEM candidate bootstrap.

### `instrument`

- `configs/fibsem_liftout_v1.yaml`: three-repository run plus pinned OpenFIBSEM checkout.
- `schemas/run.schema.json`, `src/instrument_benchmark/contracts.py`: optional external-source fields and report v3 validation.
- `src/instrument_benchmark/evaluator_image.py`: tracked OpenFIBSEM source staging and digest evidence.
- `src/instrument_benchmark/orchestrator.py`: request/provenance forwarding and artifact publication.
- `container/evaluator.Dockerfile`, `container/evaluator-requirements.lock`, `container/wheelhouse/*`: offline trusted runtime.
- `scripts/vendor_openfibsem_wheels.py`: reproducible Linux/amd64 wheel download and manifest generation.
- `tests/test_fibsem_contracts.py`, `tests/test_evaluator_image.py`, `tests/integration/test_fibsem_dual_container_linux.py`: orchestration and runtime acceptance.

---

### Task 1: Public scenario, result, and manifest contracts

**Files:**
- Create: `instance/fibsem_liftout_v1/scenario.schema.json`
- Create: `instance/fibsem_liftout_v1/result.schema.json`
- Create: `instance/fibsem_liftout_v1/scenarios/nominal.json`
- Create: `instance/tests/test_fibsem_instance.py`
- Modify: `instance/schemas/instance.schema.json`

**Interfaces:**
- Produces: schema-valid immutable scenario containing `frames`, `sample`, `work_envelopes`, `limits`, and `tolerances`; result object containing `instance_id`, `scenario_id`, `checkpoints`, `completed`, and optional `notes`.
- Produces: schema-valid data that Task 3 registers under manifest task type `fibsem_liftout`.

- [ ] **Step 1: Write failing manifest and schema tests**

```python
def test_fibsem_nominal_scenario_is_public_and_schema_valid():
    instance = ROOT / "fibsem_liftout_v1"
    scenario = json.loads((instance / "scenarios/nominal.json").read_text())
    schema = json.loads((instance / "scenario.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(scenario)
    assert scenario["scenario_id"] == "nominal"
    assert scenario["sample"]["dimensions_um"] == [14.0, 8.0, 10.0]

def test_nominal_publishes_adaptive_tolerance_contract():
    scenario = json.loads((ROOT / "fibsem_liftout_v1/scenarios/nominal.json").read_text())
    assert scenario["tolerances"]["characteristic_length"] == "cuberoot_volume"
    assert scenario["tolerances"]["position"] == {
        "relative": 0.08,
        "minimum_um": 0.5,
        "maximum_um": 2.0,
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd instance && python -m pytest tests/test_fibsem_instance.py -q`
Expected: FAIL because `fibsem_liftout_v1` does not exist.

- [ ] **Step 3: Add strict schemas, nominal data, and manifest**

Use JSON Schema objects with `additionalProperties: false`; use micrometres and degrees as explicit numeric fields; define named source, sample, needle, target, coupon, approach, and target frames. Set nominal sample dimensions to `[14.0, 8.0, 10.0]`, expose the four adaptive tolerance formulas, and restrict target translation/rotation and candidate movement/pattern limits.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `cd instance && python -m pytest tests/test_fibsem_instance.py -q`
Expected: PASS; the existing registered-instance tests remain unchanged until Task 3 creates the complete manifest.

- [ ] **Step 5: Commit**

Run in `instance`: `git add schemas/instance.schema.json tests/test_fibsem_instance.py fibsem_liftout_v1 && git commit -m "feat: define FIBSEM lift-out scenario contract"`

### Task 2: Bounded public protocol and typed client

**Files:**
- Create: `instance/fibsem_liftout_v1/fibsem_iab/__init__.py`
- Create: `instance/fibsem_liftout_v1/fibsem_iab/protocol.py`
- Create: `instance/fibsem_liftout_v1/fibsem_iab/structures.py`
- Create: `instance/fibsem_liftout_v1/fibsem_iab/microscope.py`
- Create: `instance/fibsem_liftout_v1/fibsem_iab/client.py`
- Create: `instance/fibsem_liftout_v1/tests/test_public_protocol.py`
- Create: `instance/fibsem_liftout_v1/tests/test_public_client.py`

**Interfaces:**
- Produces: `MicroscopeClient(endpoint: Path)`, `load_scenario(path: Path) -> Scenario`, and `checkpoint_callback(client) -> Callable[[str, Mapping[str, object] | None], CheckpointReceipt]`.
- RPC operations: `ping`, `capabilities`, `acquire_image`, `get_stage_position`, `move_stage`, `stop_stage`, `get_manipulator_state`, `insert_manipulator`, `move_manipulator`, `retract_manipulator`, `stop_manipulator`, `run_cut`, `run_deposition`, `pattern_status`, `stop_pattern`, and `checkpoint`.

- [ ] **Step 1: Write failing codec and client tests**

```python
def test_frame_rejects_oversize_before_reading_payload():
    stream = io.BytesIO(struct.pack("!I", MAX_FRAME_BYTES + 1))
    with pytest.raises(ProtocolError, match="frame too large"):
        read_frame(stream)

def test_checkpoint_callback_enforces_public_step_ids():
    client = RecordingClient()
    checkpoint = checkpoint_callback(client)
    assert checkpoint("step_1").step_id == "step_1"
    with pytest.raises(ValueError, match="next checkpoint is step_2"):
        checkpoint("step_3")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd instance && python -m pytest fibsem_liftout_v1/tests/test_public_protocol.py fibsem_liftout_v1/tests/test_public_client.py -q`
Expected: FAIL with missing `fibsem_iab` modules.

- [ ] **Step 3: Implement canonical length-prefixed JSON RPC**

Set `MAX_FRAME_BYTES = 1_048_576`, `MAX_IMAGE_BYTES = 8_388_608`, strict request IDs, one request per connection lock, canonical JSON encoding, tagged finite arrays, timeout handling, and typed `ProtocolError`, `RemoteError`, and `ConnectionClosed`. Reject booleans where numeric fields are expected, NaN/Infinity, unknown tags, duplicate keys, absolute paths, and response request-ID mismatch.

- [ ] **Step 4: Implement immutable public structures and proxy**

Use frozen dataclasses `Vec3`, `Pose`, `ImageFrame`, `Pattern`, `Scenario`, and `CheckpointReceipt`. Validate all units, dimensions, finite values, array byte counts, work-envelope names, image beam values `SEM|FIB`, pattern purpose values, and deposition/cut polarity before sending RPC.

- [ ] **Step 5: Run protocol/client tests and verify GREEN**

Run: `cd instance && python -m pytest fibsem_liftout_v1/tests/test_public_protocol.py fibsem_liftout_v1/tests/test_public_client.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

Run in `instance`: `git add fibsem_liftout_v1/fibsem_iab fibsem_liftout_v1/tests && git commit -m "feat: add bounded FIBSEM public client"`

### Task 3: Candidate entrypoint, public documentation, and locked image

**Files:**
- Create: `instance/fibsem_liftout_v1/starter/__init__.py`
- Create: `instance/fibsem_liftout_v1/starter/solution.py`
- Create: `instance/fibsem_liftout_v1/instance.yaml`
- Create: `instance/fibsem_liftout_v1/prompt.md`
- Create: `instance/fibsem_liftout_v1/ACCEPTANCE.md`
- Create: `instance/fibsem_liftout_v1/docs/experiment-contract.md`
- Create: `instance/fibsem_liftout_v1/docs/allowed-api.md`
- Create: `instance/fibsem_liftout_v1/docs/artifacts.md`
- Create: `instance/fibsem_liftout_v1/docs/coordinate-frames.md`
- Create: `instance/fibsem_liftout_v1/.dockerignore`
- Create: `instance/fibsem_liftout_v1/Dockerfile`
- Create: `instance/fibsem_liftout_v1/runtime/requirements.lock`
- Create: `instance/fibsem_liftout_v1/image.lock.yaml`
- Create: `instance/fibsem_liftout_v1/tests/test_candidate_boundary.py`
- Create: `instance/fibsem_liftout_v1/tests/test_container.py`
- Modify: `instance/tests/test_instance.py`

**Interfaces:**
- Candidate Docker bootstrap imports `/workspace/solution.py`, loads `/run/iab/scenario.json`, connects to `/run/iab/fibsem.sock`, calls the four-argument entrypoint, validates returned JSON against the public schema, and atomically writes `/output/result.json`.

- [ ] **Step 1: Write failing secrecy and container-context tests**

```python
def test_visible_tree_contains_no_private_simulator_markers():
    forbidden = {"simulatormicroscope", "pyvista", "geometry.oracle", "hidden_small"}
    for path in visible_text_files(INSTANCE):
        text = path.read_text(encoding="utf-8").lower()
        assert not forbidden.intersection(text.split())

def test_candidate_image_installs_only_public_runtime():
    dockerfile = (INSTANCE / "Dockerfile").read_text()
    assert "fibsem_iab" in dockerfile
    assert "openfibsem" not in dockerfile.lower()
    assert "USER 10001:10001" in dockerfile

def test_manifest_registers_exact_ten_world_suite():
    manifest = yaml.safe_load((INSTANCE / "instance.yaml").read_text())
    assert manifest["suite"] == {"fixed_worlds": 5, "seeded_worlds": 5}
    assert manifest["container"]["gateway_path"] == "/run/iab/fibsem.sock"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd instance && python -m pytest fibsem_liftout_v1/tests/test_candidate_boundary.py fibsem_liftout_v1/tests/test_container.py -q`
Expected: FAIL because public docs and image inputs are missing.

- [ ] **Step 3: Write the public contract and starter**

Document Preflight, the four checkpoints, necessary partial order, adaptive tolerances, output bundle, and allowed API signatures. The starter raises `NotImplementedError("implement the four-step lift-out experiment")` after showing imports and the exact signature; it must not contain a usable workflow sequence.

Create the final manifest only after all public and image files exist. Generalize repository contract tests to require exactly three registered instances and branch role/source assertions by `task_type`; keep all PyVISA-specific checks effective.

- [ ] **Step 4: Build the minimal locked candidate image**

Base on the existing pinned Python 3.11 slim digest, copy only `fibsem_iab` and the generic bootstrap, install only hash-locked PyYAML/typing dependencies from the instance wheelhouse, create UID/GID 10001, use a read-only-compatible `/workspace`, and set the generic bootstrap as entrypoint.

- [ ] **Step 5: Refresh all manifest hashes once**

Run a repository script that computes SHA-256 over every file under `docs`, `fibsem_iab`, `starter`, and `transport` plus the prompt/schemas, writes sorted `visible_files`, then computes sorted `container.context_files`. Re-run the hash test after the final manifest write and do not edit public files afterward without rerunning it.

- [ ] **Step 6: Run the complete instance suite and verify GREEN**

Run: `cd instance && python -m pytest -q`
Expected: all existing PyVISA tests and all new FIBSEM tests PASS; `.DS_Store` remains untracked and unstaged.

- [ ] **Step 7: Commit**

Run in `instance`: `git add fibsem_liftout_v1 tests schemas && git commit -m "feat: publish FIBSEM candidate package"`

### Task 4: Trusted scenario models and deterministic world generation

**Files:**
- Create: `evaluator/evaluators/fibsem_liftout_v1/__init__.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/models.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/scenario.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/scenarios/hidden_small.json`
- Create: `evaluator/evaluators/fibsem_liftout_v1/scenarios/hidden_large.json`
- Create: `evaluator/evaluators/fibsem_liftout_v1/scenarios/hidden_needle_offset.json`
- Create: `evaluator/evaluators/fibsem_liftout_v1/scenarios/hidden_target_pose.json`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_scenario.py`
- Modify: `evaluator/pyproject.toml`

**Interfaces:**
- Produces: `ScenarioSpec`, `AdaptiveTolerances`, `SemanticState`, `load_fixed_scenarios(public_nominal: Path)`, and `seeded_scenarios(count: int, base_seed: int)`.

- [ ] **Step 1: Write failing deterministic-generation tests**

```python
def test_tolerances_scale_and_clamp():
    assert AdaptiveTolerances.from_dimensions((14, 8, 10)).position_um == pytest.approx(0.8308, rel=1e-3)
    assert AdaptiveTolerances.from_dimensions((1, 1, 1)).position_um == 0.5
    assert AdaptiveTolerances.from_dimensions((100, 100, 100)).position_um == 2.0

def test_seeded_worlds_are_canonical_and_solvable():
    first = [world.canonical_bytes() for world in seeded_scenarios(5, 47000)]
    second = [world.canonical_bytes() for world in seeded_scenarios(5, 47000)]
    assert first == second
    assert len(set(first)) == 5
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_scenario.py -q`
Expected: FAIL with missing package.

- [ ] **Step 3: Implement immutable models and canonical JSON**

Reject unknown keys, non-finite numbers, invalid frame matrices, non-positive dimensions, unreachable bounds, collisions at initial state, and target/coupon envelopes that overlap the sample ROI. Canonical bytes use sorted compact ASCII JSON plus one newline.

- [ ] **Step 4: Add four fixed hidden worlds and seeded bounds**

Use scales `0.75` and `1.25`; hidden needle offset has each axis bounded by `0.20L`; hidden target pose has translation bounded by `0.50L` and rotation by `8 degrees`; seeded worlds combine scale `[0.75,1.25]`, offset, and pose using evaluator-owned seeds and deterministic rejection sampling capped at 100 attempts.

- [ ] **Step 5: Run scenario tests and verify GREEN**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_scenario.py -q`
Expected: PASS with exactly nine evaluator-private scenario documents/generations plus the public nominal input.

- [ ] **Step 6: Commit**

Run in `evaluator`: `git add pyproject.toml evaluators/fibsem_liftout_v1 && git commit -m "feat: add deterministic FIBSEM worlds"`

### Task 5: Trusted geometry oracle and artifact validation

**Files:**
- Create: `evaluator/evaluators/fibsem_liftout_v1/geometry/__init__.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/geometry/connectivity.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/geometry/metrics.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/geometry/oracle.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/geometry/artifacts.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_geometry.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_artifacts.py`

**Interfaces:**
- Consumes: labeled `MeshSnapshot` values from Task 7 and `ScenarioSpec` from Task 4.
- Produces: `GeometryMetrics` with source/needle/target connectivity, joint cross-sections, sample pose error, retained volume, collision, work-envelope changes, and canonical geometry hash.

- [ ] **Step 1: Write failing synthetic-mesh tests**

```python
def test_bbox_overlap_without_contact_is_not_connected():
    sample = box_mesh((0, 0, 0), (10, 8, 6))
    needle = box_mesh((9.9, 0, 0), (2, 2, 2)).translated((0, 0, 0.5))
    result = contact_metrics(sample, needle, epsilon_um=0.05, min_section_um=0.2)
    assert not result.connected

def test_valid_deposition_bridge_is_connected():
    result = evaluate_scene(scene_with_bridge(width_um=0.6), nominal_spec())
    assert result.sample_to_needle
    assert result.needle_joint_section_um >= result.tolerances.joint_scale_um
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_geometry.py evaluators/fibsem_liftout_v1/tests/test_artifacts.py -q`
Expected: FAIL with missing geometry modules.

- [ ] **Step 3: Implement scale-aware connectivity and pose metrics**

Normalize watertight triangle meshes, compute connected components, signed/closest distance, actual contact voxels at an epsilon below joint scale, cross-section, rigid pose error, retained volume, and collision. Bounding boxes are only a broad-phase filter. Canonical geometry hash sorts component names and quantized vertices/faces so exporter ordering does not change the score.

- [ ] **Step 4: Implement artifact-bundle validation**

Reject paths outside root, symlinks, hard links, unexpected names, files over declared limits, malformed GLB/STL/PNG/JSON, dimension mismatches, SHA-256 mismatches, missing component meshes, and component/scene bounds that disagree with the trusted snapshot.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_geometry.py evaluators/fibsem_liftout_v1/tests/test_artifacts.py -q`
Expected: PASS for contact, non-contact overlap, selective cuts, pose, volume, canonical hash, and artifact attacks.

- [ ] **Step 6: Commit**

Run in `evaluator`: `git add evaluators/fibsem_liftout_v1/geometry evaluators/fibsem_liftout_v1/tests && git commit -m "feat: add trusted FIBSEM geometry oracle"`

### Task 6: Hash-chain journal and bounded simulator protocol

**Files:**
- Create: `evaluator/evaluators/fibsem_liftout_v1/journal.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/protocol.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/instrumented_microscope.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_journal.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_protocol.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_dispatch.py`

**Interfaces:**
- Produces: `EventJournal(run_id, world_id)`, `FibsemBroker`, and `OperationDispatcher.dispatch(operation, arguments)`.
- Consumes: public operation names from Task 2 and backend interface from Task 7.

- [ ] **Step 1: Write failing journal/protocol tests**

```python
def test_journal_hash_chain_detects_mutation():
    journal = EventJournal("run", "world")
    journal.append("rpc.request", operation="ping")
    journal.append("rpc.result", operation="ping", ok=True)
    records = [event.to_dict() for event in journal.events]
    records[0]["fields"]["operation"] = "checkpoint"
    with pytest.raises(JournalError, match="hash"):
        validate_records(records, "run", "world")

def test_dispatch_rejects_private_or_unknown_operation():
    with pytest.raises(RejectedOperation):
        dispatcher.dispatch("_update_mesh", {})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_journal.py evaluators/fibsem_liftout_v1/tests/test_protocol.py evaluators/fibsem_liftout_v1/tests/test_dispatch.py -q`
Expected: FAIL with missing modules.

- [ ] **Step 3: Implement canonical journal and RPC broker**

Every request receives monotonic sequence, request identity, bounded argument digest, before/after semantic-state digest, result/rejection, operation lifecycle, and previous/event hashes. Export journal atomically as canonical JSONL and summary JSON; validate peer UID 10001 on Linux with `SO_PEERCRED` before accepting requests.

- [ ] **Step 4: Implement explicit operation dispatch**

Use a literal operation-to-handler mapping; never `getattr` candidate-provided names. Validate movement against workspace/collision limits, patterns against declared envelopes and polarity, checkpoint order against `step_1`…`step_4`, Preflight completion before task ROI, and reject all unlisted settings or private names.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_journal.py evaluators/fibsem_liftout_v1/tests/test_protocol.py evaluators/fibsem_liftout_v1/tests/test_dispatch.py -q`
Expected: PASS including truncation, oversize, malformed JSON, wrong UID, replay, unknown operation, and lifecycle cases.

- [ ] **Step 6: Commit**

Run in `evaluator`: `git add evaluators/fibsem_liftout_v1 && git commit -m "feat: journal and guard FIBSEM operations"`

### Task 7: OpenFIBSEM backend, checkpoint exporter, and sim service

**Files:**
- Create: `evaluator/evaluators/fibsem_liftout_v1/backend.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/checkpoint_exporter.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/service.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/fakes.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_backend.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_exporter.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_service.py`

**Interfaces:**
- Produces: `OpenFibsemBackend(spec)`, `CheckpointExporter(evidence_root)`, and `run_service(world_path, endpoint, evidence_root, run_id)`.
- Backend method set exactly matches Task 6 dispatcher and exposes evaluator-only `freeze_snapshot()`, `semantic_state()`, `cancel()`, and `force_safe()`.

- [ ] **Step 1: Write failing backend/service tests against a deterministic fake**

```python
def test_checkpoint_freezes_before_export(tmp_path):
    backend = RecordingBackend(nominal_spec())
    service = make_service(backend, tmp_path)
    receipt = service.checkpoint("step_1")
    assert backend.calls[:2] == ["freeze_snapshot", "acquire_checkpoint_images"]
    assert set(receipt.files) == REQUIRED_STEP_FILES

def test_failure_records_pre_and_post_cleanup_state(tmp_path):
    backend = RecordingBackend(nominal_spec(), fail_on="run_cut")
    result = run_service_once(backend, tmp_path)
    assert result.summary["cleanup"]["forced"]
    assert result.summary["cleanup"]["post_cleanup"]["safe"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_backend.py evaluators/fibsem_liftout_v1/tests/test_exporter.py evaluators/fibsem_liftout_v1/tests/test_service.py -q`
Expected: FAIL with missing backend/service/exporter.

- [ ] **Step 3: Implement the OpenFIBSEM adapter**

Import `fibsem` only inside the sim sibling. Construct `SimulatorMicroscope` through the pinned public setup API, register source/sample/needle/target/deposition meshes by semantic label, translate public pattern/movement/image structures to OpenFIBSEM settings, and derive snapshots from copied simulator meshes. Do not import `example/simulator_workflow.py`; use it only as prior scale evidence from the approved design.

- [ ] **Step 4: Implement atomic checkpoint export**

Freeze copied meshes under the backend lock, acquire deterministic SEM/FIB images, write colored hierarchical GLB, merged STL, five component STL files, lossless PNG files, and `checkpoint.json` into a temporary sibling directory, validate it with Task 5, fsync files/directories, then rename into `artifacts/<world>/step_N`.

- [ ] **Step 5: Implement service lifecycle and forced-safe cleanup**

Start the Unix socket with mode 0660, serve one authenticated candidate connection, stop/cancel active operations on every exit, record pre-cleanup snapshot, retract without moving a valid placed sample, record post-cleanup snapshot, finalize journal and summary atomically, and classify backend/import/export failures as infrastructure failures.

- [ ] **Step 6: Run fake-backed tests and real import smoke test**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_backend.py evaluators/fibsem_liftout_v1/tests/test_exporter.py evaluators/fibsem_liftout_v1/tests/test_service.py -q`
Expected: PASS.

Run with pinned source environment: `cd evaluator && PYTHONPATH=../fibsem/fibsem python -m pytest evaluators/fibsem_liftout_v1/tests/test_backend.py -m openfibsem -q`
Expected: PASS and report source commit `2ebccb8b9721234ca66bb94de36d0f7cfe047af9`.

- [ ] **Step 7: Commit**

Run in `evaluator`: `git add evaluators/fibsem_liftout_v1 && git commit -m "feat: run trusted OpenFIBSEM simulator service"`

### Task 8: Four-step scoring, reports, and strict gates

**Files:**
- Create: `evaluator/evaluators/fibsem_liftout_v1/scoring.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/reports.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/evaluator.yaml`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_scoring.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_reports.py`
- Modify: `evaluator/pyproject.toml`

**Interfaces:**
- Produces: `grade_world(spec, journal, checkpoints, terminal, runtime) -> FibsemWorldReport` and `aggregate_worlds(reports) -> FibsemEvaluationReport`.

- [ ] **Step 1: Write failing step and aggregate gate tests**

```python
def test_nominal_evidence_scores_100():
    report = grade_world(nominal_spec(), valid_journal(), valid_checkpoints(), safe_terminal(), valid_runtime())
    assert report.score == 100
    assert report.strict_pass

def test_four_of_five_seeded_may_pass_but_unsafe_failure_never_passes():
    worlds = five_fixed_passes() + four_seeded_passes() + [failed_seeded(unsafe=True)]
    report = aggregate_worlds(worlds)
    assert report.score >= 90
    assert not report.strict_pass
    assert not report.strict_gates["no_unsafe_terminal_world"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_scoring.py evaluators/fibsem_liftout_v1/tests/test_reports.py -q`
Expected: FAIL with missing scoring/report modules.

- [ ] **Step 3: Implement per-step scoring and necessary partial order**

Award Step 1/2/3/4 as 20/25/25/20 and trusted artifact completeness as 10. Derive gates from geometry and journal, never candidate JSON. Check only the approved dependency chain; allow diagnostic image/query events to commute. A missing checkpoint receives zero for it and later steps without erasing earlier valid points.

- [ ] **Step 4: Implement aggregate report schema version 3**

Average each dimension over ten worlds, report evidence confidence separately, require all five fixed plus four seeded passes, fail any unsafe terminal world or forbidden access, classify infrastructure failures as retry-eligible without a candidate score, and serialize all scenario/journal/geometry/artifact/runtime/cleanup provenance.

- [ ] **Step 5: Run scoring/report tests and verify GREEN**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_scoring.py evaluators/fibsem_liftout_v1/tests/test_reports.py -q`
Expected: PASS at every score/gate boundary.

- [ ] **Step 6: Commit**

Run in `evaluator`: `git add pyproject.toml evaluators/fibsem_liftout_v1 && git commit -m "feat: score four-step FIBSEM lift-out"`

### Task 9: Adaptive reference and adversarial submissions

**Files:**
- Create: `evaluator/evaluators/fibsem_liftout_v1/reference/solution.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/cut_source_early.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/no_source_cut.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/hardcoded_nominal.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/no_target_deposition.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/cut_needle_early.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/cut_both_joints.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/no_retract.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/fake_checkpoint.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/negatives/private_import.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_reference.py`
- Create: `evaluator/evaluators/fibsem_liftout_v1/tests/test_negatives.py`

**Interfaces:**
- Reference imports only `fibsem_iab`, computes every position/pattern from scenario frames and dimensions, completes Preflight, and returns schema-valid diagnostics.

- [ ] **Step 1: Write failing reference/negative matrix tests**

```python
def test_reference_uses_only_public_imports():
    assert imported_roots(REFERENCE) <= {"fibsem_iab", "json", "math", "pathlib"}

@pytest.mark.parametrize((name, gate), NEGATIVE_MATRIX.items())
def test_negative_fails_intended_gate(name, gate, evaluator_harness):
    report = evaluator_harness.run(NEGATIVES / f"{name}.py", nominal_spec())
    assert not report.strict_pass
    assert not report.strict_gates[gate]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_reference.py evaluators/fibsem_liftout_v1/tests/test_negatives.py -q`
Expected: FAIL because candidates do not exist.

- [ ] **Step 3: Implement adaptive reference workflow through public API**

Use scenario frames and `L` for all Preflight motions, protection/trench/U-cut patterns, needle alignment/deposition/source cut/carry, target transfer/alignment/deposition, selective needle cut, retraction, and four checkpoints. Never call exporter/backend/private APIs and never reuse the complete repository workflow.

- [ ] **Step 4: Implement one minimal negative per intended gate**

Each negative differs from the reference only at the behavior named by its file, so the intended missing state/order/forbidden-access gate is the first decisive failure. Include crash/timeout injection as test-generated candidates rather than checked-in workflow copies.

- [ ] **Step 5: Run reference and negative tests and verify GREEN**

Run: `cd evaluator && python -m pytest evaluators/fibsem_liftout_v1/tests/test_reference.py evaluators/fibsem_liftout_v1/tests/test_negatives.py -q`
Expected: reference passes the fake-backed ten-world suite; every negative fails its declared gate.

- [ ] **Step 6: Commit**

Run in `evaluator`: `git add evaluators/fibsem_liftout_v1 && git commit -m "test: add FIBSEM reference and adversarial matrix"`

### Task 10: Evaluator dual-container suite integration

**Files:**
- Create: `evaluator/instrument_benchmark_evaluator/fibsem_run.py`
- Create: `evaluator/instrument_benchmark_evaluator/container/fibsem_sim_runner.py`
- Create: `evaluator/tests/test_fibsem_run.py`
- Create: `evaluator/tests/test_fibsem_sim_runner.py`
- Modify: `evaluator/instrument_benchmark_evaluator/cli.py`
- Modify: `evaluator/instrument_benchmark_evaluator/contracts.py`
- Modify: `evaluator/instrument_benchmark_evaluator/candidate_backend.py`
- Modify: `evaluator/pyproject.toml`

**Interfaces:**
- Produces: `run_fibsem_world(...)` and `run_fibsem_full_suite(...)`; sim runner starts `serve-fibsem-sim` in a sibling using the exact evaluator image ID and returns journal/checkpoint/runtime evidence.

- [ ] **Step 1: Write failing dispatch and lifecycle tests**

```python
def test_cli_dispatches_fibsem_without_changing_pyvisa_dispatch():
    assert evaluator_kind("fibsem_liftout_v1") == "fibsem"
    assert evaluator_kind("pyvisa_dut_validation_v2") == "pyvisa_v2"

def test_fibsem_runner_mounts_no_candidate_or_request_files():
    spec = runner.start_spec(...)
    assert spec.network_mode == "none"
    assert spec.user == "11001:11001"
    assert all("workspace" not in mount.source for mount in spec.mounts)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd evaluator && python -m pytest tests/test_fibsem_run.py tests/test_fibsem_sim_runner.py -q`
Expected: FAIL with missing FIBSEM runner and unsupported instance ID.

- [ ] **Step 3: Implement FIBSEM instance settings and candidate bootstrap**

Accept scenario path and endpoint environment only for `fibsem_liftout_v1`; copy the public `fibsem_iab` tree and candidate solution into the candidate workspace; generate bootstrap that calls the exact four-argument entrypoint; retain existing PyVISA behavior unchanged.

- [ ] **Step 4: Implement sim sibling and ten-world outer loop**

For each world create distinct transport/evidence/workspace/output roots, start the sim sibling, invoke candidate sibling, finalize sim even after timeout/crash, validate evidence, grade trusted state, and remove both containers. Run public nominal plus four fixed in declared order and five seeded worlds from `repeated_base_seed`.

- [ ] **Step 5: Run focused and full evaluator unit suites**

Run: `cd evaluator && python -m pytest tests/test_fibsem_run.py tests/test_fibsem_sim_runner.py -q`
Expected: PASS.

Run: `cd evaluator && python -m pytest -q`
Expected: all previous PyVISA and new FIBSEM non-Docker tests PASS.

- [ ] **Step 6: Commit**

Run in `evaluator`: `git add instrument_benchmark_evaluator evaluators pyproject.toml tests && git commit -m "feat: run FIBSEM dual-container suites"`

### Task 11: Instrument run contract, OpenFIBSEM source staging, and report v3

**Files:**
- Create: `instrument/configs/fibsem_liftout_v1.yaml`
- Create: `instrument/tests/test_fibsem_contracts.py`
- Modify: `instrument/schemas/run.schema.json`
- Modify: `instrument/src/instrument_benchmark/contracts.py`
- Modify: `instrument/src/instrument_benchmark/orchestrator.py`
- Modify: `instrument/src/instrument_benchmark/evaluator_image.py`
- Modify: `instrument/tests/test_evaluator_image.py`
- Modify: `instrument/tests/test_orchestrator.py`

**Interfaces:**
- Run config adds optional `openfibsem_checkout` and exact `openfibsem_commit`; both are mandatory only for evaluator ID `fibsem_liftout_v1`.
- Evaluator image evidence adds nullable `openfibsem_commit` and `openfibsem_source_sha256` without changing PyVISA evidence.

- [ ] **Step 1: Write failing configuration, staging, and report tests**

```python
def test_fibsem_config_pins_openfibsem_source():
    config = load_run_config(ROOT / "configs/fibsem_liftout_v1.yaml")
    assert config.openfibsem_commit == "2ebccb8b9721234ca66bb94de36d0f7cfe047af9"

def test_report_v3_requires_all_fibsem_evidence():
    with pytest.raises(ContractError, match="checkpoint evidence"):
        validate_evaluator_report(incomplete_report(), "fibsem_liftout_v1")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd instrument && python -m pytest tests/test_fibsem_contracts.py tests/test_evaluator_image.py tests/test_orchestrator.py -q`
Expected: FAIL with unsupported run fields/evaluator ID.

- [ ] **Step 3: Extend the run contract conditionally**

Keep schema version 1 and all existing required keys. Permit exactly the two optional OpenFIBSEM keys; reject one without the other, wrong repository root, dirty or mismatched commit, and their presence for non-FIBSEM evaluators. Record external dependency provenance separately from the three benchmark repositories.

- [ ] **Step 4: Stage a minimal tracked OpenFIBSEM source tree**

Copy only tracked `fibsem/**`, `pyproject.toml`, `setup.py`, `LICENSE`, and required package data from the exact commit checkout into `context/openfibsem`; reject symlinks, dirty checkout, commit mismatch, untracked inputs, or source files outside the allowlist. Add all bytes to the build manifest and compute a canonical source-tree SHA-256.

- [ ] **Step 5: Validate and publish FIBSEM report/artifacts**

Require schema version 3, exactly ten world IDs, checkpoint evidence and artifact hashes, two sibling runtime evidence blocks, journal/geometry/cleanup confidence, evaluator and OpenFIBSEM identities, strict-gate types, and bounded score. Copy evaluator-published artifacts to the configured report sibling directory only after validation.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `cd instrument && python -m pytest tests/test_fibsem_contracts.py tests/test_evaluator_image.py tests/test_orchestrator.py -q`
Expected: PASS and unchanged PyVISA assertions.

- [ ] **Step 7: Commit**

Run in `instrument`: `git add configs schemas src tests && git commit -m "feat: orchestrate distributed FIBSEM benchmark"`

### Task 12: Offline trusted OpenFIBSEM runtime lock

**Files:**
- Create: `instrument/scripts/vendor_openfibsem_wheels.py`
- Create: `instrument/container/openfibsem-requirements.lock`
- Create: `instrument/container/openfibsem-wheelhouse/manifest.json`
- Create: generated Linux/amd64 wheels under `instrument/container/openfibsem-wheelhouse/`
- Modify: `instrument/container/evaluator.Dockerfile`
- Modify: `instrument/src/instrument_benchmark/evaluator_image.py`
- Create: `instrument/tests/test_openfibsem_runtime_lock.py`

**Interfaces:**
- `vendor_openfibsem_wheels.py --source <checkout> --destination <wheelhouse> --platform manylinux_2_17_x86_64 --python-version 311` resolves only the pinned source lock, verifies wheel tags, writes hashes to both lock and manifest, and never mutates the source checkout.

- [ ] **Step 1: Write failing wheel-lock and Dockerfile tests**

```python
def test_openfibsem_lock_matches_wheelhouse():
    lock = parse_hash_lock(ROOT / "container/openfibsem-requirements.lock")
    manifest = load_manifest(ROOT / "container/openfibsem-wheelhouse/manifest.json")
    assert set(lock.wheel_hashes) == set(manifest["files"])
    assert all(record["platform"] == "manylinux_x86_64" for record in manifest["files"].values())

def test_dockerfile_installs_openfibsem_without_network():
    text = normalize(ROOT / "container/evaluator.Dockerfile")
    assert "pip install --no-index --require-hashes" in text
    assert "/build/openfibsem" in text
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd instrument && python -m pytest tests/test_openfibsem_runtime_lock.py -q`
Expected: FAIL because the OpenFIBSEM lock and wheelhouse do not exist.

- [ ] **Step 3: Implement and run the deterministic vendor script**

Resolve OpenFIBSEM runtime dependencies for CPython 3.11 Linux/amd64, download wheels only, reject sdists and floating versions, record package/version/filename/SHA-256/size/platform, and sort all output. Run it once with network access into the tracked wheelhouse, then rerun in `--verify` mode without network.

- [ ] **Step 4: Install the optional runtime in the evaluator image**

Always stage an `optional-runtime.json`. For FIBSEM builds, copy verified wheels and source, install dependencies with `--no-index --require-hashes`, then install OpenFIBSEM and evaluator with `--no-deps --no-build-isolation`. For PyVISA builds, assert the optional runtime is absent and preserve the current image contents and user.

- [ ] **Step 5: Run lock tests and evaluator build-context tests**

Run: `cd instrument && python -m pytest tests/test_openfibsem_runtime_lock.py tests/test_evaluator_image.py -q`
Expected: PASS, including tampered-wheel, source-commit, and build-manifest negatives.

- [ ] **Step 6: Commit**

Run in `instrument`: `git add scripts container src tests && git commit -m "build: lock OpenFIBSEM evaluator runtime"`

### Task 13: Native-Linux dual-container, artifact, and determinism acceptance

**Files:**
- Create: `evaluator/tests/integration/test_fibsem_dual_container_linux.py`
- Create: `evaluator/tests/integration/test_fibsem_full_suite_linux.py`
- Create: `instrument/tests/integration/test_fibsem_dual_container_linux.py`
- Create: `instrument/scripts/validate_fibsem_benchmark.py`
- Create: generated ignored report `instrument/reports/fibsem_liftout_v1.json`

**Interfaces:**
- Produces a clean-container reference report with ten worlds, score 100, strict pass, four complete artifact bundles per world, exact three-repository plus OpenFIBSEM provenance, and no surviving labeled resources.

- [ ] **Step 1: Write Docker integration tests before enabling the route**

```python
@pytest.mark.skipif(not native_linux_docker(), reason="requires native Linux Docker")
def test_reference_full_suite_is_strict_and_isolated(distributed_checkout):
    report = run_distributed("fibsem_liftout_v1", reference_solution())
    assert report["score"] == 100
    assert report["strict_pass"]
    assert len(report["worlds"]) == 10
    assert no_managed_resources(report["run_id"])
```

- [ ] **Step 2: Run tests and verify RED**

Run on native Linux: `python -m pytest evaluator/tests/integration/test_fibsem_dual_container_linux.py instrument/tests/integration/test_fibsem_dual_container_linux.py -q`
Expected: FAIL until the built image and runtime route are complete.

- [ ] **Step 3: Prove isolation and failure cleanup**

Run reference, private-import, fake-artifact, timeout, crash-at-each-step, oversized-output, wrong-UID, and socket-replay candidates. Assert no candidate view of sim/evidence/request, no sim view of candidate workspace, forced cleanup marked separately, correct retry classification, and no surviving container/socket/temp root.

- [ ] **Step 4: Prove all worlds, artifacts, and determinism**

Run all ten worlds twice with the same seeds; compare canonical scenarios, normalized reports, canonical geometry hashes, and image hashes while excluding timestamps/container IDs. Parse every GLB/STL/PNG/JSON and compare bundle metrics to the immutable scoring snapshot.

- [ ] **Step 5: Run all three repository suites**

Run: `cd instance && python -m pytest -q`

Run: `cd evaluator && python -m pytest -q`

Run: `cd instrument && python -m pytest -q`

Expected: all unit/contract tests PASS; platform-marked Docker tests PASS on native Linux and SKIP with an explicit reason elsewhere.

- [ ] **Step 6: Run the full distributed validator**

Run on native Linux: `cd instrument && python scripts/validate_fibsem_benchmark.py --config configs/fibsem_liftout_v1.yaml`
Expected: exit 0, score 100, strict pass, ten worlds, forty trusted checkpoint bundles, complete provenance, and zero surviving managed resources.

- [ ] **Step 7: Commit integration coverage**

Run in `evaluator`: `git add tests/integration && git commit -m "test: verify FIBSEM dual-container isolation"`

Run in `instrument`: `git add tests/integration scripts/validate_fibsem_benchmark.py && git commit -m "test: validate distributed FIBSEM benchmark"`

### Task 14: Final contract audit and documentation handoff

**Files:**
- Modify: `instance/fibsem_liftout_v1/ACCEPTANCE.md`
- Modify: `instance/README.md`
- Modify: `evaluator/README.md`
- Modify: `instrument/README.md`
- Modify: `instrument/docs/distributed-contract.md`

**Interfaces:**
- Produces operator commands, artifact paths, failure taxonomy, platform requirements, exact commits/digests, and a requirement-to-test acceptance table.

- [ ] **Step 1: Write a failing documentation contract test**

Add assertions that all three READMEs name `fibsem_liftout_v1`, the exact candidate signature, four checkpoints, Linux Docker requirement, artifact directory, and validator command.

- [ ] **Step 2: Run documentation tests and verify RED**

Run: `cd instrument && python -m pytest tests/test_fibsem_contracts.py -q`
Expected: FAIL on missing operator documentation.

- [ ] **Step 3: Document exact build, run, inspect, and retry procedures**

Include no aspirational claims. Link each acceptance criterion to its automated test or report field, distinguish candidate failures from infrastructure retries, document the external OpenFIBSEM pin, and explain that success applies to simulation only, not physical hardware safety.

- [ ] **Step 4: Refresh public hashes and run the completion audit**

Refresh instance hashes after final public documentation changes. Check every design-spec requirement against files, tests, runtime report, rendered artifacts, container evidence, and cleanup evidence. Treat missing native-Linux Docker proof as incomplete rather than inferred success.

- [ ] **Step 5: Run final verification from clean worktrees**

Run `git status --short` in all three repositories and require only intended tracked changes before commits, then run all commands from Task 13 with fresh output. Run `git diff --check` in all repositories.

- [ ] **Step 6: Commit documentation separately in each affected repository**

Run in `instance`: `git add README.md fibsem_liftout_v1 && git commit -m "docs: publish FIBSEM instance acceptance"`

Run in `evaluator`: `git add README.md && git commit -m "docs: explain FIBSEM evaluator evidence"`

Run in `instrument`: `git add README.md docs && git commit -m "docs: explain distributed FIBSEM operation"`

## Final Evidence Checklist

- [ ] `instance`: public schema/client/container/hash/secrecy tests pass and no hidden world or simulator implementation is visible.
- [ ] `evaluator`: scenario, geometry, protocol, journal, backend, exporter, service, scoring, reference, negative, runner, and cleanup tests pass.
- [ ] `instrument`: run contract, source pin, offline runtime, report v3, provenance, artifact publication, and image staging tests pass.
- [ ] Native Linux Docker reference suite passes ten worlds with score 100 and forty valid checkpoint bundles.
- [ ] Four hidden fixed scenarios all pass; at least four seeded are required by the grader and the reference passes all five.
- [ ] Every targeted negative fails its intended state/order/safety/security gate.
- [ ] Repeated same-seed runs have identical canonical scenarios, normalized reports, canonical geometry hashes, and image hashes.
- [ ] Candidate and sim sibling evidence proves UID, network, rootfs, capabilities, mounts, image identity, and cleanup requirements.
- [ ] Final reports contain instrument/instance/evaluator commits, OpenFIBSEM commit/source digest, image identities, journal chains, geometry metrics, artifact hashes, and cleanup outcomes.
- [ ] No managed containers, sockets, temporary roots, active patterns, or unsafe simulator states survive evaluation.
