# Task Goal

Discover and identify every required instrument, configure the supply and
switch paths, upload and enable the AWG staircase, acquire the DUT output with
the DMM and scope, compare the two observations, and decide whether validation
passed. After acquisition, disable both outputs, open all switch routes, and
close the resources you opened.

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
    "psu": "MockPSU320",
    "switch": "MockSwitch48",
    "awg": "MockAWG900",
    "scope": "MockScope1200",
    "dmm": "MockDMM7510"
  },
  "resources": {
    "psu": "<discovered resource>",
    "switch": "<discovered resource>",
    "awg": "<discovered resource>",
    "scope": "<discovered resource>",
    "dmm": "<discovered resource>"
  },
  "supply_voltage_v": "<measured value>",
  "supply_output_enabled": "<observed boolean>",
  "switch_closed_paths": "<observed paths>",
  "awg_waveform": "DUT_STAIR",
  "awg_points": [0.0, 0.3, 0.6, 0.9, 1.2, 0.9, 0.6, 0.3],
  "awg_output_enabled": "<observed boolean>",
  "dmm_samples_v": ["<measured values>"],
  "dmm_average_v": "<computed value>",
  "scope_raw_codes": ["<decoded byte values>"],
  "scope_voltages_v": ["<computed values>"],
  "scope_peak_to_peak_v": "<computed value>",
  "max_scope_dmm_error_v": "<computed value>",
  "validation_passed": "<true or false>",
  "final_psu_output_enabled": false,
  "final_awg_output_enabled": false,
  "final_switch_closed_paths": "(@)"
}
```
