# EPICS Source Notes

The `epics` source uses EPICS StreamDevice, asyn, soft IOC, and caproto ideas as
source material for from-scratch raw protocol tasks.

The candidate does not use EPICS libraries directly. Current hidden evaluations
model EPICS-style behavior with a standard-library finite-state gateway, such as
StreamDevice protocol parsing, asyn-style addressed byte streams, soft IOC
record processing, or caproto-like PV put/readback semantics. The model-visible
task remains a manual plus a raw socket simulator protocol.

This is not a native EPICS runtime today: no real soft IOC, StreamDevice/asyn
stack, or caproto IOC is launched by these instances. Native evaluation
backends can be added later while keeping the same candidate-facing raw socket
boundary.

Reference materials:

- StreamDevice: byte-stream device support configured by protocol files.
- asyn: asynchronous device support and low-level communication abstraction.
- EPICS process database: records, fields, scans, links, alarms, and processing
  chains.
- caproto: pure Python Channel Access and IOC tooling used as behavioral
  inspiration for PV bridge tasks.
