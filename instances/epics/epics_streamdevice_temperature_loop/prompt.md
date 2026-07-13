# Task Environment

You are given a simulator connection protocol and a manual for one
temperature-controller-like instrument.

Visible files:

- `environment/instrument_manual.md`: instrument commands and response formats.
- `environment/simulator_protocol.md`: raw socket JSON-line simulator protocol.

# Task Goal

Create `solution.py`. Implement an instrument client from scratch, connect to
the simulator, identify the controller, set loop 1 to 37.0 C with medium heater
range, poll temperature and loop status until stable, and close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "TempLoop336",
  "loop": 1,
  "setpoint_c": 37.0,
  "heater_range": "MED",
  "temperature_history_c": [22.4, 31.2, 36.7, 37.02, 37.0],
  "stable_temperature_c": 37.0,
  "heater_percent": 12.5,
  "status": "STABLE"
}
```
