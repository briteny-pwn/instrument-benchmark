# PyVISA DC Power Supply Basic Access

This is a concrete benchmark instance for evaluating instrument access ability.

## Intended Input Interface

This instance is organized around the input interface you described:

1. `environment/`: the model-visible environment, including instrument
   documentation.
2. `prompt.md`: the model-facing task prompt that introduces the environment
   and states the required instrument-access task.

The scoring process is intentionally kept outside this input interface and can
be iterated later.

The expected model submission is a newly created Python module:

```text
solution.py
```

The model should design the instrument access code itself. This instance does
not provide TODO-based starter code.

## Files

- `prompt.md`: model-facing prompt.
- `environment/`: model-visible environment.
- `environment/instrument_manual.md`: simplified instrument documentation.

Hidden evaluation artifacts live outside this instance directory:

```text
../../evaluations/pyvisa_dc_power_supply_basic/
```

## Local Test

Run the external reference solution through the external grader:

```bash
../../.venv/bin/python ../../evaluations/pyvisa_dc_power_supply_basic/grader.py \
  ../../evaluations/pyvisa_dc_power_supply_basic/reference_solution/experiment.py
```

The important idea is that validation does not rely only on `result.json`.
The hidden evaluation runs candidate code against a pyvisa-sim instrument and
records connection, configuration, SCPI commands, semantic actions, state
transitions, and cleanup.
