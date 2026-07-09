# Evaluation: PyVISA DC Power Supply Basic Access

This directory is not part of the model-visible instance input.

It contains hidden or external evaluation assets for:

```text
../instances/pyvisa_dc_power_supply_basic/
```

Files:

- `fake_pyvisa.py`: stricter trace-recording fake PyVISA backend;
- `simulation/fake_pyvisa.py`: runtime simulator copy, not visible to the model;
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

Run:

```bash
python grader.py reference_solution/experiment.py
```
