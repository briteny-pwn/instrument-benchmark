# Task Environment

You are given a simulator connection protocol and a manual for an addressed
serial pump-control bus.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Create `solution.py`. Implement an instrument client from scratch, connect to
the simulator, identify the bus controller, check the pressure interlock, start
pump P1 with retry handling, verify that it is running, read final pressure and
speed, and close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "AsynPumpBus",
  "pump": "P1",
  "interlock": "OK",
  "start_attempts": 2,
  "running": true,
  "initial_pressure_torr": 0.00082,
  "final_pressure_torr": 0.000046,
  "speed_rpm": 45000
}
```
