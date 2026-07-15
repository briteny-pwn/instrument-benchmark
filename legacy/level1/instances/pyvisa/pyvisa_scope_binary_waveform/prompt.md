# Task Goal

Create `solution.py`. Connect to the simulator, discover, open, and identify the
scope, configure CH1 binary waveform transfer, query `CURVE?`, decode the
base64 IEEE binary block yourself, convert raw byte codes to voltages using the
manual, calculate mean and peak-to-peak voltage, and close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "MockScope500",
  "resource": "<discovered resource identifier>",
  "source": "CH1",
  "sample_count": "<decoded payload length>",
  "raw_codes": ["<decoded unsigned byte codes>"],
  "voltage_scale_v": 0.02,
  "voltage_offset_code": 128,
  "voltages_v": ["<converted voltage samples>"],
  "mean_voltage_v": "<mean of voltages_v>",
  "peak_to_peak_v": "<max(voltages_v) - min(voltages_v)>",
  "unit": "V"
}
```
