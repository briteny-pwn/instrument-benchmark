# Instrument Benchmark Orchestrator

This branch contains the generic orchestration layer for the distributed
instrument benchmark. Concrete model-visible instances and private evaluators
live in separate sibling repositories.

The orchestrator accepts independently sourced instance/evaluator pairs. A
runtime profile is selected by the versioned manifests; one instance is never
treated as the base class or dependency template for another. In particular,
`fibsem_liftout_v1` uses OpenFIBSEM and has no runtime dependency on PyVISA.

Expected checkout layout:

```text
benchmark/
├── instrument/  # briteny-pwn/instrument-benchmark, distributed-model
├── instance/    # briteny-pwn/instrument-benchmark-instances, main
└── evaluator/   # briteny-pwn/instrument-benchmark-evaluator, main
```

The repositories communicate through versioned YAML manifests, evaluator
request/report JSON, CLI arguments, and exit statuses. Instrument never imports
evaluator implementation modules on the host.

From `instrument/`, run the reference benchmark with:

```bash
PYTHONPATH=src python -m instrument_benchmark.cli \
  configs/pyvisa_dut_validation_v1.yaml
```

The formal v2 configuration is selected independently, so v1 remains
available without gaining v2-only request fields:

```bash
PYTHONPATH=src python -m instrument_benchmark.cli \
  configs/pyvisa_dut_validation_v2.yaml
```

The FIBSEM reference configuration uses the same three-repository contract
plus a separately pinned OpenFIBSEM source input. Candidate code implements
`run_experiment(microscope, scenario, checkpoint, output_dir) -> dict` and
crosses `step_1`, `step_2`, `step_3`, and `step_4`. Run the complete native
Linux Docker acceptance with:

```bash
python scripts/validate_fibsem_benchmark.py --config configs/fibsem_liftout_v1.yaml
```

That direct entrypoint requires Python 3.11, PyYAML, Git, and Docker on the
host. On a native Linux x86_64 Docker host, the portable entrypoint supplies
the Python/Git/Docker client environment in a pinned driver image:

```bash
scripts/run_fibsem_linux_acceptance.sh configs/fibsem_liftout_v1.yaml
```

The driver runs as the invoking UID/GID, adds only the Docker socket group,
and mounts the checkout parent and `/tmp` at an identical absolute path. This
is necessary because the driver and its sibling evaluator/candidate/simulator
containers share one native daemon. Network access is used only while adding
Git to the driver image; the trusted evaluator image still builds with
`--network=none`, and all evaluator, candidate, and simulator runs have no
network.

On success, the schema-version-3 report is
`reports/fibsem_liftout_v1.json`. Forty read-only checkpoint bundles are under
`reports/fibsem_liftout_v1.artifacts/<world>/<step>/`; each contains
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
Git-tracked evaluator inputs. Python wheels and the Linux/amd64 Docker CLI are
vendored with SHA-256 manifests, and the image build uses `--network=none`.
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
  --config configs/pyvisa_dut_validation_v2.yaml
```
