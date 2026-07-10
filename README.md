# Instrument Access Benchmark

This repository contains benchmark instances for evaluating whether a model can
access simulated scientific instruments through PyVISA and complete simple
instrument experiments.

The benchmark is designed around two principles:

- model-visible tasks should look like real instrument access work;
- evaluation should primarily judge observed experiment results, with PyVISA
  trace evidence used as supporting access evidence.

## Repository Layout

```text
instances/
  {instance_id}/
    README.md
    prompt.md
    environment/
      README.md
      instrument_manual.md

evaluations/
  common/
    grader_core.py
    trace_pyvisa.py
  {instance_id}/
    spec.json
    grader.py
    pyvisa_sim/*.yaml
    reference_solution/experiment.py

experience/
  {instance_id}/
    prompt.md
    environment/
    solution.py
```

## Instance Boundary

`instances/{instance_id}/` contains the model-visible task environment:

- `prompt.md`: task environment introduction, task objective, and output format;
- `environment/instrument_manual.md`: instrument documentation available to the
  model;
- `environment/README.md`: brief environment note.

The model should not see hidden simulation or scoring files.

`evaluations/{instance_id}/` contains hidden evaluation materials:

- `spec.json`: expected observations and access evidence requirements;
- `pyvisa_sim/*.yaml`: pyvisa-sim instrument behavior;
- `grader.py`: compatibility entry point into the common grader;
- `reference_solution/experiment.py`: validation solution.

## Evaluation Architecture

The current architecture is spec-driven and observation-first.

The common evaluator in `evaluations/common/`:

1. redirects `pyvisa.ResourceManager()` to the instance pyvisa-sim backend;
2. runs candidate `run_experiment(output_path=...)`;
3. reads the returned dictionary or written `result.json`;
4. compares observed result fields against `spec.json`;
5. records generic PyVISA trace events as supporting evidence.

The main score is weighted toward the experiment result:

```text
pyvisa_sim_execution: 0.2
observation:          0.5
access:               0.2
cleanup:              0.1
```

This means a solution is rewarded primarily for completing the instrument
experiment and producing the expected observations. Trace evidence is used for
general access quality, such as connection, communication parameters, PyVISA
value-transfer helpers, resource discovery, and cleanup.

## Running an Instance

For a model-facing trial, copy or use the prepared environment in:

```text
experience/{instance_id}/
```

The candidate should create:

```text
experience/{instance_id}/solution.py
```

with:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

Then run the hidden grader:

```bash
cd evaluations/{instance_id}
../../.venv/bin/python grader.py ../../experience/{instance_id}/solution.py
```

## Current Instances

- `pyvisa_dc_power_supply_basic`: single DC power supply setup and measurement.
- `pyvisa_dmm_ascii_average`: DMM DC voltage acquisition and averaging.
- `pyvisa_scope_binary_waveform`: oscilloscope IEEE binary block acquisition.
- `pyvisa_awg_ascii_upload`: AWG waveform upload with `write_ascii_values`.
- `pyvisa_resource_discovery_idn`: resource discovery and IDN-based selection.
- `pyvisa_mixed_signal_calibration`: multi-instrument calibration workflow.

## Adding a New Experiment

Prefer adding a new `spec.json` and pyvisa-sim behavior over writing a custom
grader. A good instance should define:

- what instrument documentation the model can see;
- what experiment the model must perform;
- what observed result fields prove success;
- what PyVISA access evidence is useful but not overly prescriptive.

For the same instrument, multiple experiments can share a simulator and differ
mainly in prompt/manual details and expected observations.

