# Evaluation: PyVISA DMM ASCII Average

This directory is not part of the model-visible instance input.

It contains hidden evaluation assets for:

```text
../../instances/pyvisa_dmm_ascii_average/
```

Files:

- `pyvisa_sim/mockdmm2000.yaml`: hidden pyvisa-sim instrument definition;
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

Run:

```bash
../../.venv/bin/python grader.py reference_solution/experiment.py
```

