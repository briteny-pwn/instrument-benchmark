# Instrument Benchmark Orchestrator

This branch contains the generic orchestration layer for the distributed
instrument benchmark. Concrete model-visible instances and private evaluators
live in separate repositories.

The orchestrator accepts independently sourced instance/evaluator pairs. A
runtime profile is selected by the versioned manifests; one instance is never
treated as the base class or dependency template for another. In particular,
`fibsem_liftout_v1` uses OpenFIBSEM and has no runtime dependency on PyVISA.

Configure their absolute roots before running the orchestrator. For local
development, copy the tracked example and edit both values:

```bash
cp .env.example .env
```

```dotenv
INSTANCES_REPO_PATH=/absolute/path/instrument-benchmark-instances
EVALUATOR_REPO_PATH=/absolute/path/instrument-benchmark-evaluator
```

The orchestrator reads only `.env` at this repository root. Values already
exported in the process environment take precedence. Both values are required,
must be absolute, and must name existing directories. A sibling checkout is an
optional convenience, not a resolution rule:

```text
benchmark/
├── instrument/  # briteny-pwn/instrument-benchmark, distributed-model
├── instrument-benchmark-instances/  # assigned to INSTANCES_REPO_PATH
└── instrument-benchmark-evaluator/  # assigned to EVALUATOR_REPO_PATH
```

The repositories communicate through versioned YAML manifests, evaluator
request/report JSON, CLI arguments, and exit statuses. Instrument never imports
evaluator implementation modules on the host.

Every run is bound by `(source_id, instance_id, evaluator_id)`. Instance and
evaluator leaves resolve strictly at `sources/<source_id>/<leaf_id>/`, while
configs and reports are grouped beneath their source ID. Source registries and
schema-v2 leaf manifests must agree before any image build or container start.
Ungrouped legacy config, leaf, report, and artifact paths are invalid; there is
no compatibility fallback, alias, scan, or root-manifest lookup.

Run YAML uses schema version 3 and does not contain repository checkout paths.
A relative `candidate_path` resolves beneath `EVALUATOR_REPO_PATH`, which is
how bundled reference solutions are selected. An absolute `candidate_path`
selects an external submission. Relative traversal or symlink escape outside
the evaluator repository is rejected.

From `instrument/`, run the reference benchmark with:

```bash
PYTHONPATH=src python -m instrument_benchmark.cli \
  configs/pyvisa/pyvisa_dut_validation_v1.yaml
```

The formal v2 configuration is selected independently, so v1 remains
available without gaining v2-only request fields:

```bash
PYTHONPATH=src python -m instrument_benchmark.cli \
  configs/pyvisa/pyvisa_dut_validation_v2.yaml
```

The FIBSEM reference configuration uses the same three-repository contract
plus a separately pinned OpenFIBSEM source input. Candidate code implements
`run_experiment(microscope, scenario, checkpoint, output_dir) -> dict` and
crosses `step_1`, `step_2`, `step_3`, and `step_4`. Run the complete native
Linux Docker acceptance with:

```bash
PYTHONPATH=src \
  "$EVALUATOR_REPO_PATH/scripts/validate_fibsem_benchmark.py" \
  --instrument-root "$PWD" \
  --config "$PWD/configs/openfibsem/fibsem_liftout_v1.yaml"
```

The validator and its container assets are owned by the evaluator repository.
That direct entrypoint requires Python 3.11, python-dotenv, PyYAML, Git, and
Docker on the host. On a native Linux x86_64 Docker host, its portable
entrypoint supplies the Python/Git/Docker client environment in a pinned
driver image:

```bash
"$EVALUATOR_REPO_PATH/scripts/run_fibsem_linux_acceptance.sh" \
  "$PWD/configs/openfibsem/fibsem_liftout_v1.yaml"
```

The driver runs as the invoking UID/GID, adds only the Docker socket group,
and mounts the configured instrument, instance, and evaluator repositories and
`/tmp` at identical absolute paths. This
is necessary because the driver and its sibling evaluator/candidate/simulator
containers share one native daemon. The driver mounts the native host Git
binary, exec path, and resolved dynamic libraries read-only; its image builds
with `--network=none`. The trusted evaluator also builds with `--network=none`,
and the driver, evaluator, candidate, and simulator runs have no network.

On success, the schema-version-5 report is
`reports/openfibsem/fibsem_liftout_v1.json`. Forty read-only checkpoint bundles
are under
`reports/openfibsem/fibsem_liftout_v1.artifacts/{world_id}/{step_id}/`; each contains
`scene.glb`, merged `scene.stl`, SEM/FIB PNG, `checkpoint.json`, and component
STL files. The validator parses every artifact, checks trusted geometry and
image hashes, runs all ten worlds twice, compares deterministic evidence, and
requires zero surviving managed containers.

By default every checkout must be clean so the recorded Git commit IDs fully
identify the run. `--allow-dirty` exists only for local development.

Official evaluation requires a native Linux Docker host. Each report records
the three repository commits plus the Dockerfile hash, locked image digest,
Docker Engine version, per-world security settings, artifact hashes, and
forced-cleanup outcome. Run the complete Linux gate with:

```bash
PYTHONPATH=src python scripts/validate_distributed_benchmark.py
```

The official path builds the trusted evaluator image for every run from only
Git-tracked evaluator inputs. The evaluator repository owns the Dockerfiles,
Python wheels, Linux/amd64 Docker CLI, Docker Buildx plugin and SHA-256
manifests under `$EVALUATOR_REPO_PATH/container`; the image build uses
`--network=none`.
The non-root outer evaluator has no network, a read-only root filesystem and
the host Docker socket. It uses that privileged socket only to create hardened
sibling candidate containers; candidates never receive the socket or evaluator
files. The socket grants daemon-equivalent authority, so the evaluator image is
part of the trusted computing base and must never contain candidate code.

A unique, canonical shared run root is mounted at the identical absolute path
inside the evaluator. World sockets, staged bootstrap files and outputs remain
below it. Outer build/runtime/report errors are retry-eligible infrastructure
failures, while candidate outcomes remain evaluator results. Final
`orchestration.evaluator_container` describes the trusted outer container;
each world's `container_evidence` independently describes its untrusted sibling.
Docker Desktop is intentionally unsupported because its VM can rewrite bind
mount and Docker-socket ownership semantics.

For FIBSEM, the candidate sees only its public scenario, public client,
workspace, output, and read-only socket parent. The sim sibling sees the
hidden world, transport, and evidence directory but no candidate workspace or
outer request. `step_1` retains the source bridge; `step_2` proves needle
connection before source separation; `step_3` proves positioning before target
deposition; `step_4` proves target retention and needle separation/retraction.
Candidate-generated artifacts are for display only; trusted simulator
snapshots are scored. Passing is evidence for simulation, not physical FIB-SEM
safety.

For v2, each world has separate candidate and sim evidence. Candidate code
uses the literal `pyvisa.ResourceManager("@iab")`; both workload siblings have
networking disabled and communicate only through a shared Unix socket whose
parent is read-only in the candidate. The sim sibling owns the hidden world,
PyVISA-sim state, complete event journal, forced-safe cleanup, and no candidate
workspace mount. The outer evaluator passes its label-scoped cleanup owner to
both siblings, and infrastructure failures are retryable only when trusted
errors are recorded.

Run the native-Linux formal v2 gate with:

```bash
IAB_RUN_DOCKER_TESTS=1 PYTHONPATH=src python -m unittest \
  tests.integration.test_v2_dual_container_linux -v
PYTHONPATH=src python scripts/validate_distributed_benchmark.py \
  --config configs/pyvisa/pyvisa_dut_validation_v2.yaml
```

The PyVISA v1 and v2 top-level reports are schema versions 2 and 3,
respectively; the OpenFIBSEM report is schema version 5. All require the
configured `source_id`.
