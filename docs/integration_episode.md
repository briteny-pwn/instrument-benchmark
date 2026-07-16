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

patch 只是兼容入口。推荐的提交形式是一个可运行的 adapter 目录；模型
可以重写 adapter、增加 transport wrapper 或实现自己的状态机，不需要
知道 pre-fix 文件，也不需要复现 gold patch：

```bash
python3 -c 'from pathlib import Path; from evaluator.episode import run_episode; print(run_episode(Path("episodes/iep_0001"), submission=Path("/absolute/submission")))'
```

旧式模型 patch 仍可作为兼容入口：

```bash
python3 -c 'from pathlib import Path; from evaluator.episode import run_episode; print(run_episode(Path("episodes/iep_0001"), Path("/absolute/model.patch")))'
```

这使任务从“修复某个文件”转为“交付一个满足设备行为契约的接入实现”。
评测关注状态、时序、故障恢复和资源释放，而不是 diff 形状。
