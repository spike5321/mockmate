# legacy/ · 早期形态归档

这个目录里的东西**不参与运行**，`orchestrator.py` 一行代码都不依赖它们。
留着是因为两件事：**提示词素材**和**可追溯的来路**。

> 想跑起来看效果，看[根目录 README](../README.md)；想改代码，看 [docs/architecture.md](../docs/architecture.md)。
> **这个目录是给你考古用的，不是给你上手的。**

---

## 为什么会有这个目录

MockMate 最初不是现在这个样子。它最早是**跑在 AgentTeams 平台上的配置包**——
包里只有一堆 `Agent.md`（角色定义）和 `SKILL.md`（技能定义），
真正的决策循环、工具调度、状态管理，全都由平台负责。换个说法：
**那时候这个"系统"没有自己的代码，只有提示词。**

现在的形态不一样了：决策循环是 `orchestrator.py` 自己写的 while 循环，
工具是 `agent/tools.py` 里进程内直接调的 8 个函数。
但从"平台配置包"到"自己的 Agent 系统"不是推倒重来——
**角色划分、职责边界、输出契约、状态机、选题策略，这些东西是在平台时代想清楚的，
全部保留了下来**，只是执行方式从"发消息给平台"换成了"自己调工具"。

这个目录就是那次转变的化石层。

---

## 里面有什么

| 路径 | 是什么 | 现在还有用吗 |
|---|---|---|
| `agents/` | 5 个 Agent 的角色定义（Lead + 4 个 Worker） | **有。** `agent/prompts.py` 的系统提示词就是从 `agents/interview-coordinator/Agent.md` 改写来的，改的只有"调度 Worker"→"自己调工具"这一处 |
| `skills/` | 11 个 Skill 的技能定义（输入/输出/依赖/失败处理） | **有。** 出题策略、评分维度、报告结构的原始设计都在这；`scenarios/*.json` 的 `scoring_rubric` 字段和它们是同一个来源 |
| `at/` | AgentTeams 运行配置与运行手册 | 少。只在你想知道"当年怎么跑起来的"时才需要 |
| `tools/mock_tool_server.py` | HTTP mock 工具网关 | 少。现在工具在进程内直调，不需要这层 HTTP 了 |
| `tools/MCP_MAPPING.md` | HTTP 工具 → 未来 MCP 工具的映射表 | 少。但对"这 8 个工具该对接什么真实服务"仍有参考价值 |
| `tools/tool_catalog.json` | 工具目录 | 少 |
| `article_zhihu.md` | 知乎文章草稿（`从 0 用 AgentTeams 搭一个多 Agent 模拟面试系统`） | ⚠️ **内容已过时**，见下 |
| `docs/500_words_brief.md` | 参赛作品简介（500 字） | ⚠️ **内容已过时**，见下 |

---

## 两个要注意的过时文件

`article_zhihu.md` 和 `docs/500_words_brief.md` **描述的都是平台配置包形态**，
里面写的"5 个 Agent + 11 个 Skill + HTTP 工具网关""Step 2 进行中"等说法，
和现在的代码（单循环 + 8 工具 + 已完成 5 个阶段）**已经对不上了**。

它们留在这里是当历史记录，**不要直接拿去发布或提交**——否则一读代码就露馅。
要重新对外写的话，素材应该取自根目录 `README.md`（那里的数字全部来自真实运行轨迹，可核对）。

---

## 那个转变，具体是改了什么

只改了**执行方式**，角色设计原样保留。对应关系：

| 平台时代 | 现在 |
|---|---|
| Lead 发消息调度 4 个 Worker | `orchestrator.py` 的 while 循环，模型自己决定调哪个工具 |
| Worker 通过 HTTP 访问 `tools/mock_tool_server.py` | 进程内直接调用 `agent/tools.py` 的 8 个函数 |
| 平台负责状态传递与轮次推进 | `ToolBox` 持有会话状态（`questions` / `records` / `pending_question`） |
| Skill 定义靠平台 Registry 加载 | 提示词直接写在 `agent/prompts.py`，选题/评分策略落在 `scenarios/*.json` 与 `tools/mock_tools.py` |

这段转变的完整记录见 `docs/architecture.md` 最后一节「为什么从 5 个 Agent 收敛成 1 个」。
