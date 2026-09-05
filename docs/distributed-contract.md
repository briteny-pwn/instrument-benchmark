# Source-routed distributed contract

The three repositories meet at `source_id`.

- Instrument run YAML selects `source_id` and `instance_id`.
- The task source manifest registers instances and defines one candidate file
  contract for the whole source.
- The evaluator source manifest defines one evaluator entrypoint for the whole
  source.
- `instance_id` selects task input; it does not select an evaluator.

Repository locations come only from the absolute `INSTANCES_REPO_PATH` and
`EVALUATOR_REPO_PATH` environment variables (or the Instrument root `.env`).
They are intentionally absent from portable run YAML.

Instrument invokes the evaluator repository through:

```text
python -m instrument_benchmark_evaluator.cli run
  --request <absolute JSON path>
  --report <absolute JSON path>
```

The request contains `run_id`, `source_id`, `instance_id`, the resolved task
instance directory, candidate handoff root, and three sorted inventories:
valid files, missing files, and invalid files. It contains neither
`evaluator_id` nor a special single-file `candidate_path`.

Candidate file paths are always source-defined relative file paths. Directory
candidates are unsupported. Instrument rejects symlinks, non-regular files,
and paths escaping the handoff root.

For `producer: agent`, the handoff root is the prepared Agent workspace. For
`producer: task_environment`, Instrument builds and starts the task source's
base environment, mounts a dedicated candidate handoff and evidence directory,
and gives Claude Code only the declared socket environment variable. The task
environment exports checkpoint artifacts directly into the handoff.

Claude Code runs as a host process using the prepared workspace as `cwd`.
Model, base URL, and authentication are supplied by environment variables;
other Claude Code behavior uses defaults. Agent failure does not suppress task
environment finalization, inventory, or partial evaluation.

The evaluator returns the run/source/instance identity, score, and
`evaluator_strict_pass`. Instrument preserves evaluator scoring and adds Agent,
candidate, and routing information. The final `strict_pass` is:

```text
candidate_complete AND evaluator_strict_pass
```
