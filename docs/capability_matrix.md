# Instance Capability Matrix

The canonical machine-readable source for this matrix is
`evaluations/registry.json`. `InstanceManifest` and its validator live in
`evaluations/common/instance_manifest.py`; this page is the review-oriented
summary, not a second metadata source.

Backend fidelity levels:

- `native`: the hidden evaluator runs the source ecosystem's simulator.
- `ecosystem`: an ecosystem simulator runs behind the raw gateway.
- `behavioral`: a benchmark-owned state or signal model emulates the behavior.

Capability abbreviations are `RD` resource discovery, `ID` identity, `CFG`
configuration, `AP` ASCII parsing, `BP` binary parsing, `ARR` array
acquisition, `MULTI` multi-instrument coordination, `POLL` state polling,
`EVENT` event acquisition, `NUM` numeric analysis, `DEC` decision logic, and
`SAFE` safety/cleanup.

| Source / instance | Capabilities | Backend fidelity | Principal scenario variation | Safety invariant |
| --- | --- | --- | --- | --- |
| pyvisa / pyvisa_dc_power_supply_basic | RD, ID, CFG, NUM, SAFE | ecosystem / pyvisa_sim | resource, measurement | output off |
| pyvisa / pyvisa_dmm_ascii_average | RD, ID, CFG, AP, ARR, NUM, SAFE | ecosystem / pyvisa_sim | resource, numeric format, samples | buffer cleared |
| pyvisa / pyvisa_scope_binary_waveform | RD, ID, CFG, BP, ARR, NUM, SAFE | ecosystem / pyvisa_sim | resource, block length, waveform | cleanup |
| pyvisa / pyvisa_awg_ascii_upload | RD, ID, CFG, AP, ARR, SAFE | ecosystem / pyvisa_sim | resource, initial state | output off |
| pyvisa / pyvisa_resource_discovery_idn | RD, ID, CFG, AP, NUM, SAFE | ecosystem / pyvisa_sim | transport, identity, measurement | cleanup |
| pyvisa / pyvisa_mixed_signal_calibration | RD, ID, CFG, AP, BP, ARR, MULTI, NUM, DEC, SAFE | ecosystem / pyvisa_sim | resources, observations, failure | AWG off |
| pyvisa / pyvisa_multi_instrument_dut_validation | RD, ID, CFG, AP, BP, ARR, MULTI, NUM, DEC, SAFE | behavioral / coupled_signal | resources, noise, DUT gain | sources off; routes open |
| qcodes / qcodes_station_sweep_basic | RD, ID, CFG, ARR, MULTI, NUM, DEC, SAFE | behavioral / linear_sweep | resources, transfer, noise | source off |
| epics / epics_streamdevice_temperature_loop | RD, ID, CFG, AP, POLL, ARR, NUM, SAFE | behavioral / state_machine | ramp, overshoot, polling | cleanup |
| epics / epics_asyn_serial_pump_interlock | RD, ID, CFG, AP, POLL, NUM, SAFE | behavioral / state_machine | pressure, retries, timing | interlock ordering |
| epics / epics_softioc_record_chain_ramp | RD, ID, CFG, ARR, NUM, DEC, SAFE | behavioral / state_machine | gain, alarm, readback | source off |
| epics / epics_caproto_pv_bridge_scan | RD, ID, CFG, ARR, EVENT, NUM, SAFE | behavioral / state_machine | readback, detector, events | cleanup |
| tango / tango_simulatords_dynamic_temperature_alarm | RD, ID, CFG, POLL, ARR, DEC, SAFE | behavioral / state_machine | temperature, threshold, alarm | cleanup |
| tango / tango_motor_attribute_command_scan | RD, ID, CFG, POLL, ARR, NUM, SAFE | behavioral / state_machine | delay, resource, readback | motor stopped |
| tango / tango_simulatords_xattr_average_processor | RD, CFG, MULTI, ARR, NUM, DEC, SAFE | behavioral / state_machine | sensors, processor fault | cleanup |
| tango / tango_event_like_detector_acquisition | RD, ID, CFG, EVENT, ARR, NUM, SAFE | behavioral / state_machine | event payload, signal, timing | cleanup |
| yaq / yaq_fake_sensor_stability_scan | RD, ID, ARR, NUM, DEC, SAFE | native / yaq_native | resource, signal distribution | sensor idle |
| yaq / yaq_fake_motor_sensor_alignment | RD, ID, CFG, POLL, ARR, MULTI, NUM, SAFE | native / yaq_native | resources, peak, motion | cleanup |
| yaq / yaq_fake_spectrometer_triggered_acquisition | RD, ID, CFG, POLL, ARR, NUM, SAFE | native / yaq_native | resource, spectrum | spectrometer idle |

Every row has at least three hidden worlds. The registry additionally records
task inputs, independently observable outputs, oracle-to-output bindings,
difficulty factors, and the explicit public-constant allowlist.

## Boundary Contract

`prompt.md` remains the public output contract. Registry task-input and
observable-output JSON paths must name fields in that prompt, while every
observable output must bind to an independent hidden check in `spec.json`.
Safety invariants must bind hidden checks and always include connection cleanup.

Authoring uses a seeded deterministic materialization written outside the
evaluation tree. Existing v2 specs may share a source template with one hidden
world for compatibility, but the materialized authoring bytes are unscored and
must differ from the source template; hidden scenario files, checks, and oracle
bindings are never copied into the authoring workspace.
