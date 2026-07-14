# Task Goal

Create `solution.py`. Connect to the simulator, identify the PV bridge, scan
the documented bias setpoints, read each bias readback and detector count,
collect the corresponding monitor history, calculate the documented count
slope and final snapshot, then close all resources.

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
pv_prefix
bias_setpoints_v
bias_readbacks_v
detector_counts
count_slope_per_v
snapshot
monitor_history
```

The `snapshot` object must contain `MOCK:BIAS:SP`, `MOCK:BIAS:RBV`, and
`MOCK:DETECTOR:COUNT`.
