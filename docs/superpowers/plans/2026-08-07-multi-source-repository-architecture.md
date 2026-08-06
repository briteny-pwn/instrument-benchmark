# Multi-Source Repository Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `source_id` a first-class identity across the instance, evaluator, and instrument repositories, with strict `sources/<source_id>/<leaf_id>` resolution and source-grouped run outputs.

**Architecture:** The instance and evaluator repositories each gain a schema-validated `source.yaml` registry and symmetric source-first leaf trees. The instrument repository resolves the composite identity `(source_id, instance_id, evaluator_id)` without search or legacy fallback, stages only the selected evaluator source into the trusted image, and sends evaluator protocol v2 requests carrying all three identity fields. Existing candidate APIs, candidate container protocol version 1, benchmark behavior, and locked candidate image inputs remain unchanged.

**Tech Stack:** Python 3.11, dataclasses, `pathlib`, PyYAML 6.0.3, jsonschema 4.25.1, pytest/unittest, JSON Schema Draft 2020-12, Docker/BuildKit, Git bundles, Bash.

## Global Constraints

- The approved design is `instrument/docs/superpowers/specs/2026-08-07-multi-source-repository-architecture-design.md`; it is the source of truth when this plan and an existing implementation detail appear to conflict.
- Valid source, instance, and evaluator identifiers match `^[a-z][a-z0-9_-]*$`.
- Instance identity is `(source_id, instance_id)`; evaluator identity is `(source_id, evaluator_id)`; run identity is `(source_id, instance_id, evaluator_id)`.
- The only source IDs in this migration are `pyvisa` and `openfibsem`.
- Instance and evaluator leaves live only at `sources/<source_id>/<leaf_id>`; root-level leaves, `evaluators/`, symlink aliases, compatibility wrappers, search, and fallback resolution are forbidden.
- Every source directory has a required schema-version-1 `source.yaml`; registry arrays are unique and lexically sorted, and registry-to-leaf completeness is checked in both directions.
- Instance manifest schema version becomes 2, removes `source_family`, and requires `source_id`.
- Evaluator manifest schema version becomes 2 and requires `source_id`.
- Instrument run config schema version becomes 2 and requires `source_id`.
- Evaluator request protocol version becomes 2 and includes `source_id`, `instance_id`, and `evaluator_id`.
- Evaluator report schema versions become 2 for PyVISA v1, 3 for PyVISA v2, and 4 for FIBSEM.
- Candidate result schemas and candidate container protocol version 1 do not change.
- Candidate Docker contexts, Dockerfiles, runtime files, and `image.lock.yaml` files are moved byte-for-byte. Existing image digests remain locked unless a verification command proves unavoidable input drift, which must be explained before relocking.
- The evaluator image contains generic evaluator core plus the complete selected `sources/<source_id>` tree; it contains no other source tree. The PyVISA source is staged as a whole so its v2 evaluator can reuse v1 modules.
- FIBSEM reports are written to `reports/openfibsem/fibsem_liftout_v1.json` and artifacts to `reports/openfibsem/fibsem_liftout_v1.artifacts/`.
- Preserve `/Users/britenyyyang/benchmark/acceptance-results/fibsem-formal-7` as immutable historical evidence.
- Remote native-Linux acceptance uses `yty@118.180.19.234:/home/yty/fibsem-acceptance-20260806` and must finish with zero managed containers.
- Use `apply_patch` for content edits and `git mv` for tracked tree moves. Do not use destructive Git reset or checkout commands.

---

## File Structure

The implementation introduces these focused units:

- `instance/schemas/source.schema.json`: schema for instance-source registries.
- `instance/sources/<source_id>/source.yaml`: authoritative list of instances belonging to one source.
- `instance/sources/<source_id>/<instance_id>/instance.yaml`: schema-v2 leaf identity and existing candidate contract.
- `instance/tests/repository_contracts.py`: test-only strict instance repository discovery used by positive and adversarial layout tests.
- `evaluator/schemas/source.schema.json`: schema for evaluator-source registries.
- `evaluator/sources/<source_id>/source.yaml`: authoritative list of evaluator IDs belonging to one source.
- `evaluator/sources/<source_id>/<evaluator_id>/evaluator.yaml`: schema-v2 evaluator identity and supported-instance contract.
- `evaluator/instrument_benchmark_evaluator/dispatch.py`: composite-identity dispatch and strict packaged manifest lookup.
- `instrument/src/instrument_benchmark/repository_layout.py`: reusable strict filesystem/registry resolver for instance and evaluator checkouts.
- `instrument/src/instrument_benchmark/contracts.py`: run-config v2, cross-source dependency checks, and report-version validation.
- `instrument/src/instrument_benchmark/evaluator_image.py`: source-selected image context and source provenance digests.
- `instrument/src/instrument_benchmark/orchestrator.py`: composite resolution, request protocol v2, source-bound image build, grouped report publication.
- `instrument/configs/<source_id>/<instance_id>.yaml`: run definitions.
- `instrument/reports/<source_id>/<instance_id>.json` and `.artifacts/`: source-grouped outputs.

### Task 1: Migrate and validate the instance repository

**Files:**

- Create: `instance/schemas/source.schema.json`
- Create: `instance/sources/__init__.py`
- Create: `instance/sources/pyvisa/__init__.py`
- Create: `instance/sources/pyvisa/source.yaml`
- Create: `instance/sources/openfibsem/__init__.py`
- Create: `instance/sources/openfibsem/source.yaml`
- Create: `instance/tests/repository_contracts.py`
- Modify: `instance/schemas/instance.schema.json`
- Modify: `instance/tests/test_instance.py`
- Modify: `instance/tests/test_fibsem_instance.py`
- Modify: `instance/tests/test_v2_secrecy.py`
- Modify: `instance/tests/test_v2_architecture_html.py`
- Modify: `instance/README.md`
- Move: `instance/pyvisa_dut_validation_v1` to `instance/sources/pyvisa/pyvisa_dut_validation_v1`
- Move: `instance/pyvisa_dut_validation_v2` to `instance/sources/pyvisa/pyvisa_dut_validation_v2`
- Move: `instance/fibsem_liftout_v1` to `instance/sources/openfibsem/fibsem_liftout_v1`

**Interfaces:**

- Consumes: the identifier regex and strict-layout rules in Global Constraints.
- Produces: `discover_instances(root: Path) -> tuple[InstanceLeaf, ...]`, where `InstanceLeaf` has `source_id: str`, `instance_id: str`, `root: Path`, and `manifest: dict[str, Any]`; schema-v2 instance manifests consumed by Task 4.

- [ ] **Step 1: Add failing source-registry and legacy-layout tests**

Create `instance/tests/repository_contracts.py` with this public test helper:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class InstanceLeaf:
    source_id: str
    instance_id: str
    root: Path
    manifest: dict[str, Any]


def discover_instances(root: Path) -> tuple[InstanceLeaf, ...]:
    source_schema = json.loads((root / "schemas/source.schema.json").read_text())
    instance_schema = json.loads((root / "schemas/instance.schema.json").read_text())
    sources_root = root / "sources"
    if any(root.glob("*/instance.yaml")):
        raise ValueError("flat instance leaves are forbidden")
    records: list[InstanceLeaf] = []
    for source_root in sorted(
        path for path in sources_root.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    ):
        if source_root.is_symlink() or not ID_PATTERN.fullmatch(source_root.name):
            raise ValueError("invalid source directory")
        source = yaml.safe_load((source_root / "source.yaml").read_text())
        jsonschema.Draft202012Validator(source_schema).validate(source)
        if source["source_id"] != source_root.name:
            raise ValueError("source manifest identity mismatch")
        registered = source["instances"]
        if registered != sorted(set(registered)):
            raise ValueError("instance registry must be unique and sorted")
        actual = sorted(
            path.name
            for path in source_root.iterdir()
            if path.is_dir() and (path / "instance.yaml").is_file()
        )
        if registered != actual:
            raise ValueError("instance registry and leaves differ")
        for instance_id in registered:
            leaf = source_root / instance_id
            if leaf.is_symlink() or not ID_PATTERN.fullmatch(instance_id):
                raise ValueError("invalid instance leaf")
            manifest = yaml.safe_load((leaf / "instance.yaml").read_text())
            jsonschema.Draft202012Validator(instance_schema).validate(manifest)
            if manifest["source_id"] != source["source_id"]:
                raise ValueError("instance source mismatch")
            if manifest["instance_id"] != instance_id:
                raise ValueError("instance identity mismatch")
            records.append(InstanceLeaf(source["source_id"], instance_id, leaf, manifest))
    return tuple(records)
```

Update `instance/tests/test_instance.py` to import `discover_instances`, assert the exact composite IDs below, and add temporary-copy cases for an unregistered leaf, an orphan registry entry, a root-level `legacy/instance.yaml`, a symlink source, and a symlink leaf:

```python
assert [(leaf.source_id, leaf.instance_id) for leaf in discover_instances(ROOT)] == [
    ("openfibsem", "fibsem_liftout_v1"),
    ("pyvisa", "pyvisa_dut_validation_v1"),
    ("pyvisa", "pyvisa_dut_validation_v2"),
]
```

Change path constants in the other tests to:

```python
FIBSEM = ROOT / "sources" / "openfibsem" / "fibsem_liftout_v1"
PYVISA_V2 = ROOT / "sources" / "pyvisa" / "pyvisa_dut_validation_v2"
```

and change the secrecy Git query to `git ls-files sources/pyvisa/pyvisa_dut_validation_v2`.
In `test_manual_source_manifest_has_five_official_sources`, replace the old family guard with `if manifest["source_id"] != "pyvisa": continue`.

- [ ] **Step 2: Run the new tests and verify the old layout fails**

Run in the instance checkout:

```bash
python -m pytest tests/test_instance.py tests/test_fibsem_instance.py tests/test_v2_secrecy.py tests/test_v2_architecture_html.py -q
```

Expected: FAIL because `schemas/source.schema.json` and `sources/` do not exist and old root-level instance leaves are still present.

- [ ] **Step 3: Move leaves and add source registries**

Run in the instance checkout:

```bash
mkdir -p sources/pyvisa sources/openfibsem
git mv pyvisa_dut_validation_v1 sources/pyvisa/pyvisa_dut_validation_v1
git mv pyvisa_dut_validation_v2 sources/pyvisa/pyvisa_dut_validation_v2
git mv fibsem_liftout_v1 sources/openfibsem/fibsem_liftout_v1
```

Create empty `sources/__init__.py`, `sources/pyvisa/__init__.py`, and `sources/openfibsem/__init__.py`. Create the two registries exactly as follows:

```yaml
# sources/pyvisa/source.yaml
schema_version: 1
source_id: pyvisa
display_name: PyVISA
description: PyVISA instrument-control experiment tasks
instances:
  - pyvisa_dut_validation_v1
  - pyvisa_dut_validation_v2
```

```yaml
# sources/openfibsem/source.yaml
schema_version: 1
source_id: openfibsem
display_name: OpenFIBSEM
description: FIB-SEM simulation tasks
instances:
  - fibsem_liftout_v1
```

Create `instance/schemas/source.schema.json` exactly as:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://iab.local/schemas/instance-source.schema.json",
  "title": "Instance source registry",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "source_id", "display_name", "description", "instances"
  ],
  "properties": {
    "schema_version": {"const": 1},
    "source_id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"},
    "display_name": {"type": "string", "minLength": 1},
    "description": {"type": "string", "minLength": 1},
    "instances": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"}
    }
  }
}
```

- [ ] **Step 4: Upgrade all instance manifests and their schema**

In `instance/schemas/instance.schema.json`, make these exact identity changes while preserving every other constraint:

```json
"required": [
  "schema_version", "source_id", "instance_id", "task_type",
  "evaluator", "instrument_count", "instrument_roles", "visible_files",
  "submission", "runtime", "scoring", "strict_gates", "container"
],
"properties": {
  "schema_version": {"const": 2},
  "source_id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"},
  "instance_id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"}
}
```

Remove `source_family`. In the task-type branches constrain `source_id` to `pyvisa` or `openfibsem`. Change `evaluator.properties.protocol_version.const` from 1 to 2.

In each moved `instance.yaml`, set `schema_version: 2`, replace `source_family` with the containing `source_id`, and set `evaluator.protocol_version: 2`. Do not change `visible_files`, `container.context_files`, or any candidate file.

- [ ] **Step 5: Update active instance documentation and verify byte-stable locks**

Update `instance/README.md` so all examples use:

```text
sources/pyvisa/pyvisa_dut_validation_v1
sources/pyvisa/pyvisa_dut_validation_v2
sources/openfibsem/fibsem_liftout_v1
```

Run:

```bash
python -m pytest -q
rg -n 'source_family|ROOT / "fibsem_liftout_v1"|ROOT / "pyvisa_dut_validation|git ls-files pyvisa_dut' README.md tests schemas sources
git diff --no-ext-diff -- sources/pyvisa/pyvisa_dut_validation_v1/image.lock.yaml sources/pyvisa/pyvisa_dut_validation_v2/image.lock.yaml sources/openfibsem/fibsem_liftout_v1/image.lock.yaml
```

Expected: all tests PASS; `rg` returns no matches; image-lock diff is empty apart from path headers caused by `git mv`, with unchanged file bodies.

- [ ] **Step 6: Commit the instance migration**

```bash
git add README.md schemas sources tests
git commit -m "refactor: group instances by source"
```

Expected: one instance-repository commit; `git status --short` is empty.

### Task 2: Migrate evaluator packages, registries, manifests, and report versions

**Files:**

- Create: `evaluator/schemas/source.schema.json`
- Create: `evaluator/sources/__init__.py`
- Create: `evaluator/sources/pyvisa/__init__.py`
- Create: `evaluator/sources/pyvisa/source.yaml`
- Create: `evaluator/sources/openfibsem/__init__.py`
- Create: `evaluator/sources/openfibsem/source.yaml`
- Create: `evaluator/tests/test_source_layout.py`
- Modify: `evaluator/pyproject.toml`
- Modify: every active Python import under `evaluator/instrument_benchmark_evaluator`, `evaluator/tests`, and the moved source trees that starts with `evaluators.`
- Modify: `evaluator/report.schema.json`
- Modify: `evaluator/README.md`
- Delete: `evaluator/evaluator.yaml`
- Delete: `evaluator/instrument_benchmark_evaluator/evaluator.yaml`
- Move: `evaluator/evaluators/pyvisa_dut_validation_v1` to `evaluator/sources/pyvisa/pyvisa_dut_validation_v1`
- Move: `evaluator/evaluators/pyvisa_dut_validation_v2` to `evaluator/sources/pyvisa/pyvisa_dut_validation_v2`
- Move: `evaluator/evaluators/fibsem_liftout_v1` to `evaluator/sources/openfibsem/fibsem_liftout_v1`

**Interfaces:**

- Consumes: instance evaluator protocol version 2 from Task 1.
- Produces: importable packages `sources.pyvisa.*` and `sources.openfibsem.*`; source registries; evaluator manifests with `source_id`; report versions consumed by Tasks 3 and 6.

- [ ] **Step 1: Write failing evaluator source-layout tests**

Create `evaluator/tests/test_source_layout.py` with this complete discovery contract:

```python
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


def discover_evaluators(root: Path) -> list[tuple[str, str, dict[str, Any]]]:
    schema = json.loads((root / "schemas/source.schema.json").read_text())
    if (root / "evaluator.yaml").exists() or (root / "evaluators").exists():
        raise ValueError("legacy evaluator layout is forbidden")
    records: list[tuple[str, str, dict[str, Any]]] = []
    for source_root in sorted(
        path for path in (root / "sources").iterdir()
        if path.is_dir() and path.name != "__pycache__"
    ):
        if source_root.is_symlink() or not ID_PATTERN.fullmatch(source_root.name):
            raise ValueError("invalid source directory")
        source = yaml.safe_load((source_root / "source.yaml").read_text())
        jsonschema.Draft202012Validator(schema).validate(source)
        if source["source_id"] != source_root.name:
            raise ValueError("source identity mismatch")
        registered = source["evaluators"]
        if registered != sorted(set(registered)):
            raise ValueError("evaluator registry must be unique and sorted")
        actual = sorted(
            path.name
            for path in source_root.iterdir()
            if path.is_dir() and (path / "evaluator.yaml").is_file()
        )
        if registered != actual:
            raise ValueError("evaluator registry and leaves differ")
        for evaluator_id in registered:
            leaf = source_root / evaluator_id
            if leaf.is_symlink() or not ID_PATTERN.fullmatch(evaluator_id):
                raise ValueError("invalid evaluator leaf")
            manifest = yaml.safe_load((leaf / "evaluator.yaml").read_text())
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema_version") != 2
                or manifest.get("source_id") != source["source_id"]
                or manifest.get("evaluator_id") != evaluator_id
                or manifest.get("protocol_version") != 2
            ):
                raise ValueError("evaluator manifest identity mismatch")
            supported = manifest.get("supported_instances")
            if not isinstance(supported, list) or supported != sorted(set(supported)):
                raise ValueError("supported instances must be unique and sorted")
            records.append((source["source_id"], evaluator_id, manifest))
    return records
```

Assert:

```python
assert discovered_ids == [
    ("openfibsem", "fibsem_liftout_v1"),
    ("pyvisa", "pyvisa_dut_validation_v1"),
    ("pyvisa", "pyvisa_dut_validation_v2"),
]
assert not (ROOT / "evaluators").exists()
assert not (ROOT / "evaluator.yaml").exists()
assert not (ROOT / "instrument_benchmark_evaluator/evaluator.yaml").exists()
```

For every leaf, validate that its manifest has `schema_version == 2`, `source_id` equal to the parent source, `evaluator_id` equal to the leaf name, `protocol_version == 2`, and a lexically sorted unique `supported_instances` list. Add temporary-copy failures for unregistered/orphan leaves, root flat manifests, source/leaf symlinks, and a mismatched `source_id`.

- [ ] **Step 2: Run the source-layout test and verify it fails**

```bash
python -m pytest tests/test_source_layout.py -q
```

Expected: FAIL because the evaluator code is still in `evaluators/`, source registries are absent, and root fallback manifests exist.

- [ ] **Step 3: Move evaluator leaves and replace package imports**

Run:

```bash
mkdir -p sources/pyvisa sources/openfibsem
git mv evaluators/pyvisa_dut_validation_v1 sources/pyvisa/pyvisa_dut_validation_v1
git mv evaluators/pyvisa_dut_validation_v2 sources/pyvisa/pyvisa_dut_validation_v2
git mv evaluators/fibsem_liftout_v1 sources/openfibsem/fibsem_liftout_v1
git rm evaluator.yaml instrument_benchmark_evaluator/evaluator.yaml
```

Use `apply_patch` to perform this exact import mapping in active code and tests:

| Old prefix | New prefix |
|---|---|
| `evaluators.pyvisa_dut_validation_v1` | `sources.pyvisa.pyvisa_dut_validation_v1` |
| `evaluators.pyvisa_dut_validation_v2` | `sources.pyvisa.pyvisa_dut_validation_v2` |
| `evaluators.fibsem_liftout_v1` | `sources.openfibsem.fibsem_liftout_v1` |

Do not rewrite historical files under `docs/superpowers/`.

- [ ] **Step 4: Add evaluator source registries and package metadata**

Create empty package initializers and these registries:

```yaml
# sources/pyvisa/source.yaml
schema_version: 1
source_id: pyvisa
display_name: PyVISA
description: PyVISA instrument-control evaluators
evaluators:
  - pyvisa_dut_validation_v1
  - pyvisa_dut_validation_v2
```

```yaml
# sources/openfibsem/source.yaml
schema_version: 1
source_id: openfibsem
display_name: OpenFIBSEM
description: FIB-SEM simulation evaluators
evaluators:
  - fibsem_liftout_v1
```

Create `evaluator/schemas/source.schema.json` with this complete schema, then change `evaluator/pyproject.toml`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://iab.local/schemas/evaluator-source.schema.json",
  "title": "Evaluator source registry",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "source_id", "display_name", "description", "evaluators"
  ],
  "properties": {
    "schema_version": {"const": 1},
    "source_id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"},
    "display_name": {"type": "string", "minLength": 1},
    "description": {"type": "string", "minLength": 1},
    "evaluators": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"}
    }
  }
}
```

Use this package configuration:

```toml
[tool.setuptools.packages.find]
include = ["instrument_benchmark_evaluator*", "sources*"]

[tool.setuptools.package-data]
"sources.pyvisa" = ["source.yaml"]
"sources.openfibsem" = ["source.yaml"]
"sources.pyvisa.pyvisa_dut_validation_v1" = [
  "evaluator.yaml",
  "adversarial_matrix.yaml",
  "simulator/*.yaml",
  "worlds/*.yaml",
]
"sources.pyvisa.pyvisa_dut_validation_v2" = ["evaluator.yaml", "simulator.yaml"]
"sources.openfibsem.fibsem_liftout_v1" = ["evaluator.yaml", "scenarios/*.json"]
```

- [ ] **Step 5: Upgrade evaluator manifests and report versions**

For all three evaluator manifests, set `schema_version: 2`, add the containing `source_id`, and set `protocol_version: 2`. Set report schema versions to:

```yaml
pyvisa_dut_validation_v1: 2
pyvisa_dut_validation_v2: 3
fibsem_liftout_v1: 4
```

Update only top-level evaluator report serialization:

```python
# sources/pyvisa/pyvisa_dut_validation_v1/scoring.py
"schema_version": 2
"source_id": "pyvisa"

# sources/pyvisa/pyvisa_dut_validation_v2/reports.py
value["schema_version"] = 3
# The wrapped v1 report already carries source_id == "pyvisa".

# sources/openfibsem/fibsem_liftout_v1/scoring.py
"schema_version": 4
"source_id": "openfibsem"

# sources/openfibsem/fibsem_liftout_v1/reports.py
if (
    report["schema_version"] != 4
    or report["source_id"] != "openfibsem"
    or report["evaluator_id"] != "fibsem_liftout_v1"
):
```

Change `evaluator/report.schema.json` top-level `schema_version.const` to 2; add required top-level `source_id` with `{"const": "pyvisa"}`. Leave journal, simulator-service, checkpoint, and artifact internal schema versions unchanged.

- [ ] **Step 6: Update test expectations and run the evaluator suite**

Update report assertions from `1/2/3` to `2/3/4` only where they assert top-level evaluator reports. Update path literals in unit and integration tests to the exact leaves `sources/pyvisa/pyvisa_dut_validation_v1`, `sources/pyvisa/pyvisa_dut_validation_v2`, and `sources/openfibsem/fibsem_liftout_v1`.

Run:

```bash
python -m pytest -q
rg -n 'from evaluators|import evaluators|["'"']evaluators/|evaluator.yaml' instrument_benchmark_evaluator sources tests README.md pyproject.toml
```

Expected: all tests PASS; `rg` finds only the intended leaf filename references and no old import or directory prefix; no root fallback manifest exists.

- [ ] **Step 7: Commit the evaluator layout and report migration**

```bash
git add README.md pyproject.toml report.schema.json schemas sources tests instrument_benchmark_evaluator
git commit -m "refactor: group evaluators by source"
```

Expected: one evaluator-repository commit; `git status --short` is empty.

### Task 3: Make evaluator request loading and dispatch source-aware

**Files:**

- Create: `evaluator/instrument_benchmark_evaluator/dispatch.py`
- Modify: `evaluator/instrument_benchmark_evaluator/__init__.py`
- Modify: `evaluator/instrument_benchmark_evaluator/contracts.py`
- Modify: `evaluator/instrument_benchmark_evaluator/cli.py`
- Modify: `evaluator/tests/test_cli.py`
- Modify: `evaluator/tests/test_run_backend.py`
- Modify: `evaluator/tests/test_v2_run.py`
- Modify: `evaluator/tests/test_fibsem_run.py`
- Modify: `evaluator/sources/openfibsem/fibsem_liftout_v1/tests/test_dispatch.py`
- Modify: evaluator integration request fixtures under `evaluator/tests/integration/`

**Interfaces:**

- Consumes: packaged source trees and evaluator manifests from Task 2.
- Produces: `EvaluatorRequest(source_id, instance_id, evaluator_id, ...)`, `EvaluatorTarget`, `resolve_evaluator_target(source_id, evaluator_id, instance_id)`, and strict protocol-v2 request loading consumed by the trusted evaluator CLI.

- [ ] **Step 1: Write failing composite-dispatch and request-v2 tests**

Add tests for this target contract:

```python
target = resolve_evaluator_target(
    "openfibsem", "fibsem_liftout_v1", "fibsem_liftout_v1"
)
assert target.kind == "fibsem"
assert target.manifest["source_id"] == "openfibsem"

with pytest.raises(ContractError, match="source/evaluator/instance combination"):
    resolve_evaluator_target("pyvisa", "fibsem_liftout_v1", "fibsem_liftout_v1")
```

Update every valid request fixture to include:

```json
{
  "protocol_version": 2,
  "source_id": "pyvisa",
  "instance_id": "pyvisa_dut_validation_v1",
  "evaluator_id": "pyvisa_dut_validation_v1"
}
```

Add exact-field rejection cases for missing `source_id`, missing `evaluator_id`, protocol version 1, invalid identifiers, cross-source combinations, an instance manifest whose `source_id` differs, and an evaluator ID that does not support the requested instance.

- [ ] **Step 2: Run focused evaluator contract tests and verify they fail**

```bash
python -m pytest tests/test_cli.py tests/test_run_backend.py sources/openfibsem/fibsem_liftout_v1/tests/test_dispatch.py -q
```

Expected: FAIL because `dispatch.py` and the new request fields do not exist and `PROTOCOL_VERSION` remains 1.

- [ ] **Step 3: Implement composite dispatch**

Create `instrument_benchmark_evaluator/dispatch.py` with these interfaces and exact supported table:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from .contracts import ContractError

EvaluatorKind = Literal["pyvisa_v1", "pyvisa_v2", "fibsem"]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TARGETS: dict[tuple[str, str], EvaluatorKind] = {
    ("pyvisa", "pyvisa_dut_validation_v1"): "pyvisa_v1",
    ("pyvisa", "pyvisa_dut_validation_v2"): "pyvisa_v2",
    ("openfibsem", "fibsem_liftout_v1"): "fibsem",
}


@dataclass(frozen=True)
class EvaluatorTarget:
    source_id: str
    evaluator_id: str
    instance_id: str
    kind: EvaluatorKind
    root: Path
    manifest: dict[str, Any]


def resolve_evaluator_target(
    source_id: str, evaluator_id: str, instance_id: str
) -> EvaluatorTarget:
    try:
        kind = TARGETS[(source_id, evaluator_id)]
    except KeyError as exc:
        raise ContractError("unsupported source/evaluator/instance combination") from exc
    source_root = PACKAGE_ROOT / "sources" / source_id
    source_manifest_path = source_root / "source.yaml"
    if source_root.is_symlink() or not source_manifest_path.is_file():
        raise ContractError("packaged evaluator source is missing")
    source = yaml.safe_load(source_manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(source, dict)
        or source.get("schema_version") != 1
        or source.get("source_id") != source_id
        or evaluator_id not in source.get("evaluators", [])
    ):
        raise ContractError("unsupported source/evaluator/instance combination")
    root = source_root / evaluator_id
    manifest_path = root / "evaluator.yaml"
    if root.is_symlink() or not manifest_path.is_file():
        raise ContractError("packaged evaluator manifest is missing")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 2
        or manifest.get("source_id") != source_id
        or manifest.get("evaluator_id") != evaluator_id
        or manifest.get("protocol_version") != 2
        or instance_id not in manifest.get("supported_instances", [])
    ):
        raise ContractError("unsupported source/evaluator/instance combination")
    return EvaluatorTarget(source_id, evaluator_id, instance_id, kind, root, manifest)
```

To avoid a circular import, define `ContractError` in `contracts.py` and import `resolve_evaluator_target` inside `load_evaluator_request` after parsing identifier strings.

- [ ] **Step 4: Upgrade the evaluator request and instance contracts**

Set `PROTOCOL_VERSION = 2` in `instrument_benchmark_evaluator/__init__.py` and remove `EVALUATOR_ID`. Extend `EvaluatorRequest` in `contracts.py`:

```python
@dataclass(frozen=True)
class EvaluatorRequest:
    protocol_version: int
    run_id: str
    source_id: str
    instance_id: str
    evaluator_id: str
    instance_path: Path
    candidate_path: Path
    timeout_seconds: float
    max_output_bytes: int
    repeated_worlds: int
    repeated_base_seed: int
    container_protocol_version: int
    image_mode: str
    shared_run_root: Path
    evaluator_image_id: str | None = None
```

Use exact required fields plus `evaluator_image_id` for PyVISA v2 and FIBSEM. Validate all identity values with `^[a-z][a-z0-9_-]*$`, call `resolve_evaluator_target`, and return the three IDs unchanged. Replace `load_instance_settings(instance_path, expected_evaluator_id=...)` with:

```python
def load_instance_settings(
    instance_path: Path,
    *,
    expected_source_id: str,
    expected_instance_id: str,
    expected_evaluator_id: str,
) -> InstanceSettings:
```

Require instance manifest schema 2, matching `source_id` and `instance_id`, plus evaluator contract `{"id": expected_evaluator_id, "protocol_version": 2}`. Keep container protocol validation at 1.

- [ ] **Step 5: Dispatch the CLI from the resolved target**

In `cli.py`, remove `MANIFEST`, `V2_MANIFEST`, and `FIBSEM_MANIFEST`. After loading the request, use:

```python
target = resolve_evaluator_target(
    request.source_id, request.evaluator_id, request.instance_id
)
instance = load_instance_settings(
    request.instance_path,
    expected_source_id=request.source_id,
    expected_instance_id=request.instance_id,
    expected_evaluator_id=request.evaluator_id,
)
kind = target.kind
manifest = target.manifest
```

Use `sources.pyvisa...` and `sources.openfibsem...` imports for suites and services. For non-FIBSEM reports emit:

```python
if report.get("source_id") != request.source_id:
    raise ContractError("evaluator report source_id does not match request")
report["evaluator"] = {
    "source_id": request.source_id,
    "id": request.evaluator_id,
    "protocol_version": 2,
    "run_id": request.run_id,
}
```

- [ ] **Step 6: Run evaluator unit and integration-collection tests**

```bash
python -m pytest -q
python -m pytest tests/integration --collect-only -q
rg -n 'EVALUATOR_ID|evaluator_kind\(|protocol version 1|"protocol_version": 1' instrument_benchmark_evaluator tests sources --glob '*.py'
```

Expected: all unit tests PASS; all integration tests collect; `rg` has no evaluator-request protocol-v1 or obsolete dispatch references. Internal candidate container and service protocol fixtures may still contain version 1 and must be inspected rather than changed.

- [ ] **Step 7: Commit protocol-v2 evaluator dispatch**

```bash
git add instrument_benchmark_evaluator tests sources
git commit -m "feat: dispatch evaluators by source identity"
```

Expected: one evaluator-repository commit; `git status --short` is empty.

### Task 4: Add strict source resolution and run-config v2 to the instrument repository

**Files:**

- Create: `instrument/src/instrument_benchmark/repository_layout.py`
- Create: `instrument/tests/test_repository_layout.py`
- Modify: `instrument/src/instrument_benchmark/contracts.py`
- Modify: `instrument/schemas/run.schema.json`
- Modify: `instrument/tests/test_orchestrator.py`
- Modify: `instrument/tests/test_fibsem_contracts.py`
- Modify: `instrument/tests/test_v2_contracts.py`

**Interfaces:**

- Consumes: source registries and schema-v2 leaf manifests from Tasks 1-2.
- Produces: `RunConfig.source_id`, `ResolvedLeaf`, `resolve_instance_leaf`, `resolve_evaluator_leaf`, and source-aware dependency/report validation consumed by Tasks 5-6.

- [ ] **Step 1: Write failing resolver and config-v2 tests**

Create temporary repositories in `tests/test_repository_layout.py` and assert:

```python
instance = resolve_instance_leaf(checkout, "openfibsem", "fibsem_liftout_v1")
assert instance.root == checkout / "sources/openfibsem/fibsem_liftout_v1"
assert instance.source_manifest["instances"] == ["fibsem_liftout_v1"]

evaluator = resolve_evaluator_leaf(checkout, "pyvisa", "pyvisa_dut_validation_v2")
assert evaluator.root == checkout / "sources/pyvisa/pyvisa_dut_validation_v2"
```

Add rejection cases for an invalid ID, missing/malformed source manifest, unsorted/duplicate registry, registered missing leaf, unregistered leaf, source/leaf symlink, path escape, manifest `source_id` mismatch, leaf ID mismatch, and a root-level flat leaf even when the source tree is valid. Add two valid sources that both register `shared_id`; assert each `(source_id, shared_id)` resolves to its own leaf and no global ID search occurs.

In config tests, require `schema_version: 2` and `source_id`. Assert schema-v1 configs and configs with an unknown field fail before any Git/Docker operation.

- [ ] **Step 2: Run focused instrument contract tests and verify they fail**

```bash
python -m pytest tests/test_repository_layout.py tests/test_orchestrator.py tests/test_fibsem_contracts.py tests/test_v2_contracts.py -q
```

Expected: FAIL because strict resolver functions and `RunConfig.source_id` do not exist.

- [ ] **Step 3: Implement strict repository resolution**

Create `repository_layout.py` with:

```python
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class ResolvedLeaf:
    source_id: str
    leaf_id: str
    root: Path
    manifest_path: Path
    source_manifest_path: Path
    manifest: dict[str, Any]
    source_manifest: dict[str, Any]


def resolve_instance_leaf(
    checkout: Path, source_id: str, instance_id: str
) -> ResolvedLeaf:
    return _resolve_registered_leaf(
        checkout, source_id, instance_id,
        registry_key="instances", manifest_name="instance.yaml",
        identity_key="instance_id",
    )


def resolve_evaluator_leaf(
    checkout: Path, source_id: str, evaluator_id: str
) -> ResolvedLeaf:
    return _resolve_registered_leaf(
        checkout, source_id, evaluator_id,
        registry_key="evaluators", manifest_name="evaluator.yaml",
        identity_key="evaluator_id",
    )
```

Implement `_resolve_registered_leaf` and its loader with this logic; add `import re`, `import yaml`, and `from .contracts import ContractError`:

```python
def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label} is missing or is not a regular file")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must contain a mapping")
    return value


def _require_id(value: str, label: str) -> None:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise ContractError(f"invalid {label}")


def _resolve_registered_leaf(
    checkout: Path,
    source_id: str,
    leaf_id: str,
    *,
    registry_key: str,
    manifest_name: str,
    identity_key: str,
) -> ResolvedLeaf:
    _require_id(source_id, "source_id")
    _require_id(leaf_id, identity_key)
    checkout = checkout.resolve(strict=True)
    sources_path = checkout / "sources"
    if sources_path.is_symlink() or not sources_path.is_dir():
        raise ContractError("sources directory is missing or is a symlink")
    if (checkout / manifest_name).exists() or any(checkout.glob(f"*/{manifest_name}")):
        raise ContractError("legacy flat leaf layout is forbidden")
    if manifest_name == "evaluator.yaml" and (checkout / "evaluators").exists():
        raise ContractError("legacy evaluators directory is forbidden")
    source_path = sources_path / source_id
    if source_path.is_symlink() or not source_path.is_dir():
        raise ContractError("registered source directory is missing or is a symlink")
    source_root = source_path.resolve(strict=True)
    if not source_root.is_relative_to(sources_path.resolve(strict=True)):
        raise ContractError("source path escapes sources directory")
    source_manifest_path = source_root / "source.yaml"
    source = _load_mapping(source_manifest_path, "source manifest")
    if set(source) != {
        "schema_version", "source_id", "display_name", "description", registry_key
    }:
        raise ContractError("source manifest fields are invalid")
    if source["schema_version"] != 1 or source["source_id"] != source_id:
        raise ContractError("source manifest identity is invalid")
    if not all(
        isinstance(source[name], str) and bool(source[name].strip())
        for name in ("display_name", "description")
    ):
        raise ContractError("source manifest text fields are invalid")
    registered = source[registry_key]
    if (
        not isinstance(registered, list)
        or not registered
        or any(
            not isinstance(item, str) or ID_PATTERN.fullmatch(item) is None
            for item in registered
        )
        or registered != sorted(set(registered))
    ):
        raise ContractError("source registry must be non-empty, unique, and sorted")
    actual: list[str] = []
    for child in source_root.iterdir():
        manifest_path = child / manifest_name
        if child.is_symlink() and manifest_path.exists():
            raise ContractError("leaf symlinks are forbidden")
        if child.is_dir() and manifest_path.is_file():
            actual.append(child.name)
    if registered != sorted(actual):
        raise ContractError("source registry and leaf directories differ")
    leaf_path = source_root / leaf_id
    if leaf_path.is_symlink() or not leaf_path.is_dir():
        raise ContractError("registered leaf is missing or is a symlink")
    leaf_root = leaf_path.resolve(strict=True)
    if not leaf_root.is_relative_to(source_root):
        raise ContractError("leaf path escapes source directory")
    manifest_path = leaf_root / manifest_name
    manifest = _load_mapping(manifest_path, "leaf manifest")
    if (
        manifest.get("schema_version") != 2
        or manifest.get("source_id") != source_id
        or manifest.get(identity_key) != leaf_id
    ):
        raise ContractError("leaf manifest identity is invalid")
    return ResolvedLeaf(
        source_id=source_id,
        leaf_id=leaf_id,
        root=leaf_root,
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        manifest=manifest,
        source_manifest=source,
    )
```

The function validates identifiers before joining paths and never searches recursively for a requested identity.

- [ ] **Step 4: Upgrade RunConfig and its JSON schema**

Add `source_id: str` after `run_id` in `RunConfig`. In `load_run_config`, require exact schema-v2 fields, validate `source_id`, `instance_id`, and `evaluator_id` with the identifier regex, and return `schema_version=2`. Determine the FIBSEM-only OpenFIBSEM fields from the composite identity:

```python
is_fibsem = (
    value.get("source_id") == "openfibsem"
    and value.get("evaluator_id") == "fibsem_liftout_v1"
)
```

In `schemas/run.schema.json`, set schema version const 2, add required `source_id`, apply the ID regex to all three identity fields, and conditionally require `openfibsem_checkout` and `openfibsem_commit` only for the composite FIBSEM identity.

- [ ] **Step 5: Make dependency and report validation source-aware**

Change dependency validation to:

```python
def validate_dependencies(
    source_id: str,
    instance: dict[str, Any],
    evaluator: dict[str, Any],
) -> None:
    if instance.get("source_id") != source_id:
        raise ContractError("instance source_id mismatch")
    if evaluator.get("source_id") != source_id:
        raise ContractError("evaluator source_id mismatch")
    # Retain evaluator ID, protocol, supported instance, container protocol,
    # Docker execution, and locked image checks below these two gates.
```

Change report validation to `validate_evaluator_report(value, source_id, evaluator_id, *, expected_run_id=None)` and use this exact version map:

```python
REPORT_SCHEMA_VERSIONS = {
    ("pyvisa", "pyvisa_dut_validation_v1"): 2,
    ("pyvisa", "pyvisa_dut_validation_v2"): 3,
    ("openfibsem", "fibsem_liftout_v1"): 4,
}
```

Require top-level `report["source_id"] == source_id` for every report. Also require non-FIBSEM `report["evaluator"]["source_id"] == source_id`. Add `source_id` to `_validate_fibsem_report`'s exact required-field set, require `source_id == "openfibsem"`, require schema 4, and keep its exact evaluator ID and OpenFIBSEM commit checks.

- [ ] **Step 6: Run focused tests and commit strict layout contracts**

```bash
python -m pytest tests/test_repository_layout.py tests/test_orchestrator.py tests/test_fibsem_contracts.py tests/test_v2_contracts.py -q
git add schemas src/instrument_benchmark/contracts.py src/instrument_benchmark/repository_layout.py tests
git commit -m "feat: resolve benchmark leaves by source"
```

Expected: focused tests PASS; one instrument-repository commit; no fallback resolver remains in the new module.

### Task 5: Stage source-selected evaluator images with source provenance

**Files:**

- Modify: `instrument/src/instrument_benchmark/evaluator_image.py`
- Modify: `instrument/tests/test_evaluator_image.py`
- Modify: `instrument/tests/integration/test_evaluator_image_linux.py`
- Modify: `instrument/tests/test_openfibsem_runtime_lock.py`

**Interfaces:**

- Consumes: `source_id`, `evaluator_id`, and strict evaluator leaf resolution from Task 4.
- Produces: `EvaluatorBuildContext` and `EvaluatorImageEvidence` fields `source_id`, `evaluator_id`, `source_manifest_sha256`, and `source_tree_sha256`; `EvaluatorImageBuilder.build(..., source_id, evaluator_id, ...)` consumed by Task 6.

- [ ] **Step 1: Write failing source-selection and provenance tests**

Build fixture evaluator repositories with `sources/pyvisa` and `sources/openfibsem`. Assert a PyVISA staged context contains:

```text
evaluator/pyproject.toml
evaluator/instrument_benchmark_evaluator/
evaluator/sources/__init__.py
evaluator/sources/pyvisa/
evaluator/vendor/pyvisa-sim-iab/
```

and does not contain `evaluator/sources/openfibsem`. Assert the OpenFIBSEM context contains its full source tree and not `evaluator/sources/pyvisa` or `evaluator/vendor/pyvisa-sim-iab`. Assert `.iab-build-manifest.json` identity and digest shapes with:

```python
manifest = json.loads(context.manifest_path.read_text())
assert manifest["schema_version"] == 2
assert manifest["evaluator_commit"] == evaluator_commit
assert manifest["source_id"] == "pyvisa"
assert manifest["evaluator_id"] == "pyvisa_dut_validation_v2"
assert re.fullmatch(r"[0-9a-f]{64}", manifest["source_manifest_sha256"])
assert re.fullmatch(r"[0-9a-f]{64}", manifest["source_tree_sha256"])
assert isinstance(manifest["files"], dict) and manifest["files"]
```

Compute the digest expectations in the test from canonical byte records. Add rejection tests for a missing selected source, an unregistered evaluator, a source symlink, and dirty or untracked cross-source content affecting the selected records.

- [ ] **Step 2: Run image-context tests and verify they fail**

```bash
python -m pytest tests/test_evaluator_image.py tests/test_openfibsem_runtime_lock.py -q
```

Expected: FAIL because the builder copies every tracked evaluator file and has no source identity or source digests.

- [ ] **Step 3: Extend image evidence and build signatures**

Add these fields to both `EvaluatorBuildContext` and `EvaluatorImageEvidence`:

```python
source_id: str
evaluator_id: str
source_manifest_sha256: str
source_tree_sha256: str
```

Change signatures to:

```python
def EvaluatorImageBuilder.build(
    self,
    evaluator_checkout: Path,
    *,
    run_id: str,
    source_id: str,
    evaluator_id: str,
    openfibsem_checkout: Path | None = None,
    openfibsem_commit: str | None = None,
) -> EvaluatorImageEvidence:

def stage_evaluator_build_context(
    evaluator_checkout: Path,
    assets_root: Path,
    destination: Path,
    *,
    source_id: str,
    evaluator_id: str,
    openfibsem_checkout: Path | None = None,
    openfibsem_commit: str | None = None,
) -> EvaluatorBuildContext:
```

- [ ] **Step 4: Implement the tracked-file allowlist and provenance digests**

Resolve the selected leaf with `resolve_evaluator_leaf`. Select tracked files only when their POSIX path is one of:

```python
relative == Path("pyproject.toml")
relative.parts[:1] == ("instrument_benchmark_evaluator",)
relative == Path("sources/__init__.py")
relative.parts[:2] == ("sources", source_id)
source_id == "pyvisa" and relative.parts[:2] == ("vendor", "pyvisa-sim-iab")
```

Before selecting files, require `_git(evaluator_checkout, "status", "--porcelain") == ""`; otherwise raise `EvaluatorImageError("evaluator checkout must be clean")`. Reject any selected symlink/non-regular file. Compute:

```python
source_manifest_sha256 = _sha256(
    (evaluator_checkout / "sources" / source_id / "source.yaml").read_bytes()
)
source_tree_sha256 = _sha256(
    _canonical_json(_file_records(evaluator_target / "sources" / source_id, exclude=set()))
)
```

Write build manifest schema 2 with `evaluator_commit`, source identity, and both digests before `files`. Change verification to `verify_build_manifest(root, manifest_path, *, expected_evaluator_commit: str)`, require the stored commit to equal that argument, and recompute both source digests from the staged tree. Call it with `context.evaluator_commit`. Add labels `iab.source_id` and `iab.evaluator_id` to the Docker build command.

- [ ] **Step 5: Run image unit tests and native-Linux integration collection**

```bash
python -m pytest tests/test_evaluator_image.py tests/test_openfibsem_runtime_lock.py -q
python -m pytest tests/integration/test_evaluator_image_linux.py --collect-only -q
```

Expected: unit tests PASS and the Linux test collects with the new required builder arguments.

- [ ] **Step 6: Commit source-selected evaluator image construction**

```bash
git add src/instrument_benchmark/evaluator_image.py tests/test_evaluator_image.py tests/test_openfibsem_runtime_lock.py tests/integration/test_evaluator_image_linux.py
git commit -m "feat: scope evaluator images to one source"
```

Expected: one instrument-repository commit; `git status --short` is empty.

### Task 6: Bind orchestration, requests, reports, configs, and outputs to source

**Files:**

- Modify: `instrument/src/instrument_benchmark/contracts.py`
- Modify: `instrument/src/instrument_benchmark/orchestrator.py`
- Modify: `instrument/tests/test_orchestrator.py`
- Modify: `instrument/tests/test_fibsem_contracts.py`
- Modify: `instrument/tests/test_v2_contracts.py`
- Modify: `instrument/tests/integration/test_containerized_evaluator_linux.py`
- Modify: `instrument/tests/integration/test_v2_dual_container_linux.py`
- Modify: `instrument/tests/integration/test_fibsem_dual_container_linux.py`
- Move: `instrument/configs/pyvisa_dut_validation_v1.yaml` to `instrument/configs/pyvisa/pyvisa_dut_validation_v1.yaml`
- Move: `instrument/configs/pyvisa_dut_validation_v2.yaml` to `instrument/configs/pyvisa/pyvisa_dut_validation_v2.yaml`
- Move: `instrument/configs/fibsem_liftout_v1.yaml` to `instrument/configs/openfibsem/fibsem_liftout_v1.yaml`
- Move: `instrument/reports/distributed_validation.json` to `instrument/reports/pyvisa/pyvisa_dut_validation_v1.json`

**Interfaces:**

- Consumes: Tasks 3-5 contracts and builder signatures.
- Produces: protocol-v2 evaluator requests, strict source-bound execution, source provenance in final reports, and grouped config/report paths consumed by scripts and acceptance.

- [ ] **Step 1: Write failing end-to-end orchestration identity tests**

Update the fake repository setup in `tests/test_orchestrator.py` to create registered source trees. Assert the runner receives:

```python
assert request["protocol_version"] == 2
assert request["source_id"] == "pyvisa"
assert request["instance_id"] == "pyvisa_dut_validation_v2"
assert request["evaluator_id"] == "pyvisa_dut_validation_v2"
assert image_builder.seen == {
    "source_id": "pyvisa",
    "evaluator_id": "pyvisa_dut_validation_v2",
}
```

Assert a `pyvisa` run cannot bind an `openfibsem` evaluator even when matching-named directories are manually added. Assert deleting `sources/pyvisa/source.yaml` fails before the fake image builder or runner is called. Assert no root `instance.yaml` or `evaluator.yaml` is accepted.

Add `test_dump_json_creates_nested_report_atomically`: wrap the real `os.replace`, call `dump_json(tmp_path / "reports/openfibsem/run.json", {"ok": True})`, and assert the wrapper saw one temporary sibling moved to the final path, the JSON is complete, and no `*.tmp` sibling remains.

- [ ] **Step 2: Run orchestrator tests and verify they fail**

```bash
python -m pytest tests/test_orchestrator.py tests/test_fibsem_contracts.py tests/test_v2_contracts.py -q
```

Expected: FAIL because orchestration still uses flat/fallback paths and request protocol v1.

- [ ] **Step 3: Replace fallback resolution in the orchestrator**

Delete `evaluator_manifest_path`. At the start of `run_benchmark`, resolve both leaves explicitly:

```python
instance_leaf = resolve_instance_leaf(
    config.instance_checkout, config.source_id, config.instance_id
)
evaluator_leaf = resolve_evaluator_leaf(
    config.evaluator_checkout, config.source_id, config.evaluator_id
)
instance_root = instance_leaf.root
instance_manifest = instance_leaf.manifest
evaluator_manifest = evaluator_leaf.manifest
validate_dependencies(config.source_id, instance_manifest, evaluator_manifest)
```

Keep visible-file and Git provenance checks. Use the composite FIBSEM identity for OpenFIBSEM commit checks, artifact publication, and FIBSEM run binding.

- [ ] **Step 4: Build the selected evaluator source and emit request v2**

Pass `source_id=config.source_id` and `evaluator_id=config.evaluator_id` into the image builder. Change `_build_evaluator_request` identity fields to:

```python
request = {
    "protocol_version": 2,
    "run_id": config.run_id,
    "source_id": config.source_id,
    "instance_id": config.instance_id,
    "evaluator_id": config.evaluator_id,
    # retain absolute paths, limits, repetitions, container protocol, image mode
}
```

Retain exact evaluator image ID binding for PyVISA v2 and FIBSEM. Call `validate_evaluator_report(report, config.source_id, config.evaluator_id, expected_run_id=...)`.

Add these final report fields:

```python
report["source_id"] = config.source_id
report["instance_id"] = config.instance_id
report["evaluator_id"] = config.evaluator_id
report["orchestration"]["evaluator_image"].update({
    "source_id": evaluator_image.source_id,
    "evaluator_id": evaluator_image.evaluator_id,
    "source_manifest_sha256": evaluator_image.source_manifest_sha256,
    "source_tree_sha256": evaluator_image.source_tree_sha256,
})
```

Make `dump_json` create grouped parent directories and publish atomically:

```python
def dump_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
```

Add `os` and `tempfile` imports to `contracts.py`.

- [ ] **Step 5: Move and rewrite all three configs**

Use `git mv`, then make path resolution account for one extra config directory level. The FIBSEM config must be exactly:

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

The PyVISA v1 config uses candidate `../../../evaluator/sources/pyvisa/pyvisa_dut_validation_v1/reference/solution.py` and report `../../reports/pyvisa/pyvisa_dut_validation_v1.json`. The PyVISA v2 config uses candidate `../../../evaluator/sources/pyvisa/pyvisa_dut_validation_v2/reference/solution.py` and report `../../reports/pyvisa/pyvisa_dut_validation_v2.json`. Both use `source_id: pyvisa`, `../../../instance`, and `../../../evaluator`; preserve their run IDs, timeouts, repetition settings, seeds, container protocol, and locked image mode.

- [ ] **Step 6: Update integration fixtures and run instrument unit tests**

Every generated integration config must use schema 2, include `source_id`, point at source-first leaves, and expect report schema versions 2/3/4. Run:

```bash
python -m pytest -q -m 'not openfibsem'
python -m pytest tests/test_fibsem_contracts.py tests/integration --collect-only -q
```

Expected: non-OpenFIBSEM unit suite PASS; FIBSEM and all integration tests collect.

- [ ] **Step 7: Commit source-bound orchestration and grouped configs**

```bash
git add schemas src configs reports tests
git commit -m "feat: bind benchmark runs to source"
```

Expected: one instrument-repository commit; all tracked configs are under `configs/<source_id>/`; the tracked report is under `reports/pyvisa/`.

### Task 7: Update validators, documentation, and active path references

**Files:**

- Modify: `instrument/scripts/validate_distributed_benchmark.py`
- Modify: `instrument/scripts/validate_fibsem_benchmark.py`
- Modify: `instrument/scripts/run_fibsem_linux_acceptance.sh`
- Modify: `instrument/tests/test_validation_script.py`
- Modify: `instrument/tests/test_fibsem_acceptance_runner.py`
- Modify: `instrument/README.md`
- Modify: `instrument/docs/distributed-contract.md`
- Modify: `instance/README.md`
- Modify: `instance/sources/openfibsem/fibsem_liftout_v1/ACCEPTANCE.md`
- Modify: `evaluator/README.md`
- Modify: active evaluator integration tests containing sibling instance paths

**Interfaces:**

- Consumes: source-grouped layout and report versions from Tasks 1-6.
- Produces: source-aware validation entry points and accurate operator instructions for Task 9.

- [ ] **Step 1: Write failing validator/default-path tests**

Assert these defaults and gates:

```python
assert parser_default == ROOT / "configs/openfibsem/fibsem_liftout_v1.yaml"
assert config.source_id == "openfibsem"
assert config.evaluator_id == "fibsem_liftout_v1"
assert report["schema_version"] == 4
```

For distributed validation, parameterize exact config paths:

```python
ROOT / "configs/pyvisa/pyvisa_dut_validation_v1.yaml"
ROOT / "configs/pyvisa/pyvisa_dut_validation_v2.yaml"
```

Add a validator failure where evaluator ID is FIBSEM but source ID is `pyvisa`.

- [ ] **Step 2: Run validator tests and verify path/version failures**

```bash
python -m pytest tests/test_validation_script.py tests/test_fibsem_acceptance_runner.py tests/test_fibsem_contracts.py -q
```

Expected: FAIL on old default paths, absent source checks, or old FIBSEM report schema 3.

- [ ] **Step 3: Update validator and acceptance script contracts**

Use these exact default paths:

```text
configs/pyvisa/pyvisa_dut_validation_v1.yaml
configs/pyvisa/pyvisa_dut_validation_v2.yaml
configs/openfibsem/fibsem_liftout_v1.yaml
```

Require the expected `(source_id, evaluator_id)` tuple in each specialized validator. In `run_fibsem_linux_acceptance.sh`, set:

```bash
config_arg=${1:-configs/openfibsem/fibsem_liftout_v1.yaml}
```

Change top-level report expectations to 2/3/4 and leave internal evidence schema versions unchanged.

- [ ] **Step 4: Update active documentation**

Document the canonical trees and the composite key. Use the exact FIBSEM commands:

```bash
python scripts/validate_fibsem_benchmark.py \
  --config configs/openfibsem/fibsem_liftout_v1.yaml
scripts/run_fibsem_linux_acceptance.sh \
  configs/openfibsem/fibsem_liftout_v1.yaml
```

Document report and artifact paths as:

```text
reports/openfibsem/fibsem_liftout_v1.json
reports/openfibsem/fibsem_liftout_v1.artifacts/{world_id}/{step_id}/
```

State explicitly that old flat config/leaf/report paths are invalid and there is no compatibility fallback. Do not rewrite historical plans/specs under `docs/superpowers/`.

- [ ] **Step 5: Scan active files for stale paths and run all local tests**

Run from `/Users/britenyyyang/benchmark`:

```bash
rg -n '(^|[ /])evaluators/|configs/fibsem_liftout_v1.yaml|configs/pyvisa_dut_validation|reports/fibsem_liftout_v1|source_family' \
  instance/.worktrees/fibsem-liftout-v1 \
  evaluator/.worktrees/fibsem-liftout-v1 \
  instrument/.worktrees/fibsem-liftout-v1 \
  --glob '!docs/superpowers/**' --glob '!*.git*'
```

Expected: no active stale-layout matches. Then run in each checkout:

```bash
python -m pytest -q
```

Expected: all platform-independent tests PASS; Docker/OpenFIBSEM tests may skip only through their declared platform/runtime markers.

- [ ] **Step 6: Commit validator and documentation updates in each affected repository**

Run in the instance checkout:

```bash
git add README.md sources/openfibsem/fibsem_liftout_v1/ACCEPTANCE.md
git commit -m "docs: describe source-grouped instances"
```

Run in the evaluator checkout:

```bash
git add README.md tests
git commit -m "docs: describe source-grouped evaluators"
```

Run in the instrument checkout:

```bash
git add README.md docs scripts tests
git commit -m "docs: publish source-aware run paths"
```

Expected: all three worktrees are clean.

### Task 8: Verify candidate-image stability and full local cross-repository contracts

**Files:**

- Modify only if a failing assertion exposes an implementation defect: the file named by that assertion in Tasks 1-7.
- Do not modify: any candidate `image.lock.yaml` unless a byte-level context diff is first recorded and reviewed.

**Interfaces:**

- Consumes: all local implementation commits.
- Produces: clean branch tips, unchanged candidate image locks, and a verified set of commands ready for remote native-Linux execution.

- [ ] **Step 1: Verify no candidate build input changed except path and manifest identity**

For each instance leaf, compare `container.context_files` hashes to actual bytes through the instance test suite, then run:

```bash
git diff HEAD~2..HEAD -- \
  sources/pyvisa/pyvisa_dut_validation_v1/Dockerfile \
  sources/pyvisa/pyvisa_dut_validation_v1/image.lock.yaml \
  sources/pyvisa/pyvisa_dut_validation_v2/Dockerfile \
  sources/pyvisa/pyvisa_dut_validation_v2/runtime \
  sources/pyvisa/pyvisa_dut_validation_v2/image.lock.yaml \
  sources/openfibsem/fibsem_liftout_v1/Dockerfile \
  sources/openfibsem/fibsem_liftout_v1/runtime \
  sources/openfibsem/fibsem_liftout_v1/image.lock.yaml
```

Expected: rename metadata only; no body changes. If Git displays a body change, stop and restore the original bytes with `apply_patch`, then rerun the instance hash tests.

- [ ] **Step 2: Run complete local suites from clean worktrees**

```bash
cd /Users/britenyyyang/benchmark/instance/.worktrees/fibsem-liftout-v1
python -m pytest -q
git status --short

cd /Users/britenyyyang/benchmark/evaluator/.worktrees/fibsem-liftout-v1
python -m pytest -q
git status --short

cd /Users/britenyyyang/benchmark/instrument/.worktrees/fibsem-liftout-v1
python -m pytest -q
git status --short
```

Expected: three passing suites and three empty status outputs.

- [ ] **Step 3: Validate all three canonical configs without running Docker**

Run a Python one-liner in the instrument checkout that loads each config and resolves both leaves:

```bash
python -c 'from pathlib import Path; from instrument_benchmark.contracts import load_run_config; from instrument_benchmark.repository_layout import resolve_instance_leaf, resolve_evaluator_leaf; paths=[Path("configs/pyvisa/pyvisa_dut_validation_v1.yaml"),Path("configs/pyvisa/pyvisa_dut_validation_v2.yaml"),Path("configs/openfibsem/fibsem_liftout_v1.yaml")]; [(lambda c:(resolve_instance_leaf(c.instance_checkout,c.source_id,c.instance_id),resolve_evaluator_leaf(c.evaluator_checkout,c.source_id,c.evaluator_id)))(load_run_config(p)) for p in paths]; print("3 source-bound configs valid")'
```

Expected: `3 source-bound configs valid`.

- [ ] **Step 4: Commit only verified defect fixes, if any**

If Steps 1-3 required a code correction, run the matching exact staging command in the affected clean worktree, then commit:

```bash
# instance repository
git add README.md pyproject.toml schemas sources tests

# evaluator repository
git add README.md pyproject.toml report.schema.json schemas sources tests instrument_benchmark_evaluator

# instrument repository
git add README.md schemas src configs reports scripts tests docs/distributed-contract.md

git commit -m "fix: satisfy source layout verification"
```

If no correction was needed, create no empty commit. Record the three passing test summaries for the execution handoff.

### Task 9: Sync incremental bundles and run native-Linux Docker acceptance

**Files:**

- Create outside Git repositories: `/Users/britenyyyang/benchmark/acceptance-results/fibsem-multi-source-formal-1/`
- Preserve: `/Users/britenyyyang/benchmark/acceptance-results/fibsem-formal-7/`
- Remote working root: `/home/yty/fibsem-acceptance-20260806`

**Interfaces:**

- Consumes: clean verified branch tips from Task 8 and the previously authorized SSH/Docker environment.
- Produces: native-Linux acceptance evidence for both PyVISA configs and two consecutive formal FIBSEM runs, plus a zero-managed-container audit.

- [ ] **Step 1: Record local commits and create incremental Git bundles**

Create three incremental bundles whose prerequisites are the already accepted remote tips:

```bash
local_evidence_root=/Users/britenyyyang/benchmark/acceptance-results/fibsem-multi-source-formal-1
test ! -e "$local_evidence_root"
mkdir -p "$local_evidence_root/bundles"
bundle_dir="$local_evidence_root/bundles"
git -C /Users/britenyyyang/benchmark/instance/.worktrees/fibsem-liftout-v1 bundle create "$bundle_dir/instance.incremental.bundle" feat/fibsem-liftout-v1 ^9c380e948f0b959e61ec6444eee368722d010b84
git -C /Users/britenyyyang/benchmark/evaluator/.worktrees/fibsem-liftout-v1 bundle create "$bundle_dir/evaluator.incremental.bundle" feat/fibsem-liftout-v1 ^efdc54b68efc448625d7022573dcaebdccbe8b34
git -C /Users/britenyyyang/benchmark/instrument/.worktrees/fibsem-liftout-v1 bundle create "$bundle_dir/instrument.incremental.bundle" feat/fibsem-liftout-v1 ^3be500cf6b999f1d05898ef3314aecda470902c5
git -C /Users/britenyyyang/benchmark/instance/.worktrees/fibsem-liftout-v1 bundle verify "$bundle_dir/instance.incremental.bundle"
git -C /Users/britenyyyang/benchmark/evaluator/.worktrees/fibsem-liftout-v1 bundle verify "$bundle_dir/evaluator.incremental.bundle"
git -C /Users/britenyyyang/benchmark/instrument/.worktrees/fibsem-liftout-v1 bundle verify "$bundle_dir/instrument.incremental.bundle"
```

Expected: three valid bundles with the stated prerequisite commits. The existing remote OpenFIBSEM checkout remains at the pinned commit and is not uploaded again.

- [ ] **Step 2: Upload bundles to the authorized yty directory**

```bash
ssh yty@118.180.19.234 'mkdir -p /home/yty/fibsem-acceptance-20260806/bundles/multi-source-formal-1'
scp "$bundle_dir/instance.incremental.bundle" "$bundle_dir/evaluator.incremental.bundle" "$bundle_dir/instrument.incremental.bundle" yty@118.180.19.234:/home/yty/fibsem-acceptance-20260806/bundles/multi-source-formal-1/
```

Expected: all three uploads complete under the authorized root. Do not upload or alter unrelated server directories.

- [ ] **Step 3: Materialize isolated remote checkouts from bundles**

On the server, first require the accepted bases and pinned OpenFIBSEM commit, then clone the existing repositories into a new isolated run root and fetch the incremental bundle tips:

```bash
run_root=/home/yty/fibsem-acceptance-20260806/runs/multi-source-formal-1
test ! -e "$run_root"
test "$(git -C /home/yty/fibsem-acceptance-20260806/instance rev-parse HEAD)" = 9c380e948f0b959e61ec6444eee368722d010b84
test "$(git -C /home/yty/fibsem-acceptance-20260806/evaluator rev-parse HEAD)" = efdc54b68efc448625d7022573dcaebdccbe8b34
test "$(git -C /home/yty/fibsem-acceptance-20260806/instrument rev-parse HEAD)" = 3be500cf6b999f1d05898ef3314aecda470902c5
test "$(git -C /home/yty/fibsem-acceptance-20260806/fibsem rev-parse HEAD)" = 2ebccb8b9721234ca66bb94de36d0f7cfe047af9
mkdir -p "$run_root"
git clone --no-hardlinks /home/yty/fibsem-acceptance-20260806/instance "$run_root/instance"
git clone --no-hardlinks /home/yty/fibsem-acceptance-20260806/evaluator "$run_root/evaluator"
git clone --no-hardlinks /home/yty/fibsem-acceptance-20260806/instrument "$run_root/instrument"
git clone --no-hardlinks /home/yty/fibsem-acceptance-20260806/fibsem "$run_root/fibsem"
git -C "$run_root/instance" fetch /home/yty/fibsem-acceptance-20260806/bundles/multi-source-formal-1/instance.incremental.bundle feat/fibsem-liftout-v1
git -C "$run_root/instance" checkout --detach FETCH_HEAD
git -C "$run_root/evaluator" fetch /home/yty/fibsem-acceptance-20260806/bundles/multi-source-formal-1/evaluator.incremental.bundle feat/fibsem-liftout-v1
git -C "$run_root/evaluator" checkout --detach FETCH_HEAD
git -C "$run_root/instrument" fetch /home/yty/fibsem-acceptance-20260806/bundles/multi-source-formal-1/instrument.incremental.bundle feat/fibsem-liftout-v1
git -C "$run_root/instrument" checkout --detach FETCH_HEAD
git -C "$run_root/fibsem" checkout --detach 2ebccb8b9721234ca66bb94de36d0f7cfe047af9
git -C "$run_root/instance" status --short
git -C "$run_root/evaluator" status --short
git -C "$run_root/instrument" status --short
git -C "$run_root/fibsem" status --short
```

Expected: four empty status outputs, three detached migration tips, and exact OpenFIBSEM commit `2ebccb8b9721234ca66bb94de36d0f7cfe047af9`.

- [ ] **Step 4: Run all repository tests and both PyVISA reference configs on Linux**

From the remote run root, create isolated Python environments, install each repository, and run:

```bash
acceptance_run_root=/home/yty/fibsem-acceptance-20260806/runs/multi-source-formal-1
mkdir -p "$acceptance_run_root/venvs"
mkdir -p "$acceptance_run_root/evidence"
set -o pipefail

cd /home/yty/fibsem-acceptance-20260806/runs/multi-source-formal-1/instance
python3 -m venv "$acceptance_run_root/venvs/instance"
"$acceptance_run_root/venvs/instance/bin/python" -m pip install -e . pytest
"$acceptance_run_root/venvs/instance/bin/python" -m pytest -q 2>&1 | tee "$acceptance_run_root/evidence/instance-tests.log"

cd /home/yty/fibsem-acceptance-20260806/runs/multi-source-formal-1/evaluator
python3 -m venv "$acceptance_run_root/venvs/evaluator"
"$acceptance_run_root/venvs/evaluator/bin/python" -m pip install -e . pytest
"$acceptance_run_root/venvs/evaluator/bin/python" -m pytest -q 2>&1 | tee "$acceptance_run_root/evidence/evaluator-tests.log"

cd /home/yty/fibsem-acceptance-20260806/runs/multi-source-formal-1/instrument
python3 -m venv "$acceptance_run_root/venvs/instrument"
"$acceptance_run_root/venvs/instrument/bin/python" -m pip install -e . pytest
"$acceptance_run_root/venvs/instrument/bin/python" -m pytest -q 2>&1 | tee "$acceptance_run_root/evidence/instrument-tests.log"
"$acceptance_run_root/venvs/instrument/bin/python" scripts/validate_distributed_benchmark.py --config configs/pyvisa/pyvisa_dut_validation_v1.yaml 2>&1 | tee "$acceptance_run_root/evidence/pyvisa-v1-validation.log"
"$acceptance_run_root/venvs/instrument/bin/python" scripts/validate_distributed_benchmark.py --config configs/pyvisa/pyvisa_dut_validation_v2.yaml 2>&1 | tee "$acceptance_run_root/evidence/pyvisa-v2-validation.log"
```

Expected: repository tests PASS; both PyVISA reference validators pass with report schema versions 2 and 3 at `reports/pyvisa/pyvisa_dut_validation_v1.json` and `reports/pyvisa/pyvisa_dut_validation_v2.json`.

- [ ] **Step 5: Run the two-run FIBSEM formal gate**

Run from the remote instrument checkout:

```bash
set -o pipefail
scripts/run_fibsem_linux_acceptance.sh configs/openfibsem/fibsem_liftout_v1.yaml 2>&1 | tee /home/yty/fibsem-acceptance-20260806/runs/multi-source-formal-1/evidence/fibsem-validation.log
```

Expected: the validator itself performs two clean ten-world runs and compares their semantic projections. Each run executes the nominal plus four hidden fixed scenarios and five deterministic seeded scenarios. The published run has score 100, strict pass, forty checkpoints, report schema 4, exact required merged `scene.glb`, SEM/FIB PNGs, `checkpoint.json`, merged-scene STL and component STLs, passing partial-order/terminal-state gates, and artifacts under `reports/openfibsem/fibsem_liftout_v1.artifacts/`. Its `validation.semantic_reproducibility` is true.

- [ ] **Step 6: Audit cleanup and collect acceptance evidence**

Run:

```bash
acceptance_run_root=/home/yty/fibsem-acceptance-20260806/runs/multi-source-formal-1
cd "$acceptance_run_root/instrument"
docker ps -a --filter label=iab.managed=true --format '{{.ID}} {{.Names}} {{.Status}}' | tee "$acceptance_run_root/evidence/managed-containers-after.txt"
cp reports/pyvisa/pyvisa_dut_validation_v1.json "$acceptance_run_root/evidence/"
cp reports/pyvisa/pyvisa_dut_validation_v2.json "$acceptance_run_root/evidence/"
cp reports/openfibsem/fibsem_liftout_v1.json "$acceptance_run_root/evidence/"
tar -C reports/openfibsem -czf "$acceptance_run_root/evidence/fibsem_liftout_v1.artifacts.tar.gz" fibsem_liftout_v1.artifacts
git -C "$acceptance_run_root/instance" rev-parse HEAD > "$acceptance_run_root/evidence/instance.commit"
git -C "$acceptance_run_root/evaluator" rev-parse HEAD > "$acceptance_run_root/evidence/evaluator.commit"
git -C "$acceptance_run_root/instrument" rev-parse HEAD > "$acceptance_run_root/evidence/instrument.commit"
git -C "$acceptance_run_root/fibsem" rev-parse HEAD > "$acceptance_run_root/evidence/openfibsem.commit"
docker version > "$acceptance_run_root/evidence/docker-version.txt"
```

Then run locally:

```bash
local_evidence_root=/Users/britenyyyang/benchmark/acceptance-results/fibsem-multi-source-formal-1
scp -r yty@118.180.19.234:/home/yty/fibsem-acceptance-20260806/runs/multi-source-formal-1/evidence "$local_evidence_root/remote-evidence"
```

Expected: empty output. Copy logs, the FIBSEM report and artifact manifest, its two-run semantic-reproducibility result, both PyVISA reports, Git commit/provenance records, test summaries, and the cleanup audit into `/Users/britenyyyang/benchmark/acceptance-results/fibsem-multi-source-formal-1/`. Do not overwrite `fibsem-formal-7`.

- [ ] **Step 7: Produce the final acceptance summary**

The summary must state the exact three repository commits, OpenFIBSEM commit, Docker Engine version, both PyVISA outcomes, both FIBSEM outcomes, source/evaluator image digests, artifact roots, and the zero-managed-container result. If any gate fails, retain its logs and report the first failing command without describing the migration as accepted.

---

## Final Verification Matrix

| Requirement | Primary proof |
|---|---|
| Symmetric source-first instance/evaluator trees | Tasks 1-2 source-layout tests |
| Required source manifests and bidirectional completeness | Tasks 1-2 adversarial registry tests |
| No flat lookup, fallback, symlink alias, or path escape | Task 4 strict resolver tests; Task 6 orchestration negative tests |
| One source key binds instance and evaluator | Tasks 3-4 composite dispatch/dependency tests |
| Protocol/schema version migration | Tasks 2-4 and 6 report/request tests |
| Only selected evaluator source enters image | Task 5 build-context exclusion tests |
| Source provenance is recorded | Tasks 5-6 build manifest and final report assertions |
| Configs/reports/artifacts grouped by source | Tasks 6-7 path tests and docs |
| Candidate behavior and image locks unchanged | Task 8 byte/hash verification |
| All three benchmark configs work on native Linux | Task 9 PyVISA and FIBSEM runs |
| FIBSEM is reproducible and cleans up | Task 9 two-run gate and empty managed-container audit |
