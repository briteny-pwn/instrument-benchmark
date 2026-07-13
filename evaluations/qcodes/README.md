# QCoDeS-Sourced Evaluations

These evaluations are inspired by QCoDeS-style station and driver tasks, but
the candidate is evaluated through the same raw socket protocol used by every
other instance.

No QCoDeS runtime, qcodes_contrib_drivers module, or lab driver module is
injected for candidate code. Forbidden imports are rejected before execution.

Each `evaluations/qcodes/{instance_id}/` directory provides:

- `spec.json`: expected observation and raw protocol evidence.
- `grader.py`: entry point into the common raw grader.
- `reference_solution/`: standard-library-only reference implementation.
- `pyvisa_sim/*.yaml`: hidden simulator definition when pyvisa-sim backs the
  raw gateway.

Run:

```bash
cd evaluations/qcodes/{instance_id}
../../../.venv/bin/python grader.py ../../../experience/qcodes/{instance_id}/solution.py
```
