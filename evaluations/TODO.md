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

- [ ] Add a small command to run every reference solution and summarize totals.
- [ ] Add CI-friendly negative case checks for forbidden imports and missing
  cleanup.
- [ ] Add optional per-instance metadata describing whether the hidden backend is
  `pyvisa_sim`, `state_machine`, or a future native framework backend.
