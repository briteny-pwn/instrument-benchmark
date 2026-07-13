# Task Environment

You are given a simulator connection protocol and a manual for one oscilloscope-
like instrument. The hidden simulator behaves like the documented instrument,
but you must not use PyVISA or any instrument framework.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Implement your own instrument client/interface from scratch using only Python
standard library modules. Connect to the raw simulator gateway, open the scope,
identify it, configure CH1 binary waveform transfer, query `CURVE?`, decode the
base64 IEEE binary block yourself, convert raw byte codes to voltages using the
manual, and close all handles and sockets.

Forbidden imports include `pyvisa`, `qcodes`, `qcodes_contrib_drivers`,
`lab_drivers`, `pymeasure`, `bluesky`, `ophyd`, `pylabrobot`, and `opentrons`.

# Output Format

Create a file named `solution.py` exposing:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "MockScope500",
  "source": "CH1",
  "sample_count": 8,
  "raw_codes": [65, 66, 67, 68, 69, 70, 49, 50],
  "voltage_scale_v": 0.02,
  "voltage_offset_code": 128,
  "voltages_v": [-1.26, -1.24, -1.22, -1.2, -1.18, -1.16, -1.58, -1.56],
  "unit": "V"
}
```
