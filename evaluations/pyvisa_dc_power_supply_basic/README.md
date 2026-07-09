# Evaluation: PyVISA DC Power Supply Basic Access

This directory is not part of the model-visible instance input.

It contains hidden or external evaluation assets for:

```text
../instances/pyvisa_dc_power_supply_basic/
```

Files:

- `pyvisa_sim/mockdp100.yaml`: hidden pyvisa-sim instrument definition;
- `trace_pyvisa.py`: wrapper that routes `pyvisa.ResourceManager()` to pyvisa-sim and records access traces;
- `gold_behavior.json`: expected semantic behavior;
- `grader.py`: automatic grader draft;
- `reference_solution/experiment.py`: one valid implementation used to test the grader.

Expected candidate submission:

```text
solution.py
```

The candidate module must expose:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

The grader, not the model-facing instance, is responsible for running this
entry point, selecting the output path, inspecting any generated file, and
checking hidden instrument traces.

The evaluation uses pyvisa-sim for simulated communication. The trace wrapper
records connection, configuration, command/query calls, semantic actions, and
cleanup. The pyvisa-sim execution result is one scoring component rather than
the entire score.

Run:

```bash
../../.venv/bin/python grader.py reference_solution/experiment.py
```
