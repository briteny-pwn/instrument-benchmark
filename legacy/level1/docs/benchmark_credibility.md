# Benchmark Credibility Design

This document defines how instances and evaluations should be constructed so a
high score supports a claim about instrument-access capability, rather than
memorization of one simulator trajectory.

## Claim Being Measured

The benchmark measures whether a candidate can use only a device manual and a
raw simulator protocol to implement an instrument interface, execute an
experiment, interpret observations, and leave the system in a safe state.

A score does not claim compatibility with real hardware unless the instance has
also passed a separately documented hardware-validation study.

## Instance Construction

Each instance is designed from an explicit capability matrix before its prompt
is written:

| Layer | Required design evidence |
| --- | --- |
| Device access | discovery, identity, open/close, timeout and terminator behavior |
| Protocol | command grammar, response parsing, error behavior, ASCII or binary data |
| Experiment | a result that must be computed from observed values |
| State process | causal phases such as configure, wait, acquire, verify, restore |
| Generalization | at least one hidden variation in identity, initial state, data, or timing |
| Safety | explicit acceptable final state and cleanup behavior |

Model-visible files remain exactly `prompt.md`, `instrument_manual.md`, and
`simulator_protocol.md`. Prompts state the task and output schema. Manuals state
device behavior. They must not mention grader checks, weights, expected traces,
reference solutions, or forbidden-import detection.

Output examples use placeholders for measured or discovered values. Literal
values are included only when they are task inputs, such as a requested voltage
setpoint or scan position.

## Evaluation Evidence

Evaluation uses four evidence layers:

1. Functional outcome: hidden simulator state and independently reconstructed
   observations establish whether the experiment succeeded.
2. Access evidence: socket, discovery, open, query/write, and response-dependent
   output establish that the candidate interacted with the instrument.
3. Process and safety: ordered causal milestones and final-state checks detect
   unsafe or invalid workflows without requiring an exact reference trace.
4. Robustness: the same candidate is rerun against hidden scenario variations;
   pass rate is reported separately and contributes to the total.

Candidate-reported JSON is never sufficient evidence by itself. Derived values
such as averages, standard deviations, peaks, or efficiencies should be
recomputed from hidden trace responses or backend state.

State-machine scenarios must model persistent causal state. Reopening a handle
must not rewind response progress. Writes should update shared state and later
queries should derive responses from that state whenever an experiment depends
on configuration, interlocks, motion, acquisition, or cleanup.

## Passing Rules

Weighted scores support diagnosis and partial credit. Required gates determine
validity. Recommended gates are:

- no forbidden framework import;
- genuine instrument access;
- full agreement with an independent result oracle;
- acceptable final safety state;
- complete handle and socket cleanup.

For multi-scenario instances, the report includes scenario totals, pass rate,
and an aggregate robustness score. A high average cannot compensate for a pass
rate below the instance's declared minimum. Randomized scenarios should set
`suite.repetitions` so pass rate covers multiple independent daemon runs rather
than one favorable draw.

Scenario-suite reports also include descriptive total-score statistics and
per-scenario reliability summaries. Pass-rate uncertainty uses a Wilson 95%
interval; the mean-score interval is a normal approximation and must not be
interpreted as a population claim when scenarios are heterogeneous.

## Validation

Run the visible-boundary validator with:

```text
.venv/bin/python -m evaluations.common.validate_instances
```

Every reference solution must pass every hidden scenario. Negative solutions
must cover hardcoded output, fixed resource names, missing cleanup, forbidden
imports, incorrect state ordering, and incorrect parsing. Randomized simulators
must be evaluated repeatedly before release to estimate score variance.

All 19 current instances use spec v2, at least three hidden scenarios, and
required gates. This is structural coverage, not empirical validation of task
difficulty or real-hardware transfer.

Current migrated exemplars are:

- `yaq_fake_sensor_stability_scan`: randomized numeric observations, three
  hidden signal/resource variants, trace-derived statistics, and repeated runs.
- `pyvisa_dc_power_supply_basic`: three pyvisa-sim device variants, hidden
  post-run setpoint/current queries, measurement-response consistency, and a
  mandatory final output-off safety gate.
- `pyvisa_dmm_ascii_average`: three resource/data variants, including signed
  scientific notation, with sample-list/count/mean reconstruction from the
  hidden ASCII response and post-run configuration queries.
- `pyvisa_scope_binary_waveform`: variable 6/8/12-byte waveforms, one- and
  two-digit IEEE block lengths, hidden payload decoding, affine voltage
  conversion, waveform statistics, and preamble-state snapshots.
- `pyvisa_awg_ascii_upload`: semantic parsing of the uploaded waveform command,
  equivalent numeric-format support, hidden initial-state variants, persisted
  amplitude/frequency selection, observed ON response, and final OFF gate.
- `pyvisa_mixed_signal_calibration`: three-instrument discovery, source-state
  preconditions on downstream measurements, independent ASCII and IEEE-block
  reconstruction, passing and out-of-tolerance hidden observations, and a
  mandatory final AWG output-off state.
- `pyvisa_multi_instrument_dut_validation`: a causally coupled five-instrument
  signal chain where PSU voltage, switch routes, uploaded AWG data, amplitude,
  and output states directly determine DMM and scope observations. Hidden
  scenarios cover measurement noise and an actual DUT gain failure.
- `pyvisa_resource_discovery_idn`: target resources move across TCPIP, GPIB,
  and USB topologies with changing distractors, identities, initial channels,
  numeric formats, and observations. Open-event evidence distinguishes explicit
  communication configuration from gateway defaults.
- `qcodes_station_sweep_basic`: DMM observations are computed from the gate
  source's actual current setpoint and output state. Hidden transfer functions
  include noise and a failing slope/intercept case, while fit and pass/fail
  values are independently reconstructed.
- EPICS-sourced instances: persistent causal state covers temperature
  stabilization, pressure/interlock retry behavior, source/readback/alarm
  chains, and PV scans with positive and negative detector response. These are
  portable state-machine backends, not native EPICS deployments.
- Tango-sourced instances: hidden scenarios vary event payloads, motion delay,
  alarm outcomes, threshold boundaries, resource order, and a faulty XATTR
  processor. These remain state-machine backends rather than native Tango.
- `yaq_fake_motor_sensor_alignment`: native motor and sensor daemons are
  rediscovered under changing resource names; randomized measurements are
  bound to the reported values and argmax position over repeated runs.
- `yaq_fake_spectrometer_triggered_acquisition`: native spectrometer arrays are
  parsed by the evaluator and independently determine point count, peak, and
  integrated counts over repeated runs.

## Remaining Validity Work

The current evaluator establishes deterministic functional correctness against
its hidden worlds. A publication-level claim still requires external evidence:

- independently reviewed manuals, scenarios, safety invariants, and oracles;
- substantially larger parameterized hidden-world families;
- human and multi-model baselines to estimate item difficulty and
  discrimination;
- score/ranking sensitivity analysis for rubric weights and pass thresholds;
- a representative native-framework or real-hardware calibration subset;
- release-time leakage, reproducibility, and repeated-run studies.
