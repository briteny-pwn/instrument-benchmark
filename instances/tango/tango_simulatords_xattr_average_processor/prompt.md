# Task Goal

Create `solution.py`. Connect to the simulator, discover and open the two
temperature sensors and processor device, read both sensor temperatures, read
the processor average, deviation, and state, determine whether the processor
values agree with the documented formulas, then close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`. It must
contain these fields:

```text
devices
sensor_temperatures_c
average_temperature_c
deviation_c
processor_state
validation_passed
```

The `devices` object must contain `sensor_a`, `sensor_b`, and `processor`.
