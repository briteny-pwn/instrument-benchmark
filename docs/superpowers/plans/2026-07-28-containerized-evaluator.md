# Containerized Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the complete trusted evaluator in a hardened outer Docker container which creates one existing hardened sibling candidate container per world.

**Architecture:** The orchestrator builds an evaluator image offline from the validated evaluator checkout and an orchestrator-owned wheelhouse, then launches it with a same-path shared run root and the host Docker socket. The evaluator keeps all hidden state and scoring inside the outer container while its existing `DockerCandidateBackend` creates isolated sibling candidates through the host daemon.

**Tech Stack:** Python 3.11, Docker Engine/BuildKit on Ubuntu 24.04 (`linux/amd64`), PyYAML 6.0.3, PyVISA 1.16.2, PyVISA-sim 0.7.1, unittest.

## Global Constraints

- Start from the existing `feature/docker-candidate-runner` worktrees in the orchestrator, evaluator and instance repositories.
- Official execution targets native Linux Docker Engine and `linux/amd64`; do not claim Docker Desktop support.
- The outer evaluator is trusted and may access `/var/run/docker.sock`; candidates must never receive that socket.
- Build the evaluator image for every official run with `docker build --network=none` and an offline, hash-verified wheelhouse.
- Run the outer evaluator with network `none`, read-only root, non-root UID/GID, all capabilities dropped and `no-new-privileges`.
- Mount a unique shared run root at the same absolute host/container path; every sibling bind source must live below it or be an explicitly validated same-path instance/candidate mount.
- Preserve all current candidate-container restrictions, scoring semantics, gates and candidate status classifications.
- Classify outer build/runtime/report failures as infrastructure failures with retry eligibility, never as candidate failures.
- Keep the host evaluator invocation only as a unit-test fixture; official orchestration has no host-backend option.

---

### Task 1: Add the evaluator shared-run-root contract

**Repository:** `/Users/britenyyyang/benchmark/.worktrees/evaluator-docker-runner`

**Files:**
- Modify: `instrument_benchmark_evaluator/contracts.py`
- Modify: `instrument_benchmark_evaluator/cli.py`
- Modify: `instrument_benchmark_evaluator/run.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_run_backend.py`

**Interfaces:**
- Produces `EvaluatorRequest.shared_run_root: Path` and `RunSettings.shared_run_root: Path | None`.
- `run_world()` creates its per-world directory with `TemporaryDirectory(prefix="iab-experiment-", dir=benchmark.shared_run_root)` when supplied.
- The host test backend passes `shared_run_root=None`; official outer-container requests must pass an existing absolute directory.

- [ ] **Step 1: Write failing request-contract tests**

Extend `valid_request()` with `shared_run_root`, assert it resolves to an absolute directory, and add rejection tests for a relative path, missing directory and shared root equal to the filesystem root.

```python
shared = directory / "shared-runs"
shared.mkdir()
request["shared_run_root"] = str(shared)
self.assertEqual(load_evaluator_request(path).shared_run_root, shared.resolve())
```

- [ ] **Step 2: Run the focused tests and verify failure**

```bash
cd /Users/britenyyyang/benchmark/.worktrees/evaluator-docker-runner
python -m unittest tests.test_cli tests.test_run_backend -v
```

Expected: failures report the unexpected/missing `shared_run_root` field.

- [ ] **Step 3: Implement the contract and lifecycle**

Add the field to the exact protocol-v1 key set, validate it with `_absolute_existing_directory`, reject `/`, and propagate it through CLI `RunSettings`. Replace the unconditional temporary directory in `run_world()` with:

```python
temporary = tempfile.TemporaryDirectory(
    prefix="iab-experiment-",
    dir=benchmark.shared_run_root,
)
with temporary as directory:
    root = Path(directory)
```

Keep all workspace, gateway and candidate output paths below `root`.

- [ ] **Step 4: Add a backend path-observation test**

Use a fake backend that records `workspace` and `endpoint`; assert both are descendants of the supplied shared root and that the directory is removed after `run_world()` returns.

- [ ] **Step 5: Run evaluator unit and semantic suites**

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s evaluators/pyvisa_dut_validation_v1/tests -v
git diff --check
```

Expected: all tests pass and existing world scoring is unchanged.

- [ ] **Step 6: Commit**

```bash
git add instrument_benchmark_evaluator/contracts.py \
  instrument_benchmark_evaluator/cli.py \
  instrument_benchmark_evaluator/run.py tests/test_cli.py tests/test_run_backend.py
git commit -m "feat: support host-visible evaluator run roots"
```

### Task 2: Add an offline evaluator image build

**Repository:** `/Users/britenyyyang/benchmark/.worktrees/instrument-docker-runner`

**Files:**
- Create: `container/evaluator.Dockerfile`
- Create: `container/evaluator-requirements.lock`
- Create: `container/wheelhouse/manifest.json`
- Create: `container/wheelhouse/*.whl`
- Create: `scripts/vendor_evaluator_wheels.py`
- Create: `src/instrument_benchmark/evaluator_image.py`
- Create: `tests/test_evaluator_image.py`

**Interfaces:**
- Produces `EvaluatorBuildContext`, `EvaluatorImageEvidence`, and `EvaluatorImageBuilder.build(evaluator_checkout: Path, *, run_id: str) -> EvaluatorImageEvidence`.
- `EvaluatorImageEvidence` contains `reference`, `image_id`, `repo_digest`, `dockerfile_sha256`, `build_manifest_sha256`, `evaluator_commit`, `platform`, and `user`.

- [ ] **Step 1: Write failing build-context tests**

Tests must create a miniature evaluator checkout and assert staging includes tracked evaluator files but excludes `.git`, `__pycache__`, `.venv`, reports, test artifacts and candidate output. Mutating a staged input or wheel must fail manifest verification.

```python
context = stage_evaluator_build_context(evaluator, assets, destination)
self.assertTrue((context.root / "evaluator" / "pyproject.toml").is_file())
self.assertFalse((context.root / "evaluator" / ".git").exists())
verify_build_manifest(context.root, context.manifest)
```

- [ ] **Step 2: Run the test and verify missing implementation**

```bash
python -m unittest tests.test_evaluator_image -v
```

Expected: import failure for `instrument_benchmark.evaluator_image`.

- [ ] **Step 3: Vendor the exact CPython 3.11 Linux wheels**

Lock `PyYAML==6.0.3`, `PyVISA==1.16.2`, `PyVISA-sim==0.7.1`, `setuptools==80.9.0` and their transitive dependencies with SHA-256 hashes. The vendor script must download only `manylinux_2_17_x86_64` or universal wheels, reject sdists, regenerate `manifest.json`, and fail if filenames, sizes or digests differ. Commit the wheel files because official builds are network-disabled.

- [ ] **Step 4: Create the evaluator Dockerfile**

Use a digest-pinned `python:3.11-slim` base, create UID/GID `11001:11001`, install only from `/build/wheels`, then install the staged evaluator package without build isolation or dependencies:

```dockerfile
RUN python -m pip install --no-index --require-hashes \
      --find-links=/build/wheels -r /build/evaluator-requirements.lock \
 && python -m pip install --no-index --no-deps --no-build-isolation /build/evaluator
USER 11001:11001
ENTRYPOINT ["python", "-m", "instrument_benchmark_evaluator.cli"]
```

- [ ] **Step 5: Implement build, inspect and evidence validation**

Stage the context under a temporary directory, hash every regular input, run Docker commands with argument vectors and `shell=False`, set `SOURCE_DATE_EPOCH` from the evaluator commit timestamp, build with `--network=none --platform=linux/amd64`, and inspect the result. Reject a non-Linux platform, missing digest/ID, or image user other than `11001:11001`.

- [ ] **Step 6: Add Docker integration coverage**

Under `IAB_RUN_DOCKER_TESTS=1`, build the real image, inspect it, and run `python -c` inside it to import `pyvisa`, `pyvisa_sim`, evaluator worlds and scoring. Assert no network was used by the Dockerfile and no `.git` path exists in the image.

- [ ] **Step 7: Run tests and commit**

```bash
python -m unittest tests.test_evaluator_image -v
IAB_RUN_DOCKER_TESTS=1 python -m unittest tests.integration.test_evaluator_image_linux -v
git diff --check
git add container scripts/vendor_evaluator_wheels.py \
  src/instrument_benchmark/evaluator_image.py tests/test_evaluator_image.py \
  tests/integration/test_evaluator_image_linux.py
git commit -m "feat: build evaluator image offline"
```

### Task 3: Implement the hardened outer evaluator runner

**Repository:** `/Users/britenyyyang/benchmark/.worktrees/instrument-docker-runner`

**Files:**
- Create: `src/instrument_benchmark/evaluator_runtime.py`
- Create: `tests/test_evaluator_runtime.py`
- Create: `tests/fixtures/fake_evaluator_report.json`

**Interfaces:**
- Produces `EvaluatorContainerEvidence`, `EvaluatorContainerResult`, and `EvaluatorContainerRunner.run(...) -> EvaluatorContainerResult`.
- Consumes `EvaluatorImageEvidence`, request/report paths, same-path instance/candidate/shared-root paths, total timeout, independent stdout/stderr limits and run-owner labels.

- [ ] **Step 1: Write exact Docker-argument tests**

Use a recording fake Docker executor and assert `docker create` includes:

```text
--network none --read-only --user 11001:11001
--group-add <docker-socket-gid>
--cap-drop ALL --security-opt no-new-privileges
--pids-limit 256 --memory 2g --memory-swap 2g --cpus 2.0
--tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m
```

Assert only the shared root, explicit same-path instance/candidate mounts and `/var/run/docker.sock` are present. Reject non-absolute paths, path aliases, shared root `/`, report outside the shared root, missing/non-socket Docker socket, and a candidate/instance path not covered by an allowed mount.

- [ ] **Step 2: Run tests and verify missing runner**

```bash
python -m unittest tests.test_evaluator_runtime -v
```

Expected: import failure for `instrument_benchmark.evaluator_runtime`.

- [ ] **Step 3: Implement bounded create/start/wait/inspect/remove**

Generate a random outer container name and labels `iab.managed=true`, `iab.kind=evaluator`, `iab.owner=<owner>`, and `iab.run_id=<run_id>`. Stream stdout and stderr independently, kill on timeout or limit, always inspect before removal, and always remove in `finally`. Never invoke a shell.

- [ ] **Step 4: Implement safe report collection**

Accept only the declared report path below the shared root. Open with no symlink following, require a regular file, reject hard links, enforce a 16 MiB maximum, parse one JSON object, and hash bytes before returning it. A missing, malformed, unsafe or oversized report is an infrastructure failure.

- [ ] **Step 5: Implement outer evidence and classification**

Normalize inspect fields for image ID/digest, container ID, timestamps, exit/OOM, network, rootfs, user/groups, capabilities, security options, limits and mounts. Record stream sizes/hashes and cleanup success. Map timeout, OOM, create/start/inspect/report/daemon failures to `EvaluatorInfrastructureError(retry_eligible=True)`.

- [ ] **Step 6: Run tests and commit**

```bash
python -m unittest tests.test_evaluator_runtime -v
git diff --check
git add src/instrument_benchmark/evaluator_runtime.py \
  tests/test_evaluator_runtime.py tests/fixtures/fake_evaluator_report.json
git commit -m "feat: run evaluator in hardened container"
```

### Task 4: Switch official orchestration to the evaluator container

**Repository:** `/Users/britenyyyang/benchmark/.worktrees/instrument-docker-runner`

**Files:**
- Modify: `src/instrument_benchmark/orchestrator.py`
- Modify: `src/instrument_benchmark/contracts.py`
- Modify: `schemas/run.schema.json`
- Modify: `tests/test_orchestrator.py`
- Modify: `configs/pyvisa_dut_validation_v1.yaml`

**Interfaces:**
- `run_benchmark()` constructs `EvaluatorImageBuilder`, then `EvaluatorContainerRunner`; it no longer calls host Python in the official path.
- The request adds `shared_run_root` while retaining protocol version 1 and current candidate-container fields.
- Final `orchestration.evaluator_container` is the serialized outer evidence; per-world `container_evidence` remains sibling candidate evidence.

- [ ] **Step 1: Replace the fake host-evaluator test with a fake image/runner test**

Inject builders/runners through optional keyword-only factories. Assert request paths are absolute, `shared_run_root` exists during runner invocation, report validation occurs, and the final report contains distinct outer and per-world container evidence.

- [ ] **Step 2: Run the focused test and verify it fails against host invocation**

```bash
python -m unittest tests.test_orchestrator -v
```

Expected: the new runner factory is unsupported and the old host `_invoke_evaluator` path is observed.

- [ ] **Step 3: Implement the official flow**

Within one host `TemporaryDirectory`, create the shared root, request and report. Build the image, invoke the outer runner with timeout:

```python
suite_timeout = config.timeout_seconds * (
    len(evaluator_manifest["fixed_worlds"]) + config.repeated_worlds
) + 60
```

Validate the evaluator report before leaving the shared root, then add provenance and outer evidence. Remove `_invoke_evaluator()` from production code; place any needed host CLI helper under tests only.

- [ ] **Step 4: Extend report validation**

Require `orchestration.evaluator_container` after orchestration and validate network `none`, read-only root, user `11001:11001`, all capabilities dropped, `no-new-privileges`, Docker socket mount only for the outer container, image digest, build manifest digest and cleanup success. Preserve existing per-world candidate evidence checks.

- [ ] **Step 5: Run orchestrator tests and commit**

```bash
python -m unittest discover -s tests -v
git diff --check
git add src/instrument_benchmark/orchestrator.py \
  src/instrument_benchmark/contracts.py schemas/run.schema.json \
  tests/test_orchestrator.py configs/pyvisa_dut_validation_v1.yaml
git commit -m "feat: orchestrate containerized evaluator"
```

### Task 5: Prove the two-layer isolation and semantic parity

**Repositories:** orchestrator and evaluator feature worktrees

**Files:**
- Create: orchestrator `tests/integration/test_containerized_evaluator_linux.py`
- Modify: orchestrator `scripts/validate_distributed_benchmark.py`
- Modify: evaluator `tests/fixtures/candidates/probe_isolation.py`
- Modify: evaluator `tests/integration/test_docker_full_suite_linux.py`

**Interfaces:**
- Official integration runs use only `run_benchmark()` and therefore the outer evaluator container.
- Semantic parity compares reports after removing timestamps, IDs, hashes, provenance, outer evidence and evidence sequence numbers.

- [ ] **Step 1: Add a failing outer-isolation integration test**

Assert the outer container has no usable network, read-only root, UID 11001, socket supplementary group, no capabilities and `no-new-privileges`; assert it can create a sibling candidate and write a report.

- [ ] **Step 2: Extend the candidate probe**

Inside the sibling candidate, assert failure to read `/var/run/docker.sock`, evaluator package paths, hidden worlds, simulator YAML, oracle, journal, host Git metadata and the outer request/report. Preserve successful access to exactly its gateway socket and output directory.

- [ ] **Step 3: Add success, failure and cleanup cases**

Cover reference full suite, candidate timeout, candidate OOM, outer timeout, outer OOM, malformed report and Docker daemon failure. After every case assert no container with the run-owner label and no run-scoped socket/directory remains.

- [ ] **Step 4: Add semantic parity comparison**

Run the current Docker-candidate baseline once using the test-only host evaluator and the new official outer path once with the same seeds. Compare normalized world scores, dimensions, gates, constraints, device evidence, experiment completion and decisions.

- [ ] **Step 5: Run Linux integration tests**

```bash
IAB_RUN_DOCKER_TESTS=1 python -m unittest \
  tests.integration.test_containerized_evaluator_linux -v
cd /Users/britenyyyang/benchmark/.worktrees/evaluator-docker-runner
IAB_RUN_DOCKER_TESTS=1 python -m unittest \
  tests.integration.test_docker_full_suite_linux -v
```

Expected: reference strict pass over 9 fixed + 10 repeated worlds, all isolation probes pass, and semantic projections are equal.

- [ ] **Step 6: Commit both repository changes**

Commit evaluator probe/parity fixtures first, then orchestrator integration and validation changes with messages `test: probe nested candidate isolation` and `test: validate containerized evaluator`.

### Task 6: Update official CI, documentation and final three-repository validation

**Repositories:** orchestrator, evaluator and instance feature worktrees

**Files:**
- Modify: orchestrator `.github/workflows/distributed-docker.yml`
- Modify: orchestrator `README.md`
- Modify: evaluator `README.md`
- Verify only: instance container contract and tests

**Interfaces:**
- Ubuntu 24.04 CI runs the outer evaluator container path and uploads final report, evaluator build manifest, Docker inspect evidence and stale-resource listing.

- [ ] **Step 1: Change CI to avoid installing evaluator on the host**

Install only the orchestrator package. Run instance unit tests with its standard Python environment, then run `scripts/validate_distributed_benchmark.py`; the evaluator package must be consumed only through the built image. Keep `docker info` as an explicit prerequisite.

- [ ] **Step 2: Harden CI cleanup evidence**

Always capture `docker ps -a`, `docker image inspect`, the final report and build manifest. Remove only resources labeled with the exact CI owner/run ID. Fail validation when labeled evaluator or candidate containers remain.

- [ ] **Step 3: Update documentation**

Document the two-container trust boundary, Docker socket risk, offline build, Linux-only support, same-path shared root, outer infrastructure failure behavior and the distinction between `evaluator_container` and per-world candidate `container_evidence`.

- [ ] **Step 4: Run all repository tests**

```bash
cd /Users/britenyyyang/benchmark/.worktrees/instance-docker-runner
python -m unittest discover -s tests -v

cd /Users/britenyyyang/benchmark/.worktrees/evaluator-docker-runner
python -m unittest discover -s tests -v
python -m unittest discover -s evaluators/pyvisa_dut_validation_v1/tests -v

cd /Users/britenyyyang/benchmark/.worktrees/instrument-docker-runner
python -m unittest discover -s tests -v
IAB_RUN_DOCKER_TESTS=1 python scripts/validate_distributed_benchmark.py
git diff --check
```

Expected: all unit/integration suites pass, validation reports 19 worlds, score 100, strict pass, semantic reproducibility true, and no stale run-owned resources.

- [ ] **Step 5: Request code review and address only verified findings**

Use `superpowers:requesting-code-review` across the three branch tips, rerun the focused tests for every accepted finding, then repeat the full validation command.

- [ ] **Step 6: Commit documentation and CI**

Commit orchestrator CI/docs and evaluator docs in their respective repositories. Do not modify the instance branch unless its unchanged regression tests expose a real contract defect.

