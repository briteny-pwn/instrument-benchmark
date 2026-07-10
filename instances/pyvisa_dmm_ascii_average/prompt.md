# Prompt

## Task Environment

You are working in a Python project that needs to control a simulated digital
multimeter named `MockDMM2000`.

The available environment materials include:

- `environment/instrument_manual.md`: the instrument manual and communication
  requirements.

The instrument is accessed through the PyVISA API. During execution, the runtime
will provide a PyVISA-compatible simulated instrument. You do not need to
implement the simulator.

## Task Objective

Design and implement Python code required to access `MockDMM2000` and run a
minimal DC voltage acquisition experiment.

Create a Python module named:

```text
solution.py
```

Your implementation should:

1. Use PyVISA to connect to the `MockDMM2000` simulated instrument.
2. Configure the required communication parameters from the instrument manual.
3. Design a reusable multimeter access abstraction. A class-based design is
   recommended, but the internal structure is up to you.
4. Expose a callable experiment entry point:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

5. In `run_experiment`, perform the following experiment:
   - connect to the instrument;
   - identify the instrument;
   - reset the instrument;
   - configure DC voltage measurement;
   - configure a 10 V range and 0.001 V resolution;
   - configure the sample count to `5`;
   - start the measurement;
   - read the 5 voltage samples as ASCII numeric values;
   - compute the average voltage;
   - clear the trace buffer;
   - close all instrument resources.

## Output Format

The `run_experiment` function should return a dictionary containing the
experiment result. It may also write the same result to `output_path` when an
output path is provided.

Expected result fields:

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

The samples must come from the instrument response. Do not hard-code the sample
list or average.
