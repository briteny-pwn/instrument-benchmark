# Task Goal

Discover and identify the AWG, oscilloscope, and DMM described by the instrument
manual. Upload and select the `CAL_RAMP` waveform, perform the calibration
measurements, compute the requested metrics from the observed responses, and
decide whether the calibration passed. Restore the AWG to a safe output-off
state and close the resources you opened.

# Output Format

Create a file named `solution.py` exposing:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instruments": {
    "awg": "MockAWG700",
    "scope": "MockScope900",
    "dmm": "MockDMM650"
  },
  "resources": {
    "awg": "<discovered resource>",
    "scope": "<discovered resource>",
    "dmm": "<discovered resource>"
  },
  "awg_waveform": "CAL_RAMP",
  "awg_points": [-0.5, -0.25, 0.0, 0.25, 0.5],
  "dmm_samples_v": ["<measured values>"],
  "dmm_average_v": "<computed value>",
  "scope_raw_codes": ["<decoded byte values>"],
  "scope_voltages_v": ["<computed values>"],
  "scope_peak_to_peak_v": "<computed value>",
  "calibration_passed": "<true or false>",
  "final_awg_output_enabled": false
}
```
