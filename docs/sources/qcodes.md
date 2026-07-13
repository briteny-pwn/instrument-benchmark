# QCoDeS Source

The `qcodes` source family uses QCoDeS and qcodes_contrib_drivers as inspiration
for realistic station, parameter, sweep, and measurement workflows.

For benchmark candidates, QCoDeS is not available and must not be imported. A
QCoDeS-sourced instance should translate the station/driver idea into raw
instrument protocols that the candidate implements from scratch.

The candidate sees only:

- instrument command manuals;
- the raw simulator JSON-line socket protocol;
- an experiment objective and result format.

This source family is useful for tasks that preserve QCoDeS-like experimental
structure, such as source-meter sweeps or station validation, while still
testing low-level instrument interface implementation.
