# Evaluations

Evaluation is split into a reusable framework and per-instance specifications.

## Common Framework

`evaluations/common/` contains the shared runner, PyVISA trace wrapper, and
observation-first grader.

The common grader:

- runs candidate `run_experiment(output_path=...)` against pyvisa-sim;
- records generic PyVISA access evidence;
- scores the returned or written result against `spec.json`;
- treats trace evidence as supporting access information rather than the main
  source of truth.

Default score weights are:

```text
pyvisa_sim_execution: 0.2
observation:          0.5
access:               0.2
cleanup:              0.1
```

Instances may override these weights in `spec.json`, but the intended default
is to judge whether the requested experiment was completed and observed
correctly.

## Per-Instance Files

Each `evaluations/{instance_id}/` directory provides:

- `spec.json`: hidden scoring specification and expected observations;
- `pyvisa_sim/*.yaml`: pyvisa-sim instrument definition;
- `grader.py`: thin compatibility entry point for the common grader;
- `reference_solution/experiment.py`: reference implementation for validation.

`spec.json` is the main hidden contract. It describes:

- `simulator`: pyvisa-sim YAML used for the run;
- `expected_result`: observed result fields and tolerances;
- `access`: generic PyVISA evidence such as expected resources, communication
  settings, resource discovery, and value-transfer helpers.

The usual command remains:

```bash
cd evaluations/{instance_id}
../../.venv/bin/python grader.py path/to/solution.py
```

