# Distributed Benchmark Completion Audit

Evidence is recorded in `reports/distributed_validation.json`.

## Repository topology

- [x] Root contains independent sibling `instrument/`, `instance/`, and
  `evaluator/` Git repositories.
- [x] Instrument uses
  `briteny-pwn/instrument-benchmark:distributed-model`.
- [x] Instance uses `briteny-pwn/instrument-benchmark-instances:main`.
- [x] Evaluator uses `briteny-pwn/instrument-benchmark-evaluator:main`.
- [x] Existing `refactor/iab-sim-mvp` history remains untouched as a migration
  source.

## Boundaries

- [x] Instrument contains generic configuration, compatibility, invocation,
  provenance, and report logic only.
- [x] Instance contains only model-visible prompt, controlled manuals,
  transport, starter, result schema, and hashed manifest.
- [x] Evaluator contains PyVISA/pyvisa-sim, DUT world, instruments, gateway,
  isolation, worlds, oracle, scoring, reference, and adversarial evidence.
- [x] Instrument does not source-import evaluator.
- [x] Evaluator does not source-import instrument or the real instance checkout.
- [x] Candidate workspace is populated only from instance `visible_files`.

## Contracts and reproducibility

- [x] Instance and evaluator IDs and protocol versions are checked.
- [x] Every candidate-visible file is verified by SHA-256.
- [x] Clean checkout policy is the default.
- [x] Final report records exact instrument, instance, and evaluator commits.
- [x] Evaluator is invoked through versioned JSON/CLI with exit statuses 0/2/3.
- [x] Candidate outcomes remain report outcomes rather than infrastructure exit
  statuses.

## Capability evidence

- [x] Five simulated instruments share one persistent causal DUT world.
- [x] Agent must discover resources and build SCPI handling from included docs.
- [x] Causal partial order permits commuting DMM/scope operations.
- [x] Per-device connection/configuration/acquisition/close evidence is emitted.
- [x] Experiment completion and safe final state are independently reported.
- [x] Capability score and evidence confidence remain separate.
- [x] Nine fixed and ten repeated hidden worlds are evaluated.
- [x] Eleven targeted adversarial cases map to expected failed gates.

## Fresh validation

- [x] Instance tests: 5 passed.
- [x] Evaluator CLI tests: 4 passed.
- [x] Evaluator instrument/evidence/scoring tests: 38 passed.
- [x] Instrument orchestration tests: 5 passed.
- [x] Fixed-world pass rate: 1.0.
- [x] Repeated-world pass rate: 1.0.
- [x] Strict pass: true.
- [x] Reference score: 100.
- [x] World count: 19.
- [x] Two clean evaluator runs are semantically reproducible.

## Declared limits

- Simulation success does not prove transfer to physical instruments.
- Production ranking should add an OS-level sandbox around the candidate
  process in addition to the Python audit boundary.
