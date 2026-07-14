# Tango Evaluations

These evaluations use Tango Controls and SimulatorDS behavior as source
material while preserving the benchmark rule that candidates implement the
instrument interface from scratch.

The hidden simulator is the shared state-machine gateway in
`evaluations/common/state_machine_gateway.py`; candidates see only the JSON-line
raw socket protocol.
