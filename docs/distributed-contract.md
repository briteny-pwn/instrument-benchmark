# Distributed Contract Version 1

The orchestrator validates the instance and evaluator manifests, hashes every
candidate-visible instance file, records all three repository commit IDs, and
then invokes:

```text
python -m instrument_benchmark_evaluator.cli run
  --request <absolute JSON path>
  --report <absolute JSON path>
```

The request identifies the run, instance, candidate, protocol version, limits,
and repeated-world seed range. Exit status `0` means an evaluator report was
produced; candidate failures remain normal report outcomes. Exit status `2`
means an incompatible or invalid request. Any other status is evaluator
infrastructure failure.

The evaluator owns raw evidence, worlds, oracle, scoring, and safety gates. The
orchestrator validates but never changes the evaluator score. It adds:

- `run_id`;
- instrument, instance, and evaluator Git provenance;
- orchestration protocol and evaluator exit status.

## Independent runtime profiles

The three repositories define the benchmark distribution boundary, not a
shared instrument inheritance hierarchy. Each instance declares its own task
type, evaluator, public API, image lock, report schema, and optional external
source inputs. `fibsem_liftout_v1` therefore selects
`container/fibsem-evaluator.Dockerfile`, the OpenFIBSEM wheel/system-package
locks, and the pinned OpenFIBSEM source tree without staging the PyVISA lock or
wheelhouse. The evaluator CLI also imports PyVISA implementations lazily, so
the FIBSEM route can start when `pyvisa` is absent.

For `fibsem_liftout_v1`, the request binds the exact evaluator image ID and the
external source commit. The evaluator runs one public nominal world, four
hidden fixed worlds, and five deterministic seeded worlds. At each of
`step_1` through `step_4`, it freezes the simulator before exporting the
trusted scene. The final schema-version-3 report binds journal heads,
connectivity/pose metrics, artifact hashes, sibling container evidence,
cleanup state, all three repository commits, and OpenFIBSEM commit/source
digest. The operator validator is:

```bash
python scripts/validate_fibsem_benchmark.py --config configs/fibsem_liftout_v1.yaml
```

Native Linux Docker is required because the non-root outer evaluator receives
daemon access only through the Docker socket group GID. Docker Desktop socket
ownership is not relaxed or bypassed. A simulator/import/export failure is an
infrastructure retry; a missing state, invalid order, unsafe terminal state,
or forbidden access is a candidate failure. Results do not transfer physical
hardware authority or safety.
