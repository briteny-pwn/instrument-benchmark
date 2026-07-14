# Task Goal

Create `solution.py`. Connect to the simulator, identify the serial bus
controller, check the documented pressure and pump interlock conditions, start
pump P1 with BUSY retry handling, verify its running state, read final pressure
and speed, then close all resources.

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
pump
interlock
start_attempts
running
initial_pressure_torr
final_pressure_torr
speed_rpm
```
