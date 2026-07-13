# Instrument Access Benchmark

This repository contains benchmark instances for evaluating whether a model can
implement an instrument interface from scratch, connect to a simulated
instrument, and complete a small instrument-related experiment.

The model-facing input is deliberately small:

```text
instance = prompt + instrument manual + raw simulator protocol
```

The candidate must write its own client/driver code over a bare protocol. It
must not call PyVISA, QCoDeS, qcodes_contrib_drivers, lab drivers, PyMeasure,
Bluesky/Ophyd, or any other prebuilt instrument framework.

## Repository Layout

```text
instances/
  {source}/
    {instance_id}/
      prompt.md
      environment/
        instrument_manual.md
        simulator_protocol.md

evaluations/
  common/
    raw_sim_gateway.py
    state_machine_gateway.py
    raw_trace.py
    import_guard.py
    grader_core.py
  {source}/
    {instance_id}/
      README.md
      spec.json
      grader.py
      reference_solution/
      pyvisa_sim/

experience/
  {source}/
    {instance_id}/
      prompt.md
      environment/
      solution.py

docs/
  instances.md
  sources/
    pyvisa.md
    qcodes.md
    epics.md
```

Boundaries:

- `instances/`: model-visible task input only.
- `evaluations/`: hidden scoring logic, raw gateway, simulator definitions,
  traces, specs, and reference solutions.
- `experience/`: ignored local workspaces for real model trials.
- `docs/`: human-facing notes and summaries that are not part of the model
  input.

## Source Semantics

`source` means the historical or technical source used to construct the
simulated protocol material. It does not mean the candidate may call that
framework.

- `pyvisa`: hidden evaluation may use `pyvisa-sim` to model instrument behavior,
  but the candidate only sees a raw socket protocol.
- `qcodes`: tasks may be inspired by QCoDeS station/driver patterns, but the
  candidate still writes a raw protocol client from the manual.
- `epics`: tasks may be inspired by EPICS StreamDevice, asyn, soft IOC, or
  caproto behavior, but the candidate still writes a raw protocol client from
  the manual.

## Candidate Contract

Each solution exposes:

```python
def run_experiment(output_path: str = "result.json") -> dict:
    ...
```

Allowed implementation tools are Python standard library modules such as
`socket`, `json`, `base64`, `struct`, `time`, `pathlib`, and `statistics`.

Forbidden imports include:

```text
pyvisa
caproto
epics
pyepics
qcodes
qcodes_contrib_drivers
lab_drivers
pymeasure
pcaspy
softioc
bluesky
ophyd
pylabrobot
opentrons
```

The solution should connect to the simulator endpoint from:

```text
INSTRUMENT_SIM_HOST
INSTRUMENT_SIM_PORT
```

It should implement resource discovery/open/write/query/parsing/cleanup itself.

## Evaluation Contract

Evaluation starts a hidden TCP gateway. Internally that gateway may connect to
`pyvisa-sim` or a standard-library state-machine simulator, but externally it
exposes only JSON-line socket operations:

```json
{"op": "list_resources"}
{"op": "open", "resource": "USB0::...::INSTR"}
{"op": "write", "handle": "h1", "command": "*RST"}
{"op": "query", "handle": "h1", "command": "*IDN?"}
{"op": "close", "handle": "h1"}
```

Scoring dimensions:

- `sim_execution`: candidate runs against the raw simulator gateway.
- `forbidden_api`: candidate avoids blocked framework imports.
- `interface_implementation`: candidate connects, discovers, and opens expected
  resources through its own client.
- `protocol_trace`: candidate sends expected instrument commands.
- `state_transition`: candidate follows the required configuration/measurement
  sequence.
- `observation`: final experiment result matches the expected observation.
- `cleanup`: candidate closes handles and sockets.

### EPICS Evaluation Status

The current `epics` evaluations do not start native EPICS soft IOCs,
StreamDevice/asyn stacks, or caproto servers. They use
`evaluations/common/state_machine_gateway.py`, a standard-library finite-state
simulator that reproduces the task-specific behavior derived from those
ecosystems.

This keeps the benchmark portable and preserves the candidate contract: the
model sees only a manual plus a raw socket protocol, and still writes the
instrument interface from scratch. Native-framework evaluation backends are a
future improvement tracked in `evaluations/TODO.md`.

## Running Instances

Prepare or use:

```text
experience/{source}/{instance_id}/
```

Place the candidate solution at:

```text
experience/{source}/{instance_id}/solution.py
```

Run an instance:

```bash
cd evaluations/{source}/{instance_id}
../../../.venv/bin/python grader.py ../../../experience/{source}/{instance_id}/solution.py
```

## Current Instances

PyVISA-sourced raw protocol instances:

- `pyvisa_dc_power_supply_basic`
- `pyvisa_dmm_ascii_average`
- `pyvisa_scope_binary_waveform`
- `pyvisa_awg_ascii_upload`
- `pyvisa_resource_discovery_idn`
- `pyvisa_mixed_signal_calibration`
- `pyvisa_multi_instrument_dut_validation`

QCoDeS-sourced raw protocol instance:

- `qcodes_station_sweep_basic`

EPICS-sourced raw protocol instances:

- `epics_streamdevice_temperature_loop`
- `epics_asyn_serial_pump_interlock`
- `epics_softioc_record_chain_ramp`
- `epics_caproto_pv_bridge_scan`

## Adding a New Instance

Add model-visible files under:

```text
instances/{source}/{instance_id}/
```

Add hidden scoring files under:

```text
evaluations/{source}/{instance_id}/
```

A good instance should define:

- instrument command manual and response formats;
- raw simulator connection instructions;
- a concrete instrument-related experiment;
- output schema;
- cleanup and forbidden-library requirements.

Keep starter TODO code out of the model-visible input. Keep gold behavior,
reference solutions, hidden simulators, and graders out of `instances/`.
Keep human-facing summaries in `docs/` instead of inside concrete instance
directories.
