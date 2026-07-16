# Integration episode design

An integration episode evaluates a device contract under timing, fault and
recovery scenarios. It is not a gold-patch similarity task. The upstream issue
or PR supplies the real failure evidence; `fixture_kind=contract_projection`
records when the local fixture is a deterministic projection of that evidence
rather than a verbatim upstream checkout.

Each scenario declares required observable events. The harness injects faults
such as delayed completion, disconnect, stale property reads or concurrent
shutdown, then scores the resulting behavior trace. A valid implementation may
use any design that satisfies the contract.

The episode score is a weighted scenario score. `strict_pass` requires every
required scenario. Build and patch application are infrastructure gates and
are reported separately from behavior capability.

模型 patch 在隔离副本中评测，不要求复现 gold patch：

```bash
python3 -c 'from pathlib import Path; from evaluator.episode import run_episode; print(run_episode(Path("episodes/iep_0001"), Path("/absolute/model.patch")))'
```
