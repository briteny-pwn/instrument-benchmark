# Evaluations

This directory contains hidden scoring and simulator logic. Official runs do
not mount this directory into either the authoring agent or solution runner.

The shared raw-protocol evaluation layer is in `evaluations/common/`:

- `raw_sim_gateway.py`: starts the local TCP JSON-line gateway and connects it
  to the hidden simulator backend.
- `state_machine_gateway.py`: starts the same JSON-line gateway protocol backed
  by a persistent standard-library finite-state simulator. Rules may use
  semantic command regexes, state preconditions, captured-value state updates,
  and staged responses that do not reset when a handle is reopened.
- `coupled_signal_gateway.py`: models a shared source/DUT/measurement signal
  chain so multiple resources affect the same computed observation.
- `linear_sweep_gateway.py`: computes measurement responses from the source's
  actual setpoint, output state, and a hidden transfer function.
- `yaq_native_gateway.py`: starts native hidden `yaqd-fakes` daemons and wraps
  them behind the same JSON-line gateway protocol.
- `raw_trace.py`: records resource, command, query, socket, and cleanup events.
- `import_guard.py`: rejects candidate solutions that import forbidden
  instrument frameworks.
- `grader_core.py`: combines execution, import guard, result checks, simulator
  state checks, trace evidence, ordered milestones, and cleanup scores.

Per-instance evaluations live under:

```text
evaluations/{source}/{instance_id}/
```

Each evaluation provides:

- `spec.json`: expected observations and expected protocol evidence.
- `grader.py`: thin entry point into the common raw grader.
- `reference_solution/`: standard-library-only solution.
- `pyvisa_sim/`: hidden simulator definitions, when pyvisa-sim is used.
- `sim/`: hidden standard-library state-machine scenarios, when used.
  Yaq evaluations also use `sim/` scenario files to configure hidden native
  yaqd-fakes daemons.

The candidate never sees these files during the task. Whether evaluation uses
`pyvisa-sim`, a state-machine simulator, a coupled signal model, or hidden
yaqd-fakes daemons
internally, it exposes only the raw socket protocol described in the
model-visible `simulator_protocol.md`.

## Isolated Execution

`benchmark_harness` separates untrusted execution from deterministic scoring:

- the authoring agent sees only `/workspace` and an unscored materialized
  simulator over an internal network;
- the solution runner sees only read-only `solution.py`, an empty output
  directory, and one hidden simulator endpoint;
- the simulator writes trace and final state to a control volume that is not
  mounted into either candidate container;
- the host grader consumes collected evidence after candidate execution and
  never imports untrusted `solution.py` in the official path.

The per-instance `grader.py` entry points remain available only for trusted
reference development and compatibility. They are not the blind-test entry
point.

Every spec also declares `authoring.base_simulator` and a unique seed. The
simulator container materializes a distinct unscored identity and measurement
world at startup; the three listed `scenarios` remain hidden scoring worlds.

## Backend Status

The EPICS-sourced instances currently use `state_machine_gateway.py`, not native
EPICS runtime components. That means the hidden behavior is inspired by
StreamDevice, asyn, soft IOC record processing, and caproto PV semantics, but
the evaluator does not launch real soft IOCs, asyn ports, StreamDevice protocol
files, or caproto servers yet.

The Tango-sourced instances also currently use `state_machine_gateway.py`, not
native Tango runtime components. The hidden behavior is inspired by Tango device
servers, commands, attributes, states, events, and SimulatorDS dynamic
attributes, but the evaluator does not launch a Tango Database, PyTango device
server, DeviceTestContext, SimulatorDS, or fandango yet.

The Yaq-sourced instances use `yaq_native_gateway.py`. The evaluator launches
native yaqd-fakes daemons and talks to them through an evaluation-only yaq
client, while candidates still interact only with the raw JSON-line protocol.

Future native-backend work is tracked in `TODO.md`.

Scores:

```text
sim_execution
forbidden_api
task_success
instrument_access
protocol_correctness
state_process
safety_and_cleanup
```

## Spec v2

All repository evaluations use `"spec_version": 2` in `spec.json`. These specs
define a diagnostic `rubric`, validity `gates`, hidden `scenarios`, and a list
of deterministic `checks`:

- `result_json`: compare candidate output with expected fields/ranges.
- `sim_state`: compare hidden final simulator state with expected state.
- `result_sim_state_binding`: bind a reported value directly to hidden backend
  state without copying scenario-specific answers into the spec.
- `trace_coverage`: verify important raw protocol evidence without requiring an
  exact reference trace.
- `ordered_milestones`: verify experimental phase order with partial credit.
- `causal_order`: verify pairwise before/after constraints when independent
  prerequisite checks may occur in either order; `first` and `last` occurrence
  selection can distinguish initial and final observations.
- `anti_hardcode`: require evidence of real simulator interaction.
- `cleanup`: verify handle/socket cleanup.

The report includes `pass`, `evidence`, `result`, `trace`, and `sim_state`.
Legacy specs remain readable for compatibility, but no current instance relies
on the legacy scoring path.

### Hidden Scenario Suites

A v2 spec may define `scenarios`. The grader reloads and reruns the candidate
against every hidden simulator scenario, then reports per-scenario evidence,
pass rate, and a separate `robustness` score. Scenario variation should target
resource identity, initial state, measured data, timing, or recoverable errors.
`suite.repetitions` repeats each randomized scenario in a fresh gateway/backend
process and includes every run in the reported pass rate.

Additional deterministic checks are available:

- `result_trace_binding`: bind a reported resource or identifier to an observed
  gateway event.
- `trace_numeric_aggregate`: independently reconstruct numeric observations
  from hidden responses and verify candidate-reported statistics.
- `trace_numeric_array`: parse an instrument's delimited numeric response and
  independently verify the reported values, count, and derived statistics.
- `trace_string_array`: bind monitor/event history to the actual response
  sequence.
- `trace_xy_spectrum`: parse hidden X/Y arrays and independently recompute point
  count, peak coordinates, peak value, and integrated signal.
- `trace_ieee_block`: decode an IEEE definite-length binary block from the
  hidden response and verify raw codes, scaled samples, and waveform statistics.
- `trace_command_numeric_array`: parse a numeric array embedded in a write
  command and bind the uploaded values to both task inputs and candidate output.
- `trace_response`: bind a reported scalar or state to the actual query
  response, with string, numeric, or ON/OFF parsing. A check may explicitly
  accept either the raw response or its parsed value when an older output
  contract left that representation ambiguous.
- `result_pairwise_max_abs_error`: independently recompute the maximum
  pointwise disagreement between two reported arrays after those arrays are
  bound to instrument responses.
- `result_pairwise_differences`: independently recompute every pointwise error.
- `result_linear_fit`: independently fit slope and intercept from reported
  sweep arrays after the measured array is bound to trace responses.
- `result_endpoint_slope`: recompute the documented endpoint slope from bound
  arrays.
- `result_argmax_x`: bind a reported optimum position to the maximum observed
  signal.
- `result_mean_deviation_validation`: cross-check a multi-device processor
  against statistics independently derived from sensor observations.
- `result_threshold_decision`: recompute a reported pass/fail decision from
  documented equality, range, limit, and tolerance conditions.
- `sim_state_all`: apply one final-state expectation to every hidden resource.

Scenario-suite reports include overall and per-scenario score dispersion,
normal-approximate mean-score intervals, and Wilson 95% pass-rate intervals.
These statistics describe the executed hidden suite; heterogeneous scenarios
must not be treated as independent samples from an unspecified population.

`gates` turn essential checks or dimensions into pass requirements. This keeps
a high weighted total from compensating for fake access, a wrong oracle result,
an unsafe final state, or missing cleanup.

The weighted total is diagnostic rather than a substitute for functional
success: every current instance gates genuine access, its independent result
oracle, required safety/process invariants, and cleanup. Repository-level
comparisons should report instance/scenario pass rates alongside mean scores.

For pyvisa-sim backends, `snapshot_queries` may query hidden device properties
after candidate execution. These queries are not added to candidate trace and
can verify persisted configuration or safe final state independently of the
candidate report.

`intercepted_write_patterns` can model payload-bearing command families that
pyvisa-sim cannot represent as variable-length properties. The original command
remains in trace and is evaluated semantically. `write_rewrites` may normalize
documented equivalent numeric formats before they reach a stricter backend.

The full construction and credibility policy is documented in
`docs/benchmark_credibility.md`.

Run all hidden reference solutions with:

```text
.venv/bin/python -m evaluations.run_reference_suite
```

Run representative anti-cheating and safety failures with:

```text
.venv/bin/python -m evaluations.run_negative_suite
```
