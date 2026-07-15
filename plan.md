---

# 第一阶段目标

构建一个最小可运行版本：

**IAB-Sim-MVP：Simulation-first Instrument Access Benchmark**

目标产物：

```text
1. 一个 benchmark 仓库骨架；
2. 一套真实 issue/PR 候选挖掘脚本；
3. 一套 instance 元数据 schema；
4. 至少 20 个候选真实仪器接入问题；
5. 至少 5 个人工可审查的 Verified Candidate；
6. 至少 2–3 个可以本地运行的 executable instance；
7. 每个 executable instance 满足：
   - pre-fix code + simulator → fail
   - gold patch + simulator → pass
   - model patch 可被自动评测
```

第一阶段不要追求数量，先证明 pipeline 可行。

---

# 总体执行原则

CodeAgent 必须遵守下面规则：

```text
1. 不人工编造 instance。
2. 每个 instance 必须来自真实已解决 issue / PR / commit。
3. 每个 instance 必须有 pre-fix commit 和 post-fix commit。
4. 第一阶段不依赖真实仪器。
5. evaluation 必须可执行，不能只靠人工判断。
6. 优先选择能用 mock、simulator、soft device、trace replay 复现的问题。
7. 暂时不做 Level 1，也就是不做“给文档从零写 SDK”的干净题。
8. 优先做 driver repair、framework integration、version compatibility、state/timing bug。
```

---

---

# 阶段 0：初始化仓库和数据 schema

## 0.1 建立 instance schema

创建 `docs/instance_schema.md` 和 JSON schema。每个 instance 至少包含：

```json
{
  "instance_id": "iab_0001",
  "source_project": "",
  "source_repo": "",
  "source_type": "resolved_issue_plus_pr",
  "issue_url": "",
  "pr_url": "",
  "pre_fix_commit": "",
  "post_fix_commit": "",
  "gold_patch_commit": "",
  "instrument_category": "",
  "task_type": "",
  "failure_modes": [],
  "framework": "",
  "language": "",
  "simulator_type": "",
  "requires_real_hardware": false,
  "given_to_model": {
    "issue_text": true,
    "failure_log": true,
    "docs_excerpt": true,
    "pre_fix_code": true,
    "simulator": true
  },
  "hidden_from_model": {
    "gold_patch": true,
    "post_fix_commit": true,
    "hidden_tests": true
  },
  "reproduction": {
    "pre_fix_fails": null,
    "gold_patch_passes": null,
    "command": ""
  },
  "difficulty_evidence": {
    "files_changed_by_gold": 0,
    "layers_touched": [],
    "requires_state_reasoning": false,
    "requires_async_reasoning": false,
    "requires_framework_semantics": false,
    "requires_safety_constraints": false
  },
  "evaluation_layers": [
    "fail_to_pass",
    "regression",
    "state_trace",
    "gold_differential",
    "minefield"
  ],
  "status": "candidate"
}
```

## 0.2 定义任务类型

`task_type` 固定为下面几类：

```text
real_bug_repair
version_compatibility
framework_semantic_integration
multi_device_integration
safety_critical_integration
```

不要加入 `protocol_to_sdk_basic`，因为第一阶段不做 Level 1。

## 0.3 定义 failure modes

固定标签：

```text
state_machine
async_timing
timeout
stale_data
firmware_version_skew
framework_semantic_mismatch
resource_conflict
metadata_mismatch
device_initialization
error_recovery
safety_boundary
multi_device_sync
```

---

# 阶段 1：候选来源挖掘

第一阶段不要全网乱搜，先固定几个高价值开源来源。

## 1.1 第一批 source repos

在 `configs/sources.yaml` 中配置：

```yaml
sources:
  - name: ophyd
    repo: bluesky/ophyd
    priority: high
    language: python
    domain: scientific_control

  - name: bluesky
    repo: bluesky/bluesky
    priority: medium
    language: python
    domain: experiment_orchestration

  - name: qcodes
    repo: microsoft/Qcodes
    priority: high
    language: python
    domain: instrument_drivers

  - name: qcodes_contrib_drivers
    repo: QCoDeS/Qcodes_contrib_drivers
    priority: high
    language: python
    domain: instrument_drivers

  - name: pymeasure
    repo: pymeasure/pymeasure
    priority: high
    language: python
    domain: instrument_drivers

  - name: instrumentkit
    repo: instrumentkit/InstrumentKit
    priority: medium
    language: python
    domain: instrument_drivers

  - name: areaDetector
    repo: areaDetector/areaDetector
    priority: high
    language: c_cpp_epics
    domain: detector_control

  - name: ADSimDetector
    repo: areaDetector/ADSimDetector
    priority: high
    language: c_cpp_epics
    domain: detector_simulation

  - name: micro_manager
    repo: micro-manager/micro-manager
    priority: high
    language: cpp
    domain: microscopy_device_adapters
```

建议第一批**可执行 instance 优先从 Python 生态做**，因为环境更容易跑通：

```text
ophyd
QCoDeS
qcodes_contrib_drivers
PyMeasure
InstrumentKit
```

Micro-Manager 和 areaDetector 先做 candidate mining，不急着做 executable instance，因为 C++/EPICS 编译成本更高。

---

## 1.2 GitHub issue/PR 挖掘关键词

CodeAgent 实现 `scripts/mine_github_issues.py`。

关键词组合：

```text
instrument driver
device adapter
camera adapter
stage adapter
detector
acquire
trigger
read
timeout
firmware
SCPI
VISA
serial
GPIB
EPICS
PV
IOC
asyn
areaDetector
ophyd
bluesky plan
qcodes parameter
snapshot
stale data
metadata
interlock
```

优先搜索 closed issue 和 merged PR。

候选必须尽量满足：

```text
issue 是 closed；
PR 是 merged；
issue 和 PR 能关联；
PR 修改的是 driver / adapter / device / simulator / control layer；
PR 中有测试、日志、复现描述或明确行为变化；
```

---

# 阶段 2：候选过滤与评分

实现 `scripts/score_candidates.py`。

## 2.1 硬性过滤

排除：

```text
1. 纯 README / 文档修改；
2. 纯格式化；
3. 拼写修复；
4. 只改 import；
5. 只改 CI；
6. 只升级依赖；
7. 没有明确仪器、设备、driver、adapter、PV、detector、camera、stage 等对象；
8. 必须连接真实硬件才能复现；
9. 使用私有 SDK 或私有说明书；
10. 没有 pre-fix / post-fix commit。
```

## 2.2 难度评分

每个候选打分，总分 100。

```text
真实来源证据：20
- 有 issue：5
- 有 merged PR：5
- issue 与 PR 明确关联：5
- 有开发者讨论 / 复现日志：5

仪器接入相关性：20
- 涉及 driver / adapter / device support：8
- 涉及真实仪器类型：5
- 涉及控制框架语义：5
- 涉及数据采集或设备状态：2

难度证据：25
- 修改超过 1 个文件：5
- 涉及状态机 / 异步 / timeout：5
- 涉及版本兼容：4
- 涉及 metadata / stale data：4
- 涉及 framework lifecycle：4
- 涉及错误恢复或资源释放：3

可仿真性：25
- 可用 mock/simulator 复现：10
- 可构造 trace replay：5
- 可构造 stateful simulator：5
- 不需要真实硬件：5

评估可执行性：10
- PR 已有测试：4
- 可写 fail-to-pass test：3
- 可写 regression test：3
```

候选等级：

```text
score >= 80: Verified Candidate 优先
65 <= score < 80: Candidate
50 <= score < 65: Reserve
score < 50: Drop
```

---

# 阶段 3：构造 Verified Candidate

目标：先产出 5 个 Verified Candidate。

每个候选生成一个目录：

```text
data/verified_candidates/iab_xxxx/
├── candidate.json
├── issue.md
├── pr_summary.md
├── diff_summary.md
├── reproduction_plan.md
└── difficulty_analysis.md
```

## 3.1 每个 Verified Candidate 必须回答

`difficulty_analysis.md` 中必须写清楚：

```text
1. 这个问题为什么属于仪器接入？
2. 它不是普通软件 bug 的原因是什么？
3. 它涉及哪类真实仪器或控制框架？
4. gold patch 解决了什么问题？
5. 难度来自哪里？
   - 状态机？
   - 异步？
   - firmware 差异？
   - framework semantic mismatch？
   - 多设备同步？
   - safety constraint？
6. 第一阶段如何用仿真复现？
7. evaluation oracle 从哪里来？
```

---

# 阶段 4：构造第一个 executable instance

不要一开始做 10 个。先跑通 1 个完整闭环。

## 4.1 优先选择标准

第一个 executable instance 建议满足：

```text
1. Python 项目；
2. 依赖少；
3. 有现成测试或容易写测试；
4. 不需要真实硬件；
5. 可以用 mock object / fake instrument / trace replay 复现；
6. gold patch 较清晰；
7. failure mode 不是 one-line fix。
```

优先方向：

```text
QCoDeS driver bug
PyMeasure instrument bug
Ophyd simulated device bug
InstrumentKit driver bug
```

暂时不要第一个就做 Micro-Manager 或 EPICS。

---

## 4.2 每个 executable instance 的目录结构

```text
instances/iab_0001/
├── instance.json
├── problem.md
├── Dockerfile
├── setup.sh
├── reproduce_pre_fix.sh
├── apply_gold_patch.sh
├── evaluate.sh
├── repository/
│   └── source code snapshot
├── simulator/
│   ├── fake_device.py
│   └── config.json
├── tests/
│   ├── test_fail_to_pass.py
│   ├── test_regression.py
│   ├── test_state_trace.py
│   └── test_minefields.py
├── patches/
│   └── gold.patch
└── expected/
    ├── gold_trace.json
    └── expected_state.json
```

---

## 4.3 problem.md 模板

模型看到的任务描述：

```markdown
# Task

You are given a pre-fix version of an instrument integration project.

The issue report describes a failure in instrument access. Your task is to modify the code so that the driver / adapter / device integration behaves correctly.

## Source Context

- Project:
- Instrument category:
- Framework:
- Failure type:

## Issue Description

<issue text, cleaned but not revealing PR>

## Failure Log

<log>

## Relevant Documentation

<manual excerpt or framework docs excerpt>

## Expected Behavior

The patched implementation should:

1. ...
2. ...
3. ...

## Constraints

- Do not hard-code simulator responses.
- Do not remove existing public APIs.
- Do not bypass the instrument state model.
- Do not ignore timeout or error states.
- Preserve existing behavior.
```

不要给 PR 链接、commit 链接、gold diff。

---

# 阶段 5：Evaluation Harness

实现 `evaluator/`。

## 5.1 Fail-to-pass

`tests/test_fail_to_pass.py`

验证原始 issue 是否被解决。

例子：

```text
pre-fix:
  fails because detector read returns stale frame

model patch:
  should wait for new frame before read
```

## 5.2 Regression

`tests/test_regression.py`

验证原有行为没被破坏。

```text
已有 init / close / read / write / snapshot / metadata 行为仍然正确。
```

## 5.3 State trace

`tests/test_state_trace.py`

记录模型 patch 与 simulator 的交互轨迹。

轨迹格式：

```json
[
  {
    "time": 0,
    "action": "connect",
    "state_before": "disconnected",
    "state_after": "idle"
  },
  {
    "time": 1,
    "action": "set_exposure",
    "value": 50,
    "state_before": "idle",
    "state_after": "idle"
  },
  {
    "time": 2,
    "action": "trigger",
    "state_before": "idle",
    "state_after": "acquiring"
  }
]
```

## 5.4 Gold differential

`evaluator/trace_compare.py`

比较：

```text
gold patch trace
model patch trace
```

允许实现不同，但行为必须等价。

比较维度：

```text
1. 最终设备状态；
2. 关键命令顺序；
3. 是否等待异步完成；
4. 是否读取新数据而不是旧数据；
5. metadata 是否一致；
6. timeout 和 error path 是否一致；
7. cleanup 是否一致。
```

## 5.5 Minefield

`tests/test_minefields.py`

检查危险行为：

```text
1. acquiring 状态修改关键参数；
2. busy 状态直接 read；
3. 忽略 timeout；
4. 无限 retry；
5. 硬编码测试值；
6. 不释放连接；
7. 把异常吞掉但不恢复状态。
```

---

# 阶段 6：第一阶段验收标准

CodeAgent 完成第一阶段后，仓库应满足：

## 6.1 数据侧验收

```text
至少 20 个 scored candidates；
至少 5 个 verified candidates；
每个 verified candidate 有：
- issue / PR / commit 来源；
- 难度分析；
- 仿真复现方案；
- evaluation oracle 说明。
```

## 6.2 工程侧验收

```text
至少 2–3 个 executable instances；
每个 executable instance 可以运行：

bash setup.sh
bash reproduce_pre_fix.sh
bash apply_gold_patch.sh
bash evaluate.sh
```

并满足：

```text
pre-fix fails；
gold patch passes；
model patch 可以被替换后评测；
evaluation report 可以生成 JSON。
```

## 6.3 报告侧验收

生成：

```text
docs/phase1_report.md
```

内容包括：

```text
1. instance 来源统计；
2. 候选过滤规则；
3. 5 个 verified candidate 详情；
4. 2–3 个 executable instance 详情；
5. 仿真方式；
6. evaluation layers；
7. 当前局限；
8. 第二阶段 real calibration 的预留接口。
```

---



# 第一阶段最小时间线

如果按一个 CodeAgent 连续执行，可以拆成四个里程碑：

```text
Milestone 1：仓库骨架 + schema + sources.yaml
Milestone 2：候选挖掘脚本 + 20 个 scored candidates
Milestone 3：5 个 verified candidates + difficulty analysis
Milestone 4：2–3 个 executable instances + evaluator + phase1_report
```

优先级最高的是 **Milestone 2 和 Milestone 4**。只要这两个打通，benchmark 的核心可信链路就成立：

```text
真实 issue / PR
→ 修复前代码
→ 仿真复现失败
→ gold patch 通过
→ model patch 自动评测
```
