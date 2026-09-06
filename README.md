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

### Progress and errors

Both commands show progress automatically. Interactive terminals use tqdm for
the suite's finished-task count, the current run's eight workflow stages, and
source-defined candidate file counts. Stages cover input validation, workspace
preparation, task environment startup, Agent execution, environment cleanup,
candidate inventory, evaluation, and report persistence. Operations and elapsed
time remain visible during long-running stages; Agent tool names and counts
come from actual stream events. Agent text, tool arguments, and internal
reasoning are not echoed by the progress renderer.

Candidate files observed while the Agent runs are explicitly provisional;
the final inventory is collected after task environment cleanup. Neither a
file's presence nor a finished stage implies a passing score. Evaluator
internals have no progress-event contract, so the display shows process status
and elapsed time, not an invented scoring percentage.

Progress and diagnostics go to **stderr**; **stdout remains the final JSON**.
Pipes and non-interactive terminals receive line-based events instead of cursor
control sequences. Each attempt saves `progress.jsonl` alongside the existing
Agent, environment, and evaluator logs. Child output is flushed as logical
records arrive; a record exceeding 1 MiB is replaced with an omission marker to
bound memory without exposing a partially redacted record. Configured secrets
and common credential forms are redacted from emitted process logs and
diagnostics; terminal control characters are removed.

An error block contains exactly four fields:

```text
任务：source/instance (run_id=...)
步骤：stage → operation
错误：exception type, message, and exit status when available
日志：absolute paths to existing logs, or 未保存
```

There are no troubleshooting suggestions or prescribed user actions. Primary
failures remain visible if cleanup also fails. Reports include a `diagnostics`
list without changing the evaluator request contract or scoring rules. Suite
results are checkpointed after each run; Ctrl+C stops the suite, performs
bounded child-process cleanup, and attempts to save the partial suite report.
The CLI returns 130 for interruption, 2 for invalid input contracts, and 3 for
infrastructure failures. A completed evaluation can still have a failing
score or incomplete candidate while the CLI exits normally.

For an `agent` candidate source such as PyVISA, candidate files are collected
from the Agent workspace. For a `task_environment` candidate source such as
OpenFIBSEM, Instrument starts the task repository's Docker environment and
passes its Unix-socket path to Claude Code. Successful task checkpoints export
STL, GLB, PNG, and JSON files directly into the candidate handoff.

Instrument inventories every expected file after Agent completion, failure, or
timeout. With a valid task environment, the evaluator receives the valid files
plus the missing and invalid path lists, so it may score a partial result. Final strict pass is
true only when the source candidate is complete and the evaluator reports a
strict pass.

Task containers run with the host's numeric, non-root UID/GID. Instrument owns
private candidate/evidence mounts and an independently allocated short socket
directory; long report paths do not lengthen the Unix socket address. Before
starting the Agent, it verifies container write/rename/delete probes, host
readback, run identity, and an actual socket connection. No experiment operation
is performed by this readiness check. Native Linux is required for the full
host-to-container Unix socket path.

Tasks publish incremental `task-evidence/environment-events.jsonl` and an atomic
`task-evidence/environment-result.json`. They classify their own domain errors
and retain original exception chains in `environment-errors.log`. Instrument
monitors fatal events even while the Agent is silent and stops its process group
when the environment fails. A missing/invalid terminal result, unexpected
container exit, or infrastructure failure skips evaluation: `score: null`,
`evaluated: false`, `strict_pass: null`. These runs are counted as infrastructure
failures and excluded from `mean_score`; the mean is `null` if nothing was scored.
An ordinary `candidate_incomplete` or `candidate_failure` can still be evaluated.
Candidate files and evidence remain available after container/socket cleanup.
This is a trusted-host MVP, not a security boundary against hostile Agents.

Run the current source-routing acceptance checks with:

```bash
PYTHONPATH=src pytest -q \
  tests/test_progress.py \
  tests/test_progress_pipeline.py \
  tests/test_progress_processes.py \
  tests/test_progress_cli.py \
  tests/test_progress_review_fixes.py \
  tests/test_streaming_process.py \
  tests/test_candidate_inventory.py \
  tests/test_evaluator_process.py \
  tests/test_source_routed_run_config.py \
  tests/test_source_routed_pipeline.py \
  tests/test_source_routed_suite.py \
  tests/test_three_repo_source_smoke.py
```
