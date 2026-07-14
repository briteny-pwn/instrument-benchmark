# Task Goal

Create `solution.py`. Connect to the simulator, identify and enable the motor,
set its velocity to 2.0 mm/s, move through the documented scan positions, wait
for each move to finish, read each final position, calculate the maximum
absolute position error, stop the motor, then close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`. It must
contain these fields:

```text
device
class
velocity_mm_s
target_positions_mm
readback_positions_mm
max_abs_error_mm
final_state
stopped
```
