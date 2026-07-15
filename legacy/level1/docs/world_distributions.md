# Parameterized World Distributions

The pilot world-distribution layer turns a simulator template plus a seed and
JSON-pointer patches into the same YAML or JSON file already accepted by the
existing gateways. It does not change the candidate protocol or the v2 check
schema.

The initial pilot covers:

- `pyvisa_dmm_ascii_average`: single-instrument ASCII arrays.
- `pyvisa_scope_binary_waveform`: IEEE definite-length binary blocks.
- `pyvisa_multi_instrument_dut_validation`: a causally coupled multi-instrument
  bench.

Each pilot declares one `core`, one `generalization`, and one `adversarial`
world. `core` varies ordinary identity or observations,
`generalization` varies representation, resource layout, noise, or initial
state, and `adversarial` targets a documented edge condition without changing
the task contract. Group summaries are included in suite reports.

## Spec shape

`world_distribution.version` is currently `1`. Every world has a stable `id`,
one of the three groups, an explicit string `seed`, a template path, an output
simulator path, and optional patches. Patch paths use JSON Pointer syntax.
A patch value may contain `{"choice": [...]}`; selection uses a local PRNG
seeded from SHA-256 of the world seed, so generation does not depend on process
hash randomization or global random state.

Worlds may retain normal `spec_overrides`, `check_overrides`, and
`pass_threshold` fields. The harness projects them into the existing scenario
shape before calling the grader and gateway.

## Materialization

The pilot uses frozen outputs under each evaluation's `worlds/` directory.
Regenerate a distribution with:

```bash
.venv/bin/python -m benchmark_harness freeze-worlds \
  --instance pyvisa/INSTANCE
```

`materialize_world` can also target a temporary directory for runtime
materialization. The output format remains gateway-compatible. CI tests
regenerate all pilot worlds in temporary directories and compare their parsed
content with the checked-in frozen files.

Changing a seed, template, or patch is a benchmark-world change. Regenerate the
frozen output and review both the spec and generated simulator diff together.
