# Task Goal

Create `solution.py`. Connect to the simulator, discover, open, and identify the
power supply, configure channel 1 to
3.3 V with a 0.5 A current limit, enable output, measure the channel voltage,
disable output, and close all handles and sockets.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "MockDP100",
  "resource": "<discovered resource identifier>",
  "channel": 1,
  "target_voltage_v": 3.3,
  "current_limit_a": 0.5,
  "measured_voltage_v": "<measured number>",
  "output_enabled_during_measurement": true,
  "final_output_enabled": false
}
```
