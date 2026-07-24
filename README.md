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
evaluator implementation modules.

From `instrument/`, run the reference benchmark with:

```bash
PYTHONPATH=src python -m instrument_benchmark.cli \
  configs/pyvisa_dut_validation_v1.yaml
```

By default every checkout must be clean so the recorded Git commit IDs fully
identify the run. `--allow-dirty` exists only for local development.

