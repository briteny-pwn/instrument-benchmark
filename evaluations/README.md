# Evaluations

This directory contains hidden or external scoring logic.

The shared raw-protocol evaluation layer is in `evaluations/common/`:

- `raw_sim_gateway.py`: starts the local TCP JSON-line gateway and connects it
  to the hidden simulator backend.
- `raw_trace.py`: records resource, command, query, socket, and cleanup events.
- `import_guard.py`: rejects candidate solutions that import forbidden
  instrument frameworks.
- `grader_core.py`: combines execution, import guard, trace, state transition,
  observation, and cleanup scores.

Per-instance evaluations live under:

```text
evaluations/{source}/{instance_id}/
```

Each evaluation provides:

- `spec.json`: expected observations and expected protocol evidence.
- `grader.py`: thin entry point into the common raw grader.
- `reference_solution/`: standard-library-only solution.
- `pyvisa_sim/`: hidden simulator definitions, when pyvisa-sim is used.

The candidate never sees these files during the task. Even when `pyvisa-sim` is
used internally, evaluation exposes only the raw socket protocol described in
the model-visible `simulator_protocol.md`.

Scores:

```text
sim_execution
forbidden_api
interface_implementation
protocol_trace
state_transition
observation
cleanup
```
