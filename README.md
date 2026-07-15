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
- Model authoring and candidate execution now run in separate hardened Docker
  containers. Hidden specs, scenarios, traces, repository files, and public
  internet are outside the candidate boundary.
- All 19 model-facing bundles pass the automated leakage scanner, and each has
  a separately materialized, unscored authoring scenario.
- The reference suite currently covers 69 hidden-world runs and passes 19/19
  instances with a score of `1.0`.
- The negative suite currently rejects 12/12 known invalid approaches, and 61
  evaluator/harness unit tests pass.
- Three representative PyVISA instances now use reproducible frozen
  `core`/`generalization`/`adversarial` world distributions.

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
  registry.json
  common/
    instance_manifest.py
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
  README.md

benchmark_harness/
  cli.py
  docker_runtime.py
  simulator_service.py
  solution_runner.py

docker/
  agent.Dockerfile
  simulator.Dockerfile
  runner.Dockerfile
  proxy.Dockerfile

runs/
  {run_id}/

docs/
  BENCHMARK_CARD.md
  benchmark_credibility.md
  capability_matrix.md
  instances.md
  validity/
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
- `experience/`: legacy development workspaces; old results are considered
  contaminated and are not formal benchmark runs.
- `runs/`: ignored, immutable-by-convention run artifacts produced by the
  isolated harness.
- `docs/`: human-facing notes and summaries that are not part of the model
  input.

## Isolated Run Lifecycle

A formal run separates task authoring from hidden evaluation:

```text
lint visible bundle
  -> create neutral /workspace
  -> start unscored authoring simulator
  -> run candidate agent in Docker
  -> extract solution.py only
  -> destroy authoring environment
  -> run solution.py in fresh hidden scenario containers
  -> collect result, trace, and simulator state
  -> write deterministic evaluation report
```

During authoring, the candidate can see only:

```text
/workspace/
  prompt.md
  environment/
    instrument_manual.md
    simulator_protocol.md
```

The candidate cannot mount the repository, `.git`, `evaluations/`, other task
workspaces, user configuration directories, the Docker socket, simulator
control data, or hidden traces. Public network access is disabled. Model API
traffic is routed through a dedicated proxy so the real host credential is not
placed in the candidate container.

The authoring scenario is unscored and distinct from every hidden evaluation
scenario. After generation, only `solution.py` crosses the boundary into
evaluation. Each hidden scenario uses a fresh simulator and a fresh read-only,
non-root solution runner.

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

For each hidden scenario, the official isolated evaluator:

1. Creates an internal Docker network and starts the hidden simulator backend.
2. Runs `solution.py` in a new read-only, non-root container that mounts no
   repository or evaluation files and has no public network route.
3. Stops the simulator and collects result, trace, execution status, and final
   state through a simulator-only control volume.
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

## Validation TODO

Engineering infrastructure completed in the current development version:

- [x] Define a machine-readable registry for all 19 instances, including
  capability tags, difficulty factors, backend fidelity, task/output contracts,
  safety invariants, and independent oracle bindings.
- [x] Add prompt/spec/registry consistency checks and explicit unscored
  authoring-world materialization.
- [x] Pilot deterministic parameterized world generation on an ASCII DMM,
  binary oscilloscope, and coupled multi-instrument task.
- [x] Add structured failure codes, response-bound anti-hardcode checks,
  single-source static/runtime import restrictions, and exact negative-suite
  assertions.
- [x] Add manifest schema v2, pinned dependencies, a Benchmark Card, validity
  analysis tooling, study templates, and a Docker collected-evidence CI entry
  point.

Outstanding work required before publication-level model ranking:

- [ ] Extend parameterized world distributions beyond the three pilot
  instances; document each sampling population and add substantially more than
  three frozen worlds where statistical generalization is claimed.
- [ ] Add at least one semantic negative candidate for every instance and
  positive/negative coverage for every v2 check type.
- [ ] Run the full 19-instance reference suite through the official Docker
  collected-evidence path on release infrastructure.
- [ ] Collect repeated results from 5--8 representative models plus null,
  template, reference, and qualified human baselines.
- [ ] Publish MIPR/MHSPR, item difficulty and discrimination, failure
  categories, test-retest variance, and paired model comparisons.
- [ ] Run rubric-weight, threshold, and scenario-composition sensitivity
  analyses on real baseline records.
- [ ] Arrange independent domain-expert review and publish adjudication
  outcomes.
- [ ] Calibrate a representative SCPI/VISA, yaq, and native EPICS subset
  against native simulators or real hardware, reporting the transfer gap.
- [ ] Expand native EPICS/Tango coverage before making ecosystem-specific
  compatibility claims.

Detailed evaluator and backend work remains tracked in
[`evaluations/TODO.md`](evaluations/TODO.md).

## Setup

Create a local environment and install the hidden evaluation dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

`requirements.txt` remains the direct-dependency declaration; formal images
and reproducible local validation use the fully pinned lock file.

## Running Instances

Docker Desktop must be running. Configure a model credential in the host
environment; it is injected only into the API proxy container.

```bash
export BENCHMARK_MODEL_API_KEY=...
# Optional for a compatible upstream:
export BENCHMARK_MODEL_API_BASE_URL=https://api.anthropic.com
```

Run the full initialize, author, extract, and evaluate workflow:

```bash
.venv/bin/python -m benchmark_harness run \
  --instance pyvisa/pyvisa_dc_power_supply_basic \
  --agent claude \
  --model sonnet
```

The same workflow can be controlled stage by stage:

```bash
.venv/bin/python -m benchmark_harness init --instance SOURCE/INSTANCE --agent claude --model MODEL
.venv/bin/python -m benchmark_harness generate --run RUN_ID
.venv/bin/python -m benchmark_harness evaluate --run RUN_ID
```

Formal run artifacts are written under the ignored `runs/{run_id}/` directory:

```text
manifest.json
candidate/solution.py
agent/events.jsonl
agent/summary.json
evaluation/report.json
hashes.json
```

Manifest schema v2 records the benchmark release, clean/dirty source revision,
spec/scenario/generator and dependency hashes, authoring/evaluation/model
seeds, image digests, runtime, model identity, decoding availability, and
timestamps. `hashes.json` additionally binds the visible input, extracted
solution, and report so a run can be audited without exposing hidden
evaluation material to the candidate.

The release claim, limitations, baseline statistics, sensitivity tools, and
native/hardware and expert-review protocols are documented in
[`docs/BENCHMARK_CARD.md`](docs/BENCHMARK_CARD.md) and
[`docs/validity/README.md`](docs/validity/README.md). External observations are
not bundled; empty templates are provided and analyses report
`blocked_no_data` when no records are supplied.

Before a formal run, validate every visible bundle and the Docker boundary:

```bash
.venv/bin/python -m benchmark_harness lint-instance
.venv/bin/python -m benchmark_harness security-check --instance SOURCE/INSTANCE
```

See [`docs/isolation.md`](docs/isolation.md) for the trust boundaries, network
topology, artifact format, and credential handling.

Run repository-level evaluator checks:

```bash
.venv/bin/python -m evaluations.common.validate_instances
.venv/bin/python -m evaluations.run_reference_suite
.venv/bin/python -m evaluations.run_negative_suite
.venv/bin/python -m unittest discover -s benchmark_harness/tests
```

At least one release/CI shard should also exercise the same Docker
collected-evidence path used by formal runs:

```bash
.venv/bin/python -m evaluations.run_isolated_suite \
  --instance pyvisa/pyvisa_dc_power_supply_basic
# Use --all for release validation.
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

- one complete `InstanceManifest` entry in `evaluations/registry.json`, including
  capability and difficulty labels, backend fidelity, task inputs, observable
  outputs, safety invariants, scenario distribution, oracle bindings, and the
  public-constant allowlist;
- instrument command manual and response formats;
- raw simulator connection instructions;
- a concrete instrument-related experiment;
- an output schema with placeholders for measured/discovered values;
- causal cleanup or safety behavior required by the experiment.
- at least three hidden scenarios, including changed observations or targets;
- an `authoring` configuration with a unique seed for an unscored materialized
  development scenario;
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

The validator cross-checks the registry against every visible prompt and hidden
spec. See [`docs/capability_matrix.md`](docs/capability_matrix.md) for the full
review matrix and metadata contract.
