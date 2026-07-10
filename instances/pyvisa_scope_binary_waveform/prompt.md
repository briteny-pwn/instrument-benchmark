# Prompt

## Task Environment

You are working in a Python project that needs to control a simulated
oscilloscope named `MockScope500`.

The available environment materials include:

- `environment/instrument_manual.md`: the instrument manual and communication
  requirements.

The instrument is accessed through the PyVISA API. During execution, the runtime
will provide a PyVISA-compatible simulated instrument. You do not need to
implement the simulator.

## Task Objective

Design and implement Python code required to access `MockScope500` and run a
minimal binary waveform acquisition experiment.

Create a Python module named:

```text
solution.py
```

Your implementation should:

1. Use PyVISA to connect to the `MockScope500` simulated instrument.
2. Configure the required communication parameters from the instrument manual.
3. Design a reusable oscilloscope access abstraction. A class-based design is
   recommended, but the internal structure is up to you.
4. Expose a callable experiment entry point:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

5. In `run_experiment`, perform the following experiment:
   - connect to the instrument;
   - identify the instrument;
   - reset the acquisition state;
   - select channel 1 as the waveform source;
   - configure binary byte waveform transfer;
   - set the waveform preamble scale and offset parameters;
   - acquire the waveform using PyVISA binary value reading;
   - convert raw ADC byte values to voltages using the manual formula;
   - close all instrument resources.

## Output Format

The `run_experiment` function should return a dictionary containing the
experiment result. It may also write the same result to `output_path` when an
output path is provided.

Expected result fields:

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

The raw waveform values must come from the instrument response. Do not hard-code
the waveform list or computed voltages.

