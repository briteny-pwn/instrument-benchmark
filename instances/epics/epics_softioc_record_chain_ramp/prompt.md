# Task Environment

You are given a simulator connection protocol and a manual for a soft-IOC-style
record chain connected to a power source and readback meter.

Visible files:

- `environment/instrument_manual.md`: record processing model, commands, and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Create `solution.py`. Implement an instrument client from scratch, connect to
the simulator, identify the ramp chain, enable the source, process the four
documented setpoints in order, read back each point, compute per-point error,
derive the maximum absolute error and alarm state, then close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "SoftIocRampChain",
  "setpoints_v": [0.0, 1.0, 2.0, 3.0],
  "readbacks_v": [0.01, 1.01, 2.0, 3.02],
  "errors_v": [0.01, 0.01, 0.0, 0.02],
  "max_abs_error_v": 0.02,
  "alarm": "NO_ALARM",
  "processed_records": ["ao:setpoint", "bo:enable", "ai:readback", "calc:error", "bi:alarm"]
}
```
