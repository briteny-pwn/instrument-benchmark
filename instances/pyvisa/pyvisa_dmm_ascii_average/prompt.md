# Task Goal

Create `solution.py`. Connect to the simulator, discover, open, and identify the
DMM, configure DC voltage measurement with range 10 V, resolution
0.001 V, and 5 samples, start acquisition, query the ASCII sample list, parse
it, compute the average, clear the trace buffer, and close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "MockDMM2000",
  "resource": "<discovered resource identifier>",
  "measurement": "dc_voltage",
  "sample_count": 5,
  "samples_v": ["<five parsed numeric readings>"],
  "average_voltage_v": "<mean of samples_v>",
  "unit": "V"
}
```
