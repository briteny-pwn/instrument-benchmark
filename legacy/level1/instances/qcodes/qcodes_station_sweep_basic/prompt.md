# Task Goal

Discover and identify the gate source and DMM, enable the source, sweep gate
voltage over `[-0.1, 0.0, 0.1, 0.2, 0.3]`, measure at every setpoint, fit a line
to measured voltage versus setpoint, decide whether the transfer validation
passes, then disable the source and close the resources you opened.

# Output Format

Create a file named `solution.py` exposing:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "framework": "raw_protocol",
  "instruments": {"source": "MockGateSource", "dmm": "MockDMM7510"},
  "resources": {
    "source": "<discovered resource>",
    "dmm": "<discovered resource>"
  },
  "sweep_setpoints_v": [-0.1, 0.0, 0.1, 0.2, 0.3],
  "measured_voltage_v": ["<measured values>"],
  "slope": "<fitted value>",
  "intercept": "<fitted value>",
  "validation_passed": "<true or false>",
  "final_source_output_enabled": false
}
```
