# Prompt

## Task Environment

You are working in a Python project where multiple PyVISA instruments may be
present. The target instrument is a simulated environmental logger named
`MockLogger300`.

The available environment materials include:

- `environment/instrument_manual.md`: the instrument manual and communication
  requirements.

The instrument is accessed through the PyVISA API. During execution, the runtime
will provide PyVISA-compatible simulated instruments. You do not need to
implement the simulator.

## Task Objective

Design and implement Python code required to discover the available resources,
select `MockLogger300` by querying instrument identities, and run a simple
temperature/humidity readout.

Create a Python module named:

```text
solution.py
```

Your implementation should:

1. Use PyVISA's `ResourceManager` to list available resources.
2. Open candidate resources and query `*IDN?` to find `MockLogger300`.
3. Configure the required communication parameters from the instrument manual
   after opening resources.
4. Design a reusable discovery/access abstraction. A class-based design is
   recommended, but the internal structure is up to you.
5. Expose a callable experiment entry point:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

6. In `run_experiment`, perform the following experiment:
   - list available PyVISA resources;
   - identify and select `MockLogger300`;
   - reset the selected logger;
   - configure sensor channel `A`;
   - query temperature and relative humidity;
   - close all instrument resources that were opened.

## Output Format

The `run_experiment` function should return a dictionary containing the
experiment result. It may also write the same result to `output_path` when an
output path is provided.

Expected result fields:

```json
{
  "instrument": "MockLogger300",
  "selected_resource": "TCPIP0::198.51.100.30::inst0::INSTR",
  "channel": "A",
  "temperature_c": 23.45,
  "relative_humidity_percent": 45.6
}
```

Do not hard-code the target resource name. The selected resource should be found
by listing resources and querying identities.

