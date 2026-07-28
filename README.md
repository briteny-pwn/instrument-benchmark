# Instrument Benchmark Orchestrator

This branch contains the generic orchestration layer for the distributed
instrument benchmark. Concrete model-visible instances and private evaluators
live in separate sibling repositories.

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
