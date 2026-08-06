# Multi-Source Repository Architecture Design

**Status:** Approved for planning on 2026-08-07

## Problem

The benchmark currently stores instance leaves directly at the root of the
`instance` repository and evaluator leaves under a single flat `evaluators/`
directory. The manifests contain a `source_family` field, but source is not a
first-class routing key. The instrument orchestrator resolves an instance as
either `<checkout>/<instance_id>` or the checkout itself, and evaluator
dispatch is keyed primarily by `instance_id`.

That layout does not model the real ownership relationship: the benchmark has
multiple independent sources, and each source can publish multiple instances
and multiple evaluators. It also prevents two sources from safely using the
same leaf identifier and allows compatibility fallbacks to hide incorrect
paths.

## Goals

1. Make `source_id` the first component of every instance and evaluator
   identity.
2. Organize both repositories as `sources/<source_id>/<leaf_id>/`.
3. Give every source a local authoritative `source.yaml` registry.
4. Route instrument configs and reports by source.
5. Resolve all paths explicitly from `(source_id, leaf_id)` without scanning,
   symlinks, aliases, or legacy fallbacks.
6. Preserve candidate behavior, scoring semantics, public APIs, image locks,
   and FIBSEM four-step workflow behavior.
7. Re-run local and native-Linux Docker acceptance for every existing source.

## Non-Goals

- PyVISA is not a base class or comparison point for other sources.
- This migration does not merge evaluator implementations across sources.
- It does not change the FIBSEM operation API, necessary partial order,
  tolerance formulas, scoring weights, world definitions, or checkpoint
  artifacts.
- It does not change candidate result schemas or candidate container protocol
  version 1.
- It does not add a root-level central catalog. Each source directory is a
  self-contained registration unit.
- It does not retain the old flat layout through symlinks, wrappers, directory
  searches, or compatibility fallbacks.

## Identity Model

The canonical keys are:

- source: `source_id`
- instance: `(source_id, instance_id)`
- evaluator: `(source_id, evaluator_id)`
- run binding: `(source_id, instance_id, evaluator_id)`

All IDs must match `^[a-z][a-z0-9_-]*$`. An ID is a single path component; an
absolute value, dot component, slash, backslash, or traversal component is
invalid. Different sources may reuse the same `instance_id` or `evaluator_id`.
Within one source, each list is unique.

The existing sources are:

- `pyvisa`
- `openfibsem`

## Repository Layout

### Instance repository

```text
instance/
├── schemas/
│   ├── source.schema.json
│   └── instance.schema.json
├── sources/
│   ├── __init__.py
│   ├── pyvisa/
│   │   ├── __init__.py
│   │   ├── source.yaml
│   │   ├── pyvisa_dut_validation_v1/
│   │   │   └── instance.yaml
│   │   └── pyvisa_dut_validation_v2/
│   │       └── instance.yaml
│   └── openfibsem/
│       ├── __init__.py
│       ├── source.yaml
│       └── fibsem_liftout_v1/
│           └── instance.yaml
├── tests/
└── README.md
```

The complete existing contents of each instance leaf move with the leaf. Paths
inside a leaf, including `visible_files`, `context_files`, candidate packages,
manuals, scenarios, and runtime locks, remain relative to that leaf.
Repository-only imports use `sources.<source_id>.<instance_id>` where a leaf is
a Python package. Candidate workspaces still receive only the selected leaf's
declared visible files, so the source registry itself is not candidate-visible.

### Evaluator repository

```text
evaluator/
├── instrument_benchmark_evaluator/
├── schemas/
│   └── source.schema.json
├── sources/
│   ├── __init__.py
│   ├── pyvisa/
│   │   ├── __init__.py
│   │   ├── source.yaml
│   │   ├── pyvisa_dut_validation_v1/
│   │   │   ├── __init__.py
│   │   │   └── evaluator.yaml
│   │   └── pyvisa_dut_validation_v2/
│   │       ├── __init__.py
│   │       └── evaluator.yaml
│   └── openfibsem/
│       ├── __init__.py
│       ├── source.yaml
│       └── fibsem_liftout_v1/
│           ├── __init__.py
│           └── evaluator.yaml
├── tests/
└── README.md
```

The generic evaluator runtime remains in `instrument_benchmark_evaluator/`.
Source implementation imports use the explicit namespace
`sources.<source_id>.<evaluator_id>`. The old `evaluators.*` namespace and root
`evaluator.yaml` fallback are removed.

### Instrument repository

```text
instrument/
├── configs/
│   ├── pyvisa/
│   │   ├── pyvisa_dut_validation_v1.yaml
│   │   └── pyvisa_dut_validation_v2.yaml
│   └── openfibsem/
│       └── fibsem_liftout_v1.yaml
├── reports/
│   ├── pyvisa/
│   │   ├── pyvisa_dut_validation_v1.json
│   │   └── pyvisa_dut_validation_v2.json
│   └── openfibsem/
│       ├── fibsem_liftout_v1.json
│       └── fibsem_liftout_v1.artifacts/
├── src/instrument_benchmark/
└── scripts/
```

Generic instrument code remains organized by responsibility rather than by
source. Source-specific configuration and published evidence are grouped by
source.

## Source Registries

Each source directory contains exactly one `source.yaml`. The instance and
evaluator repositories use separate schemas because they register different
leaf kinds.

Instance source manifest:

```yaml
schema_version: 1
source_id: openfibsem
display_name: OpenFIBSEM
description: FIB-SEM simulation tasks
instances:
  - fibsem_liftout_v1
```

Evaluator source manifest:

```yaml
schema_version: 1
source_id: openfibsem
display_name: OpenFIBSEM
description: Trusted FIB-SEM evaluators
evaluators:
  - fibsem_liftout_v1
```

Both source schemas use `additionalProperties: false`. They require
`schema_version`, `source_id`, `display_name`, `description`, and the
repository-specific leaf list. `display_name` and `description` are non-empty
strings. Lists contain unique valid IDs and are lexically sorted by repository
tests.

Repository tests enforce both directions:

- every registered ID has exactly one matching leaf directory and manifest;
- every leaf directory containing an `instance.yaml` or `evaluator.yaml` is
  registered;
- the source directory name and manifest `source_id` are equal;
- no source or leaf path is a symlink;
- no flat instance/evaluator leaf remains outside `sources/`.

## Leaf Manifests and Protocol Versions

### Instance manifests

`instance.yaml` advances from schema version 1 to schema version 2. The
required `source_family` field is removed and replaced with `source_id`.

```yaml
schema_version: 2
source_id: openfibsem
instance_id: fibsem_liftout_v1
evaluator:
  id: fibsem_liftout_v1
  protocol_version: 2
```

The instance schema accepts a valid source identifier rather than enumerating
all sources. Existing task-specific constraints remain conditional on
`task_type`; they do not define the repository hierarchy.

### Evaluator manifests

Every leaf `evaluator.yaml` advances to schema version 2 and requires
`source_id`. Evaluator protocol version 2 carries source-aware orchestration.

```yaml
schema_version: 2
source_id: openfibsem
evaluator_id: fibsem_liftout_v1
protocol_version: 2
container_protocol_version: 1
supported_instances:
  - fibsem_liftout_v1
```

An evaluator may support multiple instances, but all supported IDs are resolved
under the evaluator's own `source_id`. Cross-source support is forbidden.

### Version matrix

| Contract | Old | New |
|---|---:|---:|
| source manifest | absent | 1 |
| instance manifest | 1 | 2 |
| evaluator manifest | 1 | 2 |
| instrument run config | 1 | 2 |
| evaluator request protocol | 1 | 2 |
| PyVISA v1 evaluator report | 1 | 2 |
| PyVISA v2 evaluator report | 2 | 3 |
| FIBSEM evaluator report | 3 | 4 |
| candidate result schema | unchanged | unchanged |
| candidate container protocol | 1 | 1 |

Report version increments add the required `source_id` without changing scoring
fields. Validators reject reports whose `source_id` differs from the request.

## Instrument Run Configuration

Run config schema version 2 adds one required `source_id`. There is no separate
`instance_source` or `evaluator_source`; one run cannot cross source boundaries.

For `instrument/configs/openfibsem/fibsem_liftout_v1.yaml`:

```yaml
schema_version: 2
run_id: fibsem-liftout-v1-reference
source_id: openfibsem
instance_checkout: ../../../instance
instance_id: fibsem_liftout_v1
evaluator_checkout: ../../../evaluator
evaluator_id: fibsem_liftout_v1
candidate_path: ../../../evaluator/sources/openfibsem/fibsem_liftout_v1/reference/solution.py
report_path: ../../reports/openfibsem/fibsem_liftout_v1.json
timeout_seconds: 180
max_output_bytes: 1048576
repeated_worlds: 5
repeated_base_seed: 47000
container_protocol_version: 1
image_mode: locked
openfibsem_checkout: ../../../fibsem
openfibsem_commit: 2ebccb8b9721234ca66bb94de36d0f7cfe047af9
```

The PyVISA configs follow the same structure under `configs/pyvisa/` without
OpenFIBSEM-only fields.

## Resolution and Validation Flow

The instrument orchestrator performs these steps before any image build or
container creation:

1. Validate the exact run config v2 field set and all identifier syntax.
2. Resolve the instance source as
   `<instance_checkout>/sources/<source_id>`.
3. Validate the instance `source.yaml` and require that it registers
   `instance_id`.
4. Resolve the instance leaf beneath the source directory and validate its
   schema v2 manifest, IDs, visible hashes, and container contract.
5. Resolve the evaluator source as
   `<evaluator_checkout>/sources/<source_id>`.
6. Validate the evaluator `source.yaml` and require that it registers
   `evaluator_id`.
7. Resolve the evaluator leaf and validate its schema v2 manifest.
8. Require equal `source_id` values across config, source manifests, and both
   leaf manifests. Validate evaluator protocol and supported instance.
9. Collect clean repository provenance and source-aware paths.
10. Build and start the selected evaluator.

The resolver constructs paths from validated individual components, calls
`resolve()`, verifies containment under the expected source root, and rejects
symlinks at the source and leaf boundaries. It never searches the checkout for
a matching ID.

The evaluator request protocol v2 contains all three IDs:

```json
{
  "protocol_version": 2,
  "source_id": "openfibsem",
  "instance_id": "fibsem_liftout_v1",
  "evaluator_id": "fibsem_liftout_v1"
}
```

The outer evaluator validates the source-aware request before loading the
instance manifest or dispatching evaluator-specific code. Dispatch uses the
composite `(source_id, evaluator_id)` key. The trusted evaluator report echoes
`source_id`; the instrument validator compares it with the run config and then
publishes it in the final report.

## Evaluator Image Boundary

The evaluator image builder receives `source_id` and `evaluator_id`. It stages:

- the generic `instrument_benchmark_evaluator/` runtime;
- the selected `sources/<source_id>/` package, including same-source shared
  dependencies such as the PyVISA v1 code reused by v2;
- locked generic or source-specific runtime assets already required by the
  selected evaluator.

It does not stage other source directories. The image build manifest records
the evaluator repository commit, selected `source_id`, evaluator ID, source
manifest digest, and selected source-tree digest. Existing Docker hardening,
offline wheel locks, UID separation, and cleanup checks remain mandatory.

## Error Handling

All structural failures are contract errors raised before image building. Error
messages identify the failing level but do not search for or suggest an
alternative legacy path. Required failure classes include:

- invalid source, instance, or evaluator ID;
- source directory missing, unexpected, or symlinked;
- malformed `source.yaml`;
- source manifest ID does not equal its directory;
- requested leaf not registered;
- registered leaf missing;
- unregistered leaf present;
- leaf path escape or symlink;
- leaf manifest source/ID mismatch;
- evaluator does not support the instance;
- source mismatch between config, instance, evaluator, request, or report;
- old schema or old flat layout.

Once container execution begins, existing candidate-failure versus
infrastructure-failure semantics remain unchanged.

## Migration Strategy

The migration is a coordinated, hard cut across all three feature branches:

1. Add failing tests that describe source registries, composite resolution,
   protocol v2, and rejection of the old layout.
2. Use `git mv` to move all three instance leaves under their sources.
3. Add instance source schemas/manifests and update instance schema v2,
   manifests, imports, tests, docs, and package discovery.
4. Use `git mv` to move all three evaluator leaves under their sources.
5. Add evaluator source schemas/manifests and update namespaces, imports,
   package discovery, evaluator manifests, request/report contracts, image
   staging, tests, and docs.
6. Add the instrument composite resolver, config v2 contract, source-aware
   image selection, config/report directories, scripts, tests, and docs.
7. Rebuild every candidate image from its new leaf root. The build context
   content is expected to remain byte-identical. Any digest drift must be
   explained and fixed before changing an image lock.
8. Run all local suites, then sync incremental Git bundles to the existing
   remote acceptance root and run native-Linux Docker acceptance.

No compatibility files are left at the old paths. Historical acceptance output
under `/Users/britenyyyang/benchmark/acceptance-results/fibsem-formal-7` and
the server's previous formal logs remain unchanged as prior evidence.

## Test Strategy

### Instance repository

- discover `sources/*/source.yaml`, never `*/instance.yaml` at root;
- validate both source manifests against the source schema;
- prove registry-to-directory and directory-to-registry completeness;
- validate every instance manifest v2 and its `source_id`/path consistency;
- verify all visible hashes and candidate boundaries after `git mv`;
- reject duplicate, unsorted, malformed, orphaned, unregistered, symlinked,
  and flat-layout fixtures;
- run the existing PyVISA and FIBSEM instance suites from their new paths.

### Evaluator repository

- validate evaluator source registries and leaf manifests;
- test source-aware request parsing and composite dispatch;
- reject a correct instance/evaluator ID paired with the wrong source;
- reject legacy protocol v1 requests and reports;
- verify imports use `sources.<source_id>.<evaluator_id>`;
- verify evaluator image staging contains the selected source and excludes the
  other source;
- run the full evaluator suite, isolated vendored PyVISA-sim parameterized
  case, and native-Linux container integration tests.

### Instrument repository

- validate all config v2 files at their source-grouped paths;
- test the resolver with valid, duplicate-name-across-source, traversal,
  symlink, unregistered, missing, and old-layout fixtures;
- validate source equality across config, manifests, request, evaluator report,
  and final report;
- verify provenance still points to repository roots while the report records
  `source_id` and resolved leaf identities;
- verify report publication creates source-grouped directories atomically;
- update scripts and documentation so no active command uses an old config or
  report path.

### Native-Linux acceptance

On `yty@118.180.19.234`, preserve existing unrelated containers and use the
existing `/home/yty/fibsem-acceptance-20260806` acceptance root. Run:

1. locked candidate image rebuild checks for all three instances;
2. the PyVISA v1 reference config from `configs/pyvisa/`;
3. the PyVISA v2 dual-container reference config from `configs/pyvisa/`;
4. the FIBSEM formal validator from `configs/openfibsem/`, including two clean
   ten-world runs and deterministic evidence comparison.

FIBSEM acceptance must again produce score 100, strict pass, ten worlds,
forty checkpoints, semantic reproducibility, exact required GLB/STL/PNG/JSON
artifacts, clean repository provenance, and zero containers labeled
`iab.managed=true` after completion.

## Completion Criteria

- Both source repositories contain only the approved source-grouped leaf
  layout.
- Source and leaf manifests are schema-valid and mutually complete.
- Instrument configs and reports are grouped by `source_id`.
- No executable code, test, active documentation command, or packaging rule
  refers to the old flat instance/evaluator paths.
- Legacy layouts and protocol versions fail explicitly before Docker work.
- Candidate image locks have no unexplained drift.
- All local tests pass.
- All three remote source-aware runs pass, including the formal FIBSEM
  reproducibility gate.
- Local and remote feature branches are clean and at the audited commits.
