# Executable repair instances

Each `iab_NNNN` directory is a self-contained repair benchmark derived from a real closed issue and merged pull request. The candidate edits exact pre-fix upstream files under `repository/`; this is not a from-scratch protocol-client task. `source_manifest.json` records the pre-fix commit and full Git blob hashes for every included file.

Required contents:

```text
instance.json
problem.md
Dockerfile
setup.sh
reproduce_pre_fix.sh
apply_gold_patch.sh
evaluate.sh
repository/
simulator/
tests/
patches/gold.patch
expected/
```

The committed `repository/` is immutable benchmark input. `setup.sh` copies it to ignored `.work/repository`. Gold and candidate patches are applied only to that copy.

The normal audit lifecycle is:

```bash
cd instances/iab_0001
bash setup.sh
bash reproduce_pre_fix.sh
bash apply_gold_patch.sh
bash evaluate.sh
```

To score a candidate patch from a clean pre-fix copy, pass it directly to `evaluate.sh`. The JSON report contains independent fail-to-pass, regression, state-trace, gold-differential, and minefield results.

The earlier source-family/manual/raw-protocol bundles have moved to `legacy/level1/instances` and are not current benchmark instances.
