# PyVISA Source

The `pyvisa` source family uses PyVISA and pyvisa-sim as material for creating
instrument simulations and SCPI-style protocol tasks.

For benchmark candidates, PyVISA is not available and must not be imported.
The candidate sees only:

- an instrument command manual;
- the raw simulator JSON-line socket protocol;
- an experiment objective and result format.

Hidden evaluation may use `pyvisa-sim` internally, wrapped by
`evaluations/common/raw_sim_gateway.py`. The gateway records raw socket,
resource, command, query, and cleanup evidence.

This source family is useful for:

- resource discovery tasks;
- text command write/query workflows;
- ASCII numeric data transfer;
- IEEE binary block decoding;
- multi-instrument coordination.
