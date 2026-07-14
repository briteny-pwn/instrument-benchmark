# Task Goal

Create `solution.py`. Connect to the simulator, identify the sensor, discover
its channels, collect five
measurements from the documented channel, compute the mean and sample standard
deviation, decide whether the signal is stable, and close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Write the result JSON to `output_path` and return the same dictionary. The
dictionary must contain:

```json
{
  "instrument": "fake-sensor",
  "resource": "<discovered resource identifier>",
  "channel": "signal",
  "sample_count": 5,
  "mean_signal": "<number computed from the readings>",
  "std_signal": "<sample standard deviation>",
  "stable": "<boolean>"
}
```
