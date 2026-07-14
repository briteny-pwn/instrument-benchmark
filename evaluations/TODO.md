# Evaluation Backend TODO

This file tracks evaluator-side work only. It should not be copied into
`instances/` or exposed as model-visible task context.

## EPICS Native Backend Roadmap

- [ ] Add a `caproto_gateway.py` hidden backend for caproto-style instances.
  The gateway should launch a caproto IOC/server internally, interact with it
  through a hidden client, and continue exposing only the existing JSON-line raw
  socket protocol to candidates.
- [ ] Add negative tests proving candidates that import `caproto`, `epics`,
  `pyepics`, `pcaspy`, or `softioc` still fail even when evaluation uses those
  packages internally.
- [ ] Define a native-backend spec shape, for example
  `"gateway": "caproto"` plus a hidden IOC scenario file, without changing the
  candidate `solution.py` contract.
- [ ] Prototype one native caproto version of
  `epics_caproto_pv_bridge_scan` and compare its trace/result behavior against
  the current state-machine scenario.
- [ ] Investigate a real `softIoc` backend that can load generated `.db` files
  under evaluation control, with deterministic process startup, PV namespace
  isolation, timeout handling, and cleanup.
- [ ] Investigate a StreamDevice/asyn backend only after soft IOC is reliable:
  it will need EPICS Base, asyn, StreamDevice, `.db`, `.proto`, `st.cmd`, and a
  separate low-level TCP/serial device simulator.
- [ ] Document environment requirements for any native backend separately from
  the default lightweight benchmark path.
- [ ] Keep `state_machine_gateway.py` as the portable baseline backend even
  after native EPICS backends are added.

## General Evaluation Improvements

- [x] Add `python -m evaluations.run_reference_suite` to run every reference
  solution and summarize totals.
- [x] Add `python -m evaluations.run_negative_suite` for forbidden imports,
  hardcoded results, unsafe final state, and fixed ASCII/binary observations.
- [ ] Add a deterministic missing-cleanup fixture whose socket lifetime is not
  affected by interpreter reference counting.
- [ ] Add optional per-instance metadata describing whether the hidden backend is
  `pyvisa_sim`, `state_machine`, or a future native framework backend.
- [x] Migrate all remaining legacy specs to `spec_version: 2` checks and
  rubrics.
- [x] Migrate `pyvisa_dc_power_supply_basic` to hidden device variants,
  backend-state snapshot queries, a measurement oracle, and an output-off
  safety gate.
- [x] Migrate `pyvisa_dmm_ascii_average` to hidden ASCII datasets, including
  signed/scientific values, array-derived statistics, configuration snapshots,
  and mandatory trace-buffer cleanup.
- [x] Migrate `pyvisa_scope_binary_waveform` to variable-length IEEE blocks,
  including a two-digit payload length, hidden waveform/statistics oracle, and
  preamble configuration snapshots.
- [x] Migrate `pyvisa_awg_ascii_upload` to semantic upload validation, hidden
  resource/initial-state variants, persisted amplitude/frequency checks, output
  response binding, and final output-off safety.
- [x] Migrate `pyvisa_mixed_signal_calibration` to three hidden multi-instrument
  scenarios, source-state measurement guards, independent DMM/scope response
  oracles, pass/fail decision reconstruction, and final AWG output-off safety.
- [x] Migrate `pyvisa_resource_discovery_idn` to TCPIP/GPIB/USB hidden
  topologies, dynamic measurements, identity-response binding, explicit
  communication-parameter evidence, and fixed-address rejection.
- [x] Migrate `qcodes_station_sweep_basic` to a coupled source/DMM transfer
  model with hidden resource/noise/failure scenarios, independent fit and
  decision reconstruction, actual-vs-requested setpoint evidence, and output
  safety cleanup.
- [x] Migrate `pyvisa_multi_instrument_dut_validation` to a coupled source/DUT/
  measurement model so downstream observations change with PSU, switch, and
  AWG state rather than relying only on command-history guards.
- [x] Add hidden multi-scenario execution with pass-rate and robustness
  reporting. `yaq_fake_sensor_stability_scan` is the first migrated instance.
- [x] Add repeated execution within randomized scenarios through
  `suite.repetitions`.
- [x] Add score variance and confidence intervals to repeated-run reports,
  including per-scenario summaries and Wilson pass-rate intervals.
- [ ] Expand dedicated unit tests to every v2 check type. Core scenario,
  independent numeric oracle, empty-trace, and hard-gate behavior are covered.
- [x] Migrate measured-value output examples to placeholders across all visible
  prompts so prompts specify schemas without revealing fixed simulator answers.
- [x] Migrate all EPICS and Tango instances to persistent-state, multi-scenario
  v2 evaluation with independent result oracles and required gates.
- [x] Migrate the remaining yaq motor/sensor and spectrometer tasks to repeated
  native scenarios, trace-bound observations, and required gates.
- [ ] Replace hand-authored three-world suites with parameterized scenario
  generators for selected instances and document the sampling population.
- [ ] Run human and multi-model baselines, then report item pass rate,
  discrimination, failure categories, and repeated-run variance.
- [ ] Perform rubric-weight and pass-threshold sensitivity analysis; verify that
  headline model rankings are not artifacts of arbitrary weights.
- [ ] Arrange independent domain-expert review of manuals, safety invariants,
  hidden scenarios, and result oracles.
- [ ] Calibrate a representative subset against native framework simulators or
  real instrument traces/hardware and publish the observed transfer gap.

## Candidate Lightweight Ecosystem Roadmap

- [x] Investigate `yaq` / `yaqd-fakes` as the next high-value source family.
  It is lightweight compared with EPICS/Tango, uses daemon-style instrument
  components, and has fake daemons for cameras, sensors, spectrometers,
  furnaces, motors, and other devices.
- [x] Define a `yaq` source strategy where evaluation may launch native
  `yaqd-fakes` internally, but candidates still see only the existing
  JSON-line raw socket gateway and must write their own standard-library
  client code.
- [x] Prototype one `yaq` multi-daemon instance covering non-blocking motion,
  trait-like position/sensor semantics, state polling, and coordinated
  acquisition.
- [ ] Investigate `Python Microscope` as a microscopy/optics source family.
  Its simulated camera, filter wheel, and device-server architecture can support
  high-difficulty imaging tasks without a facility-scale control stack.
- [ ] Define a `microscope` source strategy where native simulated devices may
  run hidden behind the gateway, while candidates do not import `microscope` or
  `Pyro4`.
- [ ] Prototype one `microscope` instance combining camera exposure, laser
  enable/power control, filter wheel position, stage movement, image/frame
  parsing, and cleanup.
- [ ] Investigate `ophyd` plus `caproto` simulated hardware as a focused source
  for asynchronous scan/status/monitor semantics. Treat it as related to, but
  separate from, the existing EPICS instances.
- [ ] Define an `ophyd` source strategy where hidden evaluation may use caproto
  simulated PVs or ophyd-style behavior, but candidates do not import `ophyd`,
  `bluesky`, `caproto`, `epics`, or `pyepics`.
- [ ] Prototype one `ophyd` instance covering set/read separation, timeout-aware
  status completion, monitor-like value history, and multi-signal scan results.
- [ ] Add native-backend hardening for `yaq_native_gateway.py`: deterministic
  port management, subprocess stderr surfacing on failure, and stress tests for
  repeated start/stop cycles.
- [ ] For remaining lightweight ecosystems, add source notes under
  `docs/sources/`, update root/source READMEs, extend forbidden-import negative
  cases, and keep `state_machine_gateway.py` as the portable baseline until
  native hidden backends are proven reliable.

## Tango Native Backend Roadmap

- [ ] Add a native PyTango backend feasibility check using
  `tango.test_context.DeviceTestContext` or `MultiDeviceTestContext` without a
  full Tango Database where possible.
- [ ] Add negative tests proving candidates that import `tango`, `PyTango`,
  `pytango`, `taurus`, `sardana`, or `fandango` still fail even when evaluation
  uses those packages internally.
- [ ] Define a native-backend spec shape, for example `"gateway": "pytango"` or
  `"gateway": "simulatords"` plus hidden device/server scenario files, without
  changing the candidate `solution.py` contract.
- [ ] Prototype one native PyTango version of
  `tango_motor_attribute_command_scan` and compare its trace/result behavior
  against the current state-machine scenario.
- [ ] Prototype one native SimulatorDS/fandango version of
  `tango_simulatords_dynamic_temperature_alarm`, including dynamic attributes
  and dynamic states.
- [ ] Investigate a full Tango facility backend only after DeviceTestContext is
  reliable: it will need Tango Database, MySQL/MariaDB or a database-free
  equivalent, device server startup, namespace isolation, timeout handling, and
  cleanup.
- [ ] Keep `state_machine_gateway.py` as the portable baseline backend even
  after native Tango backends are added.
