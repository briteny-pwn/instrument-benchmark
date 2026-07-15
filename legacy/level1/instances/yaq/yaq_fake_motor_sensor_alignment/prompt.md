# Task Goal

Create `solution.py`. Connect to the simulator, discover and identify the motor
and sensor resources, scan the documented motor positions, wait for each motion
to complete, read the final motor position and alignment signal at each point,
calculate the maximum position error and the position with maximum signal, then
close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`. It must
contain these fields:

```text
motor
sensor
positions_mm
readbacks_mm
sensor_channel
sensor_values
sample_count
max_abs_error_mm
best_position_mm
completed
```
