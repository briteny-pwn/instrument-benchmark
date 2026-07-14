# Task Goal

Create `solution.py`. Connect to the simulator, identify the temperature
device, set its alarm limit to 30.0 C, read the documented temperature
sequence, determine the final state, status, and alarm decision, then close all
resources.

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
alarm_limit_c
temperature_history_c
final_state
status
alarm
```
