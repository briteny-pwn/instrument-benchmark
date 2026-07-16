# Integration episodes

These episodes model real scientific-instrument failure classes rather than
one expected patch. Their provenance points to upstream Micro-Manager PRs; the
local fixtures are explicitly marked `contract_projection` because they model
the observable device contract without copying vendor SDKs.

The primary submission is a directory containing a runnable `adapter.py`. It
may be a repair, a rewrite, or a transport wrapper. The evaluator never scores
textual similarity to the gold fixture; it scores behavior under injected
faults. Patch submission remains only for compatibility with the original
SWE-shaped instances.

Run the scenario harnesses:

```bash
python3 -c 'from pathlib import Path; from evaluator.episode import run_episode; print(run_episode(Path("episodes/iep_0001")))'
```

The three initial episodes cover stage timing/recovery, camera property
callback races, and per-device timeout/resource recovery.
