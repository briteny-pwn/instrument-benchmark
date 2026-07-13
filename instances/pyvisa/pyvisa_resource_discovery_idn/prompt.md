# Task Environment

You are given a simulator connection protocol and a manual for multiple
discoverable instruments. The hidden simulator behaves like the documented
devices, but you must not use PyVISA or any instrument framework.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Implement your own instrument client/interface from scratch using only Python
standard library modules. Connect to the raw simulator gateway, list resources,
open candidates, use `*IDN?` to find `MockLogger300`, read channel A temperature
and relative humidity, and close every handle and socket you open.

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
  "instrument": "MockLogger300",
  "selected_resource": "TCPIP0::198.51.100.30::inst0::INSTR",
  "channel": "A",
  "temperature_c": 23.45,
  "relative_humidity_percent": 45.6
}
```
