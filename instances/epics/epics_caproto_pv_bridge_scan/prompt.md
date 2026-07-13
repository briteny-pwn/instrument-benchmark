# Task Environment

You are given a simulator connection protocol and a manual for a PV-bridge-like
instrument interface.

Visible files:

- `environment/instrument_manual.md`: PV command mapping and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Create `solution.py`. Implement an instrument client from scratch, connect to
the simulator, identify the bridge, scan the documented bias setpoints, read
back each bias and detector count, collect monitor-like history entries, and
close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "CaprotoPvBridge",
  "pv_prefix": "MOCK:",
  "bias_setpoints_v": [-0.2, 0.0, 0.2, 0.4],
  "bias_readbacks_v": [-0.198, 0.002, 0.201, 0.399],
  "detector_counts": [102, 150, 197, 241],
  "count_slope_per_v": 231.6666666667,
  "snapshot": {
    "MOCK:BIAS:SP": 0.4,
    "MOCK:BIAS:RBV": 0.399,
    "MOCK:DETECTOR:COUNT": 241
  },
  "monitor_history": ["BIAS:SP=-0.2", "BIAS:SP=0.0", "BIAS:SP=0.2", "BIAS:SP=0.4"]
}
```
