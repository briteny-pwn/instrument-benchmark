# Prompt

## Task Environment

You are working in a Python project that needs to control a simulated arbitrary
waveform generator named `MockAWG100`.

The available environment materials include:

- `environment/instrument_manual.md`: the instrument manual and communication
  requirements.

The instrument is accessed through the PyVISA API. During execution, the runtime
will provide a PyVISA-compatible simulated instrument. You do not need to
implement the simulator.

## Task Objective

Design and implement Python code required to access `MockAWG100` and upload a
small waveform using PyVISA ASCII value writing.

Create a Python module named:

```text
solution.py
```

Your implementation should:

1. Use PyVISA to connect to the `MockAWG100` simulated instrument.
2. Configure the required communication parameters from the instrument manual.
3. Design a reusable waveform generator access abstraction. A class-based design
   is recommended, but the internal structure is up to you.
4. Expose a callable experiment entry point:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

5. In `run_experiment`, perform the following experiment:
   - connect to the instrument;
   - identify the instrument;
   - reset the instrument;
   - upload the waveform named `RAMP` with points `[0.0, 0.25, 0.5, 0.75, 1.0]`;
   - select `RAMP` as the active arbitrary waveform;
   - set output amplitude to `2.0 Vpp`;
   - enable output;
   - query the active waveform name;
   - query output state;
   - close all instrument resources.

## Output Format

The `run_experiment` function should return a dictionary containing the
experiment result. It may also write the same result to `output_path` when an
output path is provided.

Expected result fields:

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

The waveform upload should be generated from the point list in code. Do not
hard-code a preformatted upload command string.

