# Task Goal

Create `solution.py`. Connect to the simulator, identify the ramp chain, enable
the source, process the four documented setpoints in order, read back each
point, compute per-point error, derive the maximum absolute error and alarm
state, leave the source disabled, then close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`. It must
contain these fields:

```text
instrument
setpoints_v
readbacks_v
errors_v
max_abs_error_v
alarm
processed_records
```
