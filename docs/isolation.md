# Isolated Benchmark Execution

The official runner treats both the model agent and generated `solution.py` as
untrusted code. A current working directory or `.gitignore` rule is not a
security boundary.

## Trust Boundaries

The host orchestrator owns task selection, hidden specs, run manifests, image
digests, traces, final simulator state, and scoring. It starts separate
containers for the authoring agent, model API proxy, simulator, and hidden
solution execution.

The authoring container receives exactly:

```text
/workspace/prompt.md
/workspace/environment/instrument_manual.md
/workspace/environment/simulator_protocol.md
```

It has a read-only root filesystem, writable `/workspace`, tmpfs `/tmp`, a
non-root user, dropped Linux capabilities, resource limits, no Docker socket,
no host home, no repository mount, and no public network route.

The API proxy has a second egress network and forwards only the configured
model message endpoints. The upstream credential exists only in that proxy;
the agent receives a local URL and placeholder key. The simulator shares only
the internal network.

Hidden evaluation destroys the authoring environment, extracts only
`solution.py`, and executes it once per hidden scenario in fresh containers.
Only the simulator container can write the trace/state control volume.

## Run Artifacts

Each ignored `runs/{run_id}` directory contains:

```text
manifest.json
workspace/
candidate/solution.py
agent/events.jsonl
agent/summary.json
evaluation/report.json
hashes.json
```

The manifest records the task, model, repository revision, timestamps, and
container image digests. `hashes.json` binds the visible inputs, extracted
solution, and final report. Neither file is exposed inside the candidate
container.

Historical files under `experience/` predate this boundary. Because those
runs could inspect the repository and hidden evaluations, they are retained
only as contaminated development records.

## Verification

Run content and container checks before collecting formal results:

```bash
.venv/bin/python -m benchmark_harness lint-instance
.venv/bin/python -m benchmark_harness security-check --instance SOURCE/INSTANCE
```

The security probe verifies the workspace allowlist, absence of repository and
credential paths, absence of the Docker socket, and failure of direct public
network access. A formal report is valid only when these checks pass for the
same image configuration used by the run.
