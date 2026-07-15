# PyVISA-Sourced Evaluations

These evaluations use pyvisa-sim as a hidden simulator backend, but candidates
never interact with PyVISA directly.

Per-instance graders start `evaluations/common/raw_sim_gateway.py`, expose a
local JSON-line TCP service through `INSTRUMENT_SIM_HOST` and
`INSTRUMENT_SIM_PORT`, and score the candidate's raw socket interaction.

Each `evaluations/pyvisa/{instance_id}/` directory provides:

- `spec.json`: expected observation and raw protocol evidence.
- `grader.py`: entry point into the common raw grader.
- `reference_solution/`: standard-library-only reference implementation.
- `pyvisa_sim/*.yaml`: hidden pyvisa-sim instrument definition.

Run:

```bash
cd evaluations/pyvisa/{instance_id}
../../../.venv/bin/python grader.py ../../../experience/pyvisa/{instance_id}/solution.py
```
