# Task Environment

You are given a simulator connection protocol and a manual for a source + DMM
station sweep. This instance is historically inspired by QCoDeS-style station
sweeps, but the task is now raw protocol only. The hidden simulator behaves like
the documented devices, and you must not use QCoDeS, PyVISA, lab drivers, or any
instrument framework.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Implement your own instrument client/interface from scratch using only Python
standard library modules. Discover resources, identify the gate source and DMM,
enable the source, sweep gate voltage over `[-0.1, 0.0, 0.1, 0.2, 0.3]`, query
the DMM at each setpoint, fit a line to measured voltage versus setpoint, and
close all handles and sockets.

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
  "framework": "raw_protocol",
  "instruments": {"source": "MockGateSource", "dmm": "MockDMM7510"},
  "resources": {
    "source": "TCPIP0::203.0.113.210::inst0::INSTR",
    "dmm": "TCPIP0::203.0.113.211::inst0::INSTR"
  },
  "sweep_setpoints_v": [-0.1, 0.0, 0.1, 0.2, 0.3],
  "measured_voltage_v": [-0.19, 0.01, 0.21, 0.41, 0.61],
  "slope": 2.0,
  "intercept": 0.01,
  "validation_passed": true
}
```
