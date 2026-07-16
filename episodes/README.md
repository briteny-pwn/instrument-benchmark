# Integration episodes

These episodes model real scientific-instrument failure classes rather than
one expected patch. Their provenance points to upstream Micro-Manager PRs; the
local fixtures are explicitly marked `contract_projection` because they model
the observable device contract without copying vendor SDKs.

Run the scenario harnesses:

```bash
python3 -c 'from pathlib import Path; from evaluator.episode import run_episode; print(run_episode(Path("episodes/iep_0001")))'
```

The three initial episodes cover stage timing/recovery, camera property
callback races, and per-device timeout/resource recovery.
