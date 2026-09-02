# Distributed Contract Version 2

The orchestrator validates the instance and evaluator manifests, hashes every
candidate-visible instance file, records all three repository commit IDs, and
then invokes:

```text
python -m instrument_benchmark_evaluator.cli run
  --request <absolute JSON path>
  --report <absolute JSON path>
```

The request identifies `source_id`, `instance_id`, `evaluator_id`, the run,
candidate, protocol version, limits, and repeated-world seed range. The
composite run binding is `(source_id, instance_id, evaluator_id)`. Exit status
`0` means an evaluator report was
produced; candidate failures remain normal report outcomes. Exit status `2`
means an incompatible or invalid request. Any other status is evaluator
infrastructure failure.

Run YAML uses schema version 3. Repository locations are not YAML fields:
`INSTANCES_REPO_PATH` and `EVALUATOR_REPO_PATH` must be absolute existing
directories. The process environment has priority over the optional
repository-root `.env` file. A relative `candidate_path` is evaluator-root
relative and cannot escape that repository; an absolute path selects an
external candidate. These run-config rules are independent of the evaluator
request protocol version named by this document.

Instance and evaluator leaves resolve only at
`sources/<source_id>/<leaf_id>/`, after their source registries and schema-v2
manifests agree. Source-grouped config and report paths are also mandatory.
Legacy ungrouped paths are invalid and no compatibility fallback, alias,
search, or root-manifest lookup exists.

The evaluator owns raw evidence, worlds, oracle, scoring, and safety gates. The
orchestrator validates but never changes the evaluator score. It adds:

- `run_id`;
- instrument, instance, and evaluator Git provenance;
- orchestration protocol and evaluator exit status.

## Independent runtime profiles

The three repositories define the benchmark distribution boundary, not a
shared instrument inheritance hierarchy. Each instance declares its own task
type, evaluator, public API, image lock, report schema, and optional external
source inputs. `fibsem_liftout_v1` therefore selects the evaluator-owned
`$EVALUATOR_REPO_PATH/container/fibsem-evaluator.Dockerfile`, OpenFIBSEM
wheel/system-package locks, and pinned OpenFIBSEM source tree without staging
the PyVISA lock or wheelhouse. The evaluator CLI also imports PyVISA
implementations lazily, so the FIBSEM route can start when `pyvisa` is absent.

For `fibsem_liftout_v1`, the request binds the exact evaluator image ID and the
external source commit. The evaluator runs one public nominal world, four
hidden fixed worlds, and five deterministic seeded worlds. At each of
`step_1` through `step_4`, it freezes the simulator before exporting the
trusted scene. The final schema-version-5 report binds source identity, journal heads,
connectivity/pose metrics, artifact hashes, sibling container evidence,
cleanup state, all three repository commits, and OpenFIBSEM commit/source
digest. The operator validator is:

```bash
PYTHONPATH=src "$EVALUATOR_REPO_PATH/scripts/validate_fibsem_benchmark.py" \
  --instrument-root "$PWD" \
  --config "$PWD/configs/openfibsem/fibsem_liftout_v1.yaml"
"$EVALUATOR_REPO_PATH/scripts/run_fibsem_linux_acceptance.sh" \
  "$PWD/configs/openfibsem/fibsem_liftout_v1.yaml"
```

The validated output is
`reports/openfibsem/fibsem_liftout_v1.json`, with checkpoint bundles below
`reports/openfibsem/fibsem_liftout_v1.artifacts/{world_id}/{step_id}/`.
PyVISA v1 and v2 reports use top-level schema versions 2 and 3, respectively.

Native Linux Docker is required because the non-root outer evaluator receives
daemon access only through the Docker socket group GID. Docker Desktop socket
ownership is not relaxed or bypassed. A simulator/import/export failure is an
infrastructure retry; a missing state, invalid order, unsafe terminal state,
or forbidden access is a candidate failure. Results do not transfer physical
hardware authority or safety.
