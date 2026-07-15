# Tango Source Notes

The `tango` source uses Tango Controls and SimulatorDS ideas as source material
for from-scratch raw protocol tasks.

The candidate does not use Tango libraries directly. Current hidden evaluations
model Tango-style behavior with a standard-library finite-state gateway:

- device identity and hierarchy;
- commands for actions;
- attributes for read/write physical or computed quantities;
- properties as configuration concepts;
- device states and status strings;
- event-like acquisition histories;
- SimulatorDS dynamic attributes, dynamic states, and cross-attribute formulas.

This is not a native Tango runtime today: no Tango Database, PyTango device
server, DeviceTestContext, SimulatorDS, or fandango process is launched by these
instances. Native evaluation backends can be added later while keeping the same
candidate-facing raw socket boundary.

Reference materials:

- Tango Controls: device-oriented open source controls toolkit.
- Tango device model: devices expose commands, attributes, and properties.
- Tango communication paradigms: synchronous, asynchronous, and
  publish-subscribe/event communication.
- SimulatorDS: PyTango device server for simulation/testing, dynamic
  attributes, dynamic states, dynamic commands, and replayable mockups.
