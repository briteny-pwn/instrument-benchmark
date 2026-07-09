# Prompt

## Task Environment

You are working in a Python project that needs to control a simulated DC power
supply named `MockDP100`.

The available environment materials include:

- `environment/instrument_manual.md`: the instrument manual and communication
  requirements.

The instrument is accessed through the PyVISA API. During execution, the runtime
will provide a PyVISA-compatible simulated instrument. You do not need to
implement the simulator.

## Task Objective

Design and implement the Python code required to access `MockDP100` and run a
minimal voltage-output experiment.

Create a Python module named:

```text
solution.py
```

Your implementation should:

1. Use PyVISA to connect to the `MockDP100` simulated instrument.
2. Configure the required communication parameters from the instrument manual.
3. Design a reusable power-supply access abstraction. A class-based design is recommended, but the exact internal structure is up to you.
4. Expose a callable experiment entry point:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

5. In `run_experiment`, perform the following experiment:
   - connect to the instrument;
   - identify the instrument;
   - set channel 1 voltage to `3.3 V`;
   - set channel 1 current limit to `0.5 A`;
   - enable channel 1 output;
   - measure channel 1 output voltage;
   - close all instrument resources.

## Output Format

The `run_experiment` function should return a dictionary containing the experiment result.
It may also write the same result to `output_path` when an output path is provided.

Expected result fields:

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

The measured voltage may differ slightly from `3.3 V`.

Do not hard-code the measured voltage. It must come from an instrument query.
