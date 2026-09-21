# 运行证据

这个目录是一次**完整运行**的原始产物，用来支撑 README 第 3 节的实测数据。
它们平时是 `gitignore` 掉的（`traces/` 和 `scenarios/*.report.*`），这里各留了一份，方便核对。

| 文件 | 是什么 |
|---|---|
| `run14_trace.json` | 决策轨迹。包含本次运行的 `summary` 和逐轮的 `thinking` / `content` / `tool_calls` |
| `run14_report.json` | 本次运行落盘的复盘报告（结构化，`docs/replay/` 的雷达图与逐题明细读它） |
| `run14_report.md` | 同一份报告的 markdown 版本（给人读的） |

这两份 JSON 还有第二个用途：**[运行回放页](../replay/index.html) 就是由它们生成的**。

```bash
python tools/build_replay.py    # 读上面两个文件 → 生成 docs/replay/index.html
```

所以回放页里的每一个数字、每一句话都能追溯到这两个文件；
重新生成一份与仓库里的比对，就能确认页面没有被手工美化过。

**这次运行的条件**

| 项 | 值 |
|---|---|
| 场景 | `backend_intern` |
| 面试官模型 | `glm-4.5-air` |
| 评分模型 | `glm-4-flash-250414` |
| token 用量 | 278364 in + 5860 out |

**这些数字怎么核对**

```bash
python -u orchestrator.py --scenario backend_intern
```

跑完注意三件事：终端最后的统计块、`traces/` 下新生成的轨迹文件、`scenarios/backend_intern.report.md`。
每次运行的题目和分数都会变（模型有随机性），但**规模量级和链路结构是一致的**。

一点说明：`glm-4-flash-250414` 只用来判卷，**不要**拿它当面试官——
它不会按多轮时序调用工具，会全程自己编题（README 第 6 节第 12 条）。
