# Prompt

## Task Environment

You are working in a Python project that needs to control a simulated
mixed-signal calibration bench.

The bench contains three target instruments:

- `MockAWG700`: arbitrary waveform generator
- `MockScope900`: oscilloscope
- `MockDMM650`: digital multimeter

There may also be non-target instruments in the resource list.

The available environment materials include:

- `environment/instrument_manual.md`: the instrument manual and communication
  requirements.

The instruments are accessed through the PyVISA API. During execution, the
runtime will provide PyVISA-compatible simulated instruments. You do not need to
implement the simulator.

## Task Objective

Design and implement Python code required to discover the target instruments,
configure the bench, run a mixed-signal calibration acquisition, and produce a
structured result.

Create a Python module named:

```text
solution.py
```

Your implementation should:

1. Use PyVISA's `ResourceManager` to list available resources.
2. Open candidate resources and query `*IDN?` to identify the three target
   instruments.
3. Configure each opened target resource using the communication parameters in
   the instrument manual.
4. Design reusable access abstractions for the instruments. A class-based design
   is recommended, but the internal structure is up to you.
5. Use PyVISA value transfer helpers where the manual indicates them:
   - upload the AWG waveform with `write_ascii_values`;
   - read DMM samples with `query_ascii_values` using the manual separator;
   - read the oscilloscope waveform with `query_binary_values`.
6. Expose a callable experiment entry point:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

7. In `run_experiment`, perform the following experiment:
   - discover and identify the three target instruments;
   - reset the target instruments;
   - upload the AWG waveform `CAL_RAMP`;
   - configure AWG amplitude, offset, and output state;
   - configure the DMM for DC voltage acquisition and read four samples;
   - configure the scope waveform source, encoding, width, and scaling;
   - acquire the scope waveform as a binary byte block;
   - convert raw scope codes to volts;
   - compute the scope peak-to-peak voltage and DMM average voltage;
   - decide whether the calibration passes using the manual tolerances;
   - close all opened resources and the resource manager.

## Output Format

The `run_experiment` function should return a dictionary containing the
experiment result. It may also write the same result to `output_path` when an
output path is provided.

Expected result fields:

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

The numeric data must come from instrument responses. Do not hard-code measured
sample lists or converted scope voltages.
