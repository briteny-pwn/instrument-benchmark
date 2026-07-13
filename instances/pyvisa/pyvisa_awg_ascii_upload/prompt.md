# Task Environment

You are given a simulator connection protocol and a manual for one arbitrary
waveform generator-like instrument. The hidden simulator behaves like the
documented instrument, but you must not use PyVISA or any instrument framework.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Implement your own instrument client/interface from scratch using only Python
standard library modules. Connect to the raw simulator gateway, open the AWG,
identify it, upload a five-point ASCII waveform named `RAMP`, select it, set
amplitude to 2 Vpp, enable output, verify output state, and close all handles
and sockets.

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
  "instrument": "MockAWG100",
  "waveform": "RAMP",
  "points": [0.0, 0.25, 0.5, 0.75, 1.0],
  "point_count": 5,
  "amplitude_vpp": 2.0,
  "output_enabled": true
}
```
