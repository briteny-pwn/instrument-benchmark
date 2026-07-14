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

## Current Status

- 19 instances across PyVISA-, QCoDeS-, EPICS-, Tango-, and yaq-sourced task
  families.
- All current instances use evaluation schema v2, at least three hidden
  scenarios, explicit pass gates, and independent trace/simulator-state
  evidence.
- The reference suite currently covers 69 hidden-world runs and passes 19/19
  instances with a score of `1.0`.
- The negative suite currently rejects 12/12 known invalid approaches, and 35
  evaluator unit tests pass.

These numbers verify the repository implementation; they are not, by
themselves, evidence of model-ranking validity or transfer to real hardware.
The remaining validation work is described in
[`docs/benchmark_credibility.md`](docs/benchmark_credibility.md) and
[`evaluations/TODO.md`](evaluations/TODO.md).

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
    coupled_signal_gateway.py
    linear_sweep_gateway.py
    yaq_native_gateway.py
    raw_trace.py
    import_guard.py
    grader_core.py
  {source}/
    {instance_id}/
      spec.json
      grader.py
      reference_solution/
      pyvisa_sim/ or sim/

experience/
  {source}/
    {instance_id}/
      prompt.md
      environment/
      solution.py

docs/
  benchmark_credibility.md
  instances.md
  sources/
    pyvisa.md
    qcodes.md
    epics.md
    tango.md
    yaq.md
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
- `tango`: tasks may be inspired by Tango Controls and SimulatorDS device,
  command, attribute, property, state, and event semantics, but the candidate
  still writes a raw protocol client from the manual.
- `yaq`: hidden evaluation uses native `yaqd-fakes` daemons through an internal
  yaq client, but the candidate only sees a raw socket protocol and writes its
  own client from the manual.

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
PyTango
pytango
tango
taurus
sardana
fandango
softioc
bluesky
ophyd
yaq
yaqc
yaqd_core
yaqd_fakes
yaq_traits
avro
fastavro
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
`pyvisa-sim`, a standard-library state-machine simulator, or native hidden
`yaqd-fakes` daemons, but externally it exposes only JSON-line socket
operations:

```json
{"op": "list_resources"}
{"op": "open", "resource": "USB0::...::INSTR"}
{"op": "write", "handle": "h1", "command": "*RST"}
{"op": "query", "handle": "h1", "command": "*IDN?"}
{"op": "close", "handle": "h1"}
```

All current instances use evaluation schema v2. Its scoring dimensions are:

- `sim_execution`: candidate runs against the raw simulator gateway.
- `forbidden_api`: candidate avoids blocked framework imports.
- `task_success`: final experiment result and hidden simulator state match the
  task goal.
- `instrument_access`: candidate genuinely connects to and opens the simulated
  instruments through its own raw client.
- `protocol_correctness`: candidate sends the important command families
  described by the manual.
- `state_process`: candidate follows the required experimental phases, scored
  by ordered milestone coverage rather than exact trace replay.
- `safety_and_cleanup`: candidate closes handles/sockets and avoids leaving
  unsafe simulator state.

Legacy specs are still readable for compatibility, but no current instance
uses the legacy path.

Every current instance runs the same candidate against multiple hidden
scenarios. Numeric results are independently reconstructed from
simulator responses, essential access/safety checks are pass gates, and the
report includes a scenario pass rate plus `robustness`. See
[`docs/benchmark_credibility.md`](docs/benchmark_credibility.md) for the
construction policy.

### Evaluation Flow

For each hidden scenario, the evaluator:

1. Starts the hidden simulator backend and its raw JSON-line gateway.
2. Runs the candidate in a guarded process with the endpoint supplied through
   environment variables.
3. Collects the returned result, gateway trace, execution status, and hidden
   final simulator state.
4. Applies deterministic result, causal-state, protocol-coverage, ordered
   milestone, safety, cleanup, and anti-hardcode checks.
5. Applies required pass gates, then aggregates scores and reliability across
   scenarios and repeated runs.

The evaluator does not require an exact reference trace. Equivalent valid
command paths may receive full credit when they produce the required state and
independent evidence.

### Interpreting Results

The weighted `total` is a diagnostic capability score, not the sole definition
of success. A candidate passes an instance only when `pass` is true and all
required gates hold. Benchmark reports should therefore lead with instance
pass rate and hidden-scenario pass rate, then use dimension scores and trace
evidence to explain failures.

A correct-looking `result.json` is insufficient for a full pass when the trace
does not demonstrate genuine instrument access or when hidden simulator state
contradicts the claimed result. Conversely, a harmless difference from the
reference command sequence should not fail an otherwise correct experiment.

### Backend Matrix

| Source | Hidden backend | Native ecosystem runtime |
| --- | --- | --- |
| `pyvisa` | `pyvisa-sim` and coupled-signal simulators | Partial: native `pyvisa-sim` is hidden behind the raw gateway |
| `qcodes` | Linear-sweep simulator | No |
| `epics` | Persistent state-machine simulator | No |
| `tango` | Persistent state-machine simulator | No |
| `yaq` | `yaqd-fakes` through `yaq_native_gateway.py` | Yes |

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

### Tango Evaluation Status

The current `tango` evaluations do not start native Tango Database servers,
PyTango device servers, DeviceTestContext, or SimulatorDS/fandango processes.
They use `evaluations/common/state_machine_gateway.py`, a standard-library
finite-state simulator that reproduces task-specific behavior derived from
Tango Controls and SimulatorDS.

This keeps the default benchmark path lightweight. A native Tango/SimulatorDS
backend is future work tracked in `evaluations/TODO.md`.

### Yaq Evaluation Status

The current `yaq` evaluations use `evaluations/common/yaq_native_gateway.py`.
That gateway starts native `yaqd-fakes` daemons, talks to them through the
evaluation-only yaq client, and wraps the behavior behind the same JSON-line raw
socket protocol used by other sources.

Candidates still do not see or use yaq, yaqc, Avro RPC, or yaqd-fakes directly.

## Credibility and Limits

The evaluator is designed to be more than output-schema matching:

- candidate claims are checked against independently observed trace and hidden
  simulator state;
- hidden scenarios vary resources, measurements, targets, and failure-relevant
  conditions to make constant-output solutions unreliable;
- ordered milestones receive partial credit, while essential access, safety,
  and cleanup behavior can be enforced as pass gates;
- native yaq evaluation verifies that the common raw gateway can wrap a real
  ecosystem simulator without exposing its high-level client to candidates.

Important limitations remain:

- most tasks currently use three hand-authored hidden scenarios rather than a
  large generated distribution;
- EPICS and Tango behavior is reproduced by state machines rather than their
  native runtimes;
- score weights and thresholds still need sensitivity analysis and independent
  expert review;
- model baselines, repeated-run confidence intervals, contamination analysis,
  and real-hardware calibration have not yet been published.

Until those studies are complete, scores should be treated as reproducible
simulation-benchmark evidence, not a universal measure of real laboratory
competence.

## Setup

Create a local environment and install the hidden evaluation dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

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

Run repository-level evaluator checks:

```bash
.venv/bin/python -m evaluations.common.validate_instances
.venv/bin/python -m evaluations.run_reference_suite
.venv/bin/python -m evaluations.run_negative_suite
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

Tango-sourced raw protocol instances:

- `tango_simulatords_dynamic_temperature_alarm`
- `tango_motor_attribute_command_scan`
- `tango_simulatords_xattr_average_processor`
- `tango_event_like_detector_acquisition`

Yaq-sourced raw protocol instances:

- `yaq_fake_sensor_stability_scan`
- `yaq_fake_motor_sensor_alignment`
- `yaq_fake_spectrometer_triggered_acquisition`

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
- an output schema with placeholders for measured/discovered values;
- causal cleanup or safety behavior required by the experiment.
- at least three hidden scenarios, including changed observations or targets;
- independent result oracles derived from trace and simulator state rather
  than candidate-reported fields alone;
- pass gates for genuine access and any task-critical safety behavior;
- a standard-library reference solution and negative fixtures for hardcoding,
  forbidden APIs, missing protocol steps, or missing cleanup as applicable.

Keep starter TODO code out of the model-visible input. Keep gold behavior,
reference solutions, hidden simulators, and graders out of `instances/`.
Keep scoring weights, expected traces, import-guard details, and fixed simulator
answers out of model-visible documents.
Keep human-facing summaries in `docs/` instead of inside concrete instance
directories.
