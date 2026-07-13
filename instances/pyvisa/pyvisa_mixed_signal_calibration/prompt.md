# Task Environment

You are given a simulator connection protocol and manuals for an AWG, scope,
and DMM bench. The hidden simulator behaves like the documented instruments,
but you must not use PyVISA or any instrument framework.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Implement your own instrument client/interface from scratch using only Python
standard library modules. Discover resources, identify the AWG/scope/DMM, upload
the `CAL_RAMP` waveform to the AWG, enable output, read DMM ASCII samples,
read and decode the scope binary waveform, compute average and peak-to-peak
metrics, decide whether calibration passed, and close all handles and sockets.

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
    "awg": "MockAWG700",
    "scope": "MockScope900",
    "dmm": "MockDMM650"
  },
  "resources": {
    "awg": "USB0::0x9999::0x0700::AWG700001::0::INSTR",
    "scope": "TCPIP0::203.0.113.90::inst0::INSTR",
    "dmm": "GPIB0::22::INSTR"
  },
  "awg_waveform": "CAL_RAMP",
  "awg_points": [-0.5, -0.25, 0.0, 0.25, 0.5],
  "dmm_samples_v": [1.198, 1.201, 1.2, 1.199],
  "dmm_average_v": 1.1995,
  "scope_raw_codes": [80, 95, 110, 95, 80, 65, 50, 65],
  "scope_voltages_v": [0.0, 0.3, 0.6, 0.3, 0.0, -0.3, -0.6, -0.3],
  "scope_peak_to_peak_v": 1.2,
  "calibration_passed": true
}
```
