# Task Environment

You are given a simulator connection protocol and manuals for a five-instrument
DUT validation bench: PSU, switch matrix, AWG, scope, and DMM. The hidden
simulator behaves like the documented instruments, but you must not use PyVISA
or any instrument framework.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Implement your own instrument client/interface from scratch using only Python
standard library modules. Discover and identify every required instrument,
configure the supply and switch paths, upload and enable the AWG staircase,
read DMM ASCII samples, read and decode the scope binary waveform, compare the
two observations, decide whether DUT validation passed, and close all handles
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
  "instruments": {
    "psu": "MockPSU320",
    "switch": "MockSwitch48",
    "awg": "MockAWG900",
    "scope": "MockScope1200",
    "dmm": "MockDMM7510"
  },
  "resources": {
    "psu": "USB0::0x9999::0x0320::PSU320001::0::INSTR",
    "switch": "GPIB0::7::INSTR",
    "awg": "USB0::0x9999::0x0900::AWG900001::0::INSTR",
    "scope": "TCPIP0::203.0.113.120::inst0::INSTR",
    "dmm": "GPIB0::24::INSTR"
  },
  "supply_voltage_v": 5.001,
  "supply_output_enabled": true,
  "switch_closed_paths": "(@101,102)",
  "awg_waveform": "DUT_STAIR",
  "awg_points": [0.0, 0.3, 0.6, 0.9, 1.2, 0.9, 0.6, 0.3],
  "awg_output_enabled": true,
  "dmm_samples_v": [0.0, 0.3, 0.6, 0.9, 1.2, 0.9, 0.6, 0.3],
  "dmm_average_v": 0.6,
  "scope_raw_codes": [50, 65, 80, 95, 110, 95, 80, 65],
  "scope_voltages_v": [0.0, 0.3, 0.6, 0.9, 1.2, 0.9, 0.6, 0.3],
  "scope_peak_to_peak_v": 1.2,
  "max_scope_dmm_error_v": 0.0,
  "validation_passed": true
}
```
