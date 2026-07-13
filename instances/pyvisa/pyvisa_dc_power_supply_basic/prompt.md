# Task Environment

You are given a simulator connection protocol and a manual for one DC power
supply-like instrument. The hidden simulator behaves like the documented
instrument, but you must not use PyVISA or any instrument framework.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Implement your own instrument client/interface from scratch using only Python
standard library modules. Connect to the raw simulator gateway, open the
documented instrument, identify it, configure channel 1 to 3.3 V with a 0.5 A
current limit, enable output, measure the channel voltage, and close all handles
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
  "instrument": "MockDP100",
  "channel": 1,
  "target_voltage_v": 3.3,
  "current_limit_a": 0.5,
  "measured_voltage_v": 3.3,
  "output_enabled": true
}
```
