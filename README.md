# Instrument Benchmark

Instrument Benchmark is the orchestration layer for real-Agent instrument
tests. Its core responsibilities are intentionally small:

1. select a task instance and evaluator by `source_id`;
2. prepare the task workspace and, when required, start the source-owned base
   test environment;
3. launch Claude Code as a host process;
4. inventory the source-defined candidate files, invoke the matching source
   evaluator, and aggregate the result.

Task inputs and task environments live in `instrument-benchmark-tasks`.
Private scoring lives in `instrument-benchmark-evaluator`. Instrument does not
define source-specific candidate names and does not select an evaluator leaf.

## Configuration

Create `.env` from the example and use absolute paths:

```bash
cp .env.example .env
```

```dotenv
INSTANCES_REPO_PATH=/absolute/path/instrument-benchmark-tasks
EVALUATOR_REPO_PATH=/absolute/path/instrument-benchmark-evaluator
INSTRBENCH_AGENT_MODEL=claude-model-name-supported-by-your-gateway
ANTHROPIC_BASE_URL=https://your-anthropic-compatible-gateway.example
ANTHROPIC_AUTH_TOKEN=replace-with-your-token
```

`ANTHROPIC_API_KEY` may replace `ANTHROPIC_AUTH_TOKEN`. Process environment
values override `.env`. Claude Code uses its normal defaults for all settings
that are not listed above.

A run YAML contains only orchestration identity and output location:

```yaml
run_id: fibsem-liftout
source_id: openfibsem
instance_id: fibsem_liftout_v1
report_path: ../../reports/openfibsem/fibsem_liftout_v1.json
```

`source_id` performs the one-level route:

```text
run config
  ├─ tasks/sources/<source_id>/source.yaml
  │    ├─ instance registry
  │    ├─ candidate file contract
  │    └─ optional task environment
  └─ evaluator/sources/<source_id>/source.yaml
       └─ one evaluator entrypoint
```

`instance_id` selects the task input only. There is no `evaluator_id` or
`candidate_path` in run configuration.

## Run

Install Python 3.11+, this package and the evaluator package into the same
environment, Docker for task environments that need it, and Claude Code on the
host:

```bash
python -m pip install -e /absolute/path/instrument-benchmark-evaluator -e .
instrbench run --config configs/openfibsem/fibsem_liftout_v1.yaml
instrbench run --suite suites/example.yaml
```

The suite exposes only `agent: claudecode`. Claude Code runs directly on the
trusted host with a fresh working directory. This is a trusted-environment MVP,
not a strong process sandbox.

For an `agent` candidate source such as PyVISA, candidate files are collected
from the Agent workspace. For a `task_environment` candidate source such as
OpenFIBSEM, Instrument starts the task repository's Docker environment and
passes its Unix-socket path to Claude Code. Successful task checkpoints export
STL, GLB, PNG, and JSON files directly into the candidate handoff.

Instrument inventories every expected file after Agent completion, failure, or
timeout. The evaluator always receives the valid files plus the missing and
invalid path lists, so it may score a safe partial result. Final strict pass is
true only when the source candidate is complete and the evaluator reports a
strict pass.

Run the current source-routing acceptance checks with:

```bash
PYTHONPATH=src pytest -q \
  tests/test_candidate_inventory.py \
  tests/test_evaluator_process.py \
  tests/test_source_routed_run_config.py \
  tests/test_source_routed_pipeline.py \
  tests/test_source_routed_suite.py \
  tests/test_three_repo_source_smoke.py
```
