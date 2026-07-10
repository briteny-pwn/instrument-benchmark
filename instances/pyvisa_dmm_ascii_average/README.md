# PyVISA DMM ASCII Average

This instance evaluates instrument access for a simulated digital multimeter
using PyVISA message-based communication and ASCII numeric data transfer.

## Model-Visible Input

- `prompt.md`: task prompt.
- `environment/instrument_manual.md`: simplified instrument manual.

The model should create `solution.py` and expose:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

No TODO-based starter code is provided.

## Hidden Evaluation

Hidden evaluation assets live outside this directory:

```text
../../evaluations/pyvisa_dmm_ascii_average/
```

The evaluator runs candidate code against a pyvisa-sim instrument and records
PyVISA access traces.

