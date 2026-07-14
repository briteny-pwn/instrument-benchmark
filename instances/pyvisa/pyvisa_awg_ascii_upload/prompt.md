# Task Goal

Create `solution.py`. Connect to the simulator, open and identify the AWG,
upload a five-point ASCII waveform named `RAMP`, select it, set
amplitude to 2 Vpp and frequency to 1000 Hz, enable output, verify output state,
disable output, and close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "MockAWG100",
  "resource": "<discovered resource identifier>",
  "waveform": "RAMP",
  "points": [0.0, 0.25, 0.5, 0.75, 1.0],
  "point_count": 5,
  "amplitude_vpp": 2.0,
  "frequency_hz": 1000.0,
  "output_enabled_during_verification": true,
  "final_output_enabled": false
}
```
