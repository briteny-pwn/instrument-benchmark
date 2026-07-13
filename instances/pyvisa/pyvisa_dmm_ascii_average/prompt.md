# Task Environment

You are given a simulator connection protocol and a manual for one digital
multimeter-like instrument. The hidden simulator behaves like the documented
instrument, but you must not use PyVISA or any instrument framework.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Implement your own instrument client/interface from scratch using only Python
standard library modules. Connect to the raw simulator gateway, open the DMM,
identify it, configure DC voltage measurement with range 10 V and 5 samples,
start acquisition, query the ASCII sample list, parse it yourself, compute the
average, and close all handles and sockets.

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
  "instrument": "MockDMM2000",
  "measurement": "dc_voltage",
  "sample_count": 5,
  "samples_v": [1.001, 1.003, 0.999, 1.002, 1.0],
  "average_voltage_v": 1.001,
  "unit": "V"
}
```
