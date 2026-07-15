# Task Goal

Create `solution.py`. Connect to the simulator, identify the temperature
controller, set loop 1 to 37.0 C with medium heater range, poll temperature,
heater output, and loop status until the documented stability condition is met,
then close all resources.

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
loop
setpoint_c
heater_range
temperature_history_c
stable_temperature_c
heater_percent
status
```
