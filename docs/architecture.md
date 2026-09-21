# MockMate 架构说明

> 这份文档描述的是**当前形态**：决策循环由 `orchestrator.py` 自己实现，不依赖 AgentTeams / Element / Matrix。
> 早期基于平台的形态见 `agents/`、`skills/`、`at/` 三个目录（仅作提示词素材保留）。
>
> README 里是"能看懂"的版本，这里是"要上手改"的版本。

---

## 1. 一句话定位

**一个自己写的 ReAct 式调度循环**：把「对话历史 + 工具说明书」发给 LLM，
由 LLM 决定下一步是说话还是调工具，我们执行完把结果写回历史，循环到 LLM 自己调用 `end_interview` 为止。

没有 Agent 框架、没有 HTTP 工具网关、没有多进程编排。工具都是**进程内直调**。

---

## 2. 分层

```mermaid
flowchart TB
    subgraph L1["编排层 · orchestrator.py"]
        MAIN["主循环<br/>决策 · 分发 · 状态推进 · 预算提醒 · 收尾"]
    end
    subgraph L2["Agent 运行时 · agent/"]
        LLM["llm.py<br/>LLMClient.chat / embed"]
        TOOLS["tools.py<br/>TOOL_SCHEMAS + ToolBox"]
        PROMPT["prompts.py<br/>系统提示词"]
        CAND["candidate.py<br/>CandidateSim"]
        EVAL["evaluator.py<br/>AnswerEvaluator"]
    end
    subgraph L3["能力层"]
        KB["kb/ · 向量检索"]
        DATA["scenarios/ · 简历 题库 候选人脚本"]
        REND["tools/mock_tools.py · 报告渲染"]
    end
    subgraph L4["外部依赖"]
        ZHIPU["智谱 OpenAI 兼容端点<br/>chat/completions · embeddings"]
        CHROMA["Chroma 持久化向量库<br/>.kb/"]
    end
    MAIN --> LLM
    MAIN --> TOOLS
    MAIN --> PROMPT
    MAIN --> CAND
    TOOLS --> EVAL
    TOOLS --> KB
    TOOLS --> DATA
    TOOLS --> REND
    KB --> CHROMA
    LLM --> ZHIPU
```

**分层原则只有一条**：下层不知道上层的存在。
`kb/` 不知道谁在调它，`ToolBox` 不知道主循环长什么样，`LLMClient` 更不知道自己在扮演面试官。
所以每一层都能单独替换、单独测试。

---

## 3. 主循环

### 3.1 骨架

```python
while turn < max_turns and not toolbox.finished:
    turn += 1

    if 剩余轮数 <= 3 and 还没交报告:        # ⓪ 预算提醒
        注入一条 user 消息催它交报告

    reply = llm.chat(messages, tools=TOOL_SCHEMAS)   # ① 决策
    messages.append(reply.as_message())

    if reply.wants_tools:                  # ② 调工具
        for call in reply.tool_calls:
            ok, payload = toolbox.dispatch(name, args)
            messages.append({"role": "tool", "content": json.dumps(payload)})
        continue

    ...                                    # ③ 模型只是在说话 → 判断该不该给候选人回答的机会
```

### 3.2 三个必须理解的设计点

**① `messages` 是 Agent 唯一的记忆。**
每一轮都把整份历史重发一次。没有额外的"记忆模块"，也没有摘要压缩——
这是最简单、也最容易讲清楚的方案。代价是 token 随轮数线性增长（实测 32 轮约 27.8 万 in）。

**② 工具失败不抛异常。**
`dispatch()` 返回 `(ok, payload)`，业务错误（id 不存在、enum 非法）也走同一条通道写回 `messages`。
模型下一轮看到错误会自己换参数重试。**循环永远不会因为"模型调错了"而崩。**

**③ 停止条件由模型判断。**
`end_interview` 被调用时 `toolbox.finished = True`，循环自然退出。
`max_turns` 只是保险丝，不是正常退出路径。

### 3.3 分支 ③：该不该让候选人回答

这是整个循环里最容易写错的地方，三级判定：

| 顺序 | 条件 | 含义 |
|---|---|---|
| 1 | `toolbox.pending_question is not None` | 台上有题（刚 `pick_question` 出过）→ 必然是在提问 |
| 2 | 句子里有 `?` / `？` | 自由提问（项目深挖走这条） |
| 3 | `nod_streak >= 1` | 连着两轮没给出答案 → 强制给，防死循环的保险丝 |

命中任意一条 → 让 `CandidateSim` 作答，并以 `[候选人回答]` 前缀写回。
都不命中 → 注入「（候选人点了点头，等你提问。）」。

**为什么不用"有没有问号"单条判断？**
因为出题用的是「请实现……请说明……」这种祈使句，一个问号都没有。
第一版就是栽在这儿：模型被判成自言自语 → 注入点头 → 以为题没问出去 → 再问一遍……30 轮空转。

---

## 4. 会话状态

短期记忆全在 `ToolBox` 里，不散落：

| 字段 | 类型 | 用途 |
|---|---|---|
| `questions` | `dict[id, dict]` | 已出过的题。`score_answer` 靠它校验 id 合法性 |
| `records` | `list[dict]` | 逐题记录：题目 / 回答 / 分数 / 维度 / 评分来源 |
| `pending_question` | `dict \| None` | 台上有题待答（分支 ③ 的第一级判定） |
| `last_question` | `dict \| None` | 最近一道题。自由追问没有 id，靠它继承话题 |
| `custom_count` | `int` | 已登记的自拟题数量，用来生成 `custom-01` 这类合法 id |
| `report_path` | `str \| None` | 报告是否已落盘 |
| `finished` | `bool` | 循环退出标志 |

合法取值表是**写死在代码里**的常量（`VALID_TRACKS` / `VALID_DIFFICULTIES` / `VALID_STAGES`），
不是靠 Schema 里的 `enum`。原因见第 8 节的第 4 条。

---

## 5. 工具层

8 个工具，分三类：

| 类别 | 工具 | 说明 |
|---|---|---|
| 读取 | `read_resume` `fetch_jd` `search_jd_kb` | 简历、JD、向量检索（检索是**工具**，不是管线） |
| 出题 | `pick_question` `log_custom_question` | 题库题 / 自拟题登记（后者为了给项目深挖题一个合法 id） |
| 收尾 | `score_answer` `submit_report` `end_interview` | 逐题评分、交报告、结束 |

工具说明书就是标准的 JSON Schema（`TOOL_SCHEMAS`），直接塞进 `payload["tools"]`，
`tool_choice="auto"` 交给模型自己决定调不调。

---

## 6. 检索层（Agentic RAG）

```
knowledge/*.md  --(按 markdown 标题切小节)-->  chunks  --(embedding-3)-->  Chroma(.kb/, cosine)
                                                                               ↑
            面试官调 search_jd_kb(query)  --(同一个 embedding 模型)-->  向量查询 → top-k 片段
```

**和固定管线的分界线**：这里的检索结果不是被拼进 prompt 送给"答案生成器"，
而是作为**工具结果交回面试官自己**，由它决定查什么、查几次、怎么用。

检索层不抛异常：库是空的时候 `retrieve()` 返回 `[]`，由调用方回退到内置的少量情报。
"库没建"是**正常状态**，不是错误。

### 切分策略

先按 markdown 标题（`#` ~ `####`）切小节，小节内再按段落聚合到 400 字，超长段落带 80 字重叠硬切。
每条片段前缀带上所属小节标题（`【2. 缓存击穿】`）。

为什么值得单独说：原来的做法是"任意位置的 400 字"，
实测问「缓存击穿」命中的片段开头却是「缓存雪崩」的正文——两个小节被切开又拼在了一起，
语义被稀释，相似度全线偏低。改成按标题切之后，一个片段 = 一个知识点。

---

## 7. 评分链路

### 7.1 双模型、双客户端

| | 面试官 | 评分官 |
|---|---|---|
| 职责 | 出题、追问、收尾 | 单题判分 |
| 调用频率 | 每轮都调 | 每题一次（无状态） |
| 失败策略 | **必须成功**，`max_retries=4`（429 时共等 70s） | **可以降级**，`max_retries=2`（10s+20s 就放弃） |
| 模型 | `glm-4.5-flash` / `glm-4.5-air` | `glm-4-flash-250414`（`SCORE_MODEL`） |

分开的两个理由：**智谱的 429 按模型报**，各占一份额度不容易一起被打满；
以及"必须成功"和"可以降级"是两种诉求，共用一个客户端就只能二选一。

### 7.2 评分器内部流程

```
score_answer(question_id, answer)
  → 取出题目 + 自带 scoring_rubric
  → 只发三条信息给评分模型：题目 / 参考要点 / 这一条回答   ← 不带对话历史
  → 模型返回各维度达成度（0~1）
  → 覆盖率检查（< 60% → 判失败）
  → 代码按 rubric 权重算加权总分（10 分制）
  → 连续 2 次失败 → 熔断，后续直接走规则打分
```

**判卷看不到对话历史是刻意的**：防止光环效应（同一条答案放在不同位置分数不一样，就没法横向比较），
顺带省掉大量 token。副作用是评分调用**无状态**，可以单独重跑某一题。

**加权总分由代码算，不由模型算**：模型做判断很行，做算术不稳，
让它自己算总分十次里会错两三次，而且错得悄无声息。

---

## 8. 失败处理

| 场景 | 处理 | 结果 |
|---|---|---|
| 429 限流 | 单独用 10s 基数退避（10→20→40s） | 覆盖一次分钟级限流窗口 |
| 5xx / 网络异常 | 3s 基数退避 | — |
| 401 / 403 等非限流 4xx | **不重试**，直接抛错 | 是我们自己的问题，重试没意义 |
| 评分失败 | 退回规则打分，标 `source=rule-fallback` | 报告里看得出哪几题是降级的 |
| 评分连续失败 2 次 | 熔断，后续题直接规则打分 | 不拿整场面试赌一道题 |
| 主循环 LLM 挂掉 | `break` + `submit_partial_report()` | **交一份残缺但真实的报告，而不是空白** |
| 模型交出 0 道题 | 运行结束时明确报警 | 提示"评分链路未生效" |
| 模型没交报告 | 运行结束时明确报警 | 报告才是这个产品真正的交付物 |

> **降级不是丢人的事，假装没降级才是。**

---

## 9. 关键文件索引

| 想改什么 | 改哪 |
|---|---|
| 循环行为、预算提醒、中断策略 | `orchestrator.py` |
| 重试策略、超时、换供应商 | `agent/llm.py`（`RETRY_BASE` / `DEFAULT_BASE_URL`） |
| 加工具、改入参校验 | `agent/tools.py`（`TOOL_SCHEMAS` + `ToolBox`） |
| 面试官行为准则 | `agent/prompts.py` |
| 候选人的回答和"认输"时机 | `agent/candidate.py` + `scenarios/*.answers.json` |
| 评分标准、维度、降级门槛 | `agent/evaluator.py` |
| 切分粒度、入库 | `kb/store.py` |
| 检索条数、相似度 | `kb/search.py` |
| 语料 | `knowledge/*.md` → 改完跑 `python -m kb.build --rebuild` |
| 报告长什么样 | `tools/mock_tools.py`（`_render_markdown_report`） |

---

## 10. 扩展点

按"改动量从小到大"排：

1. **加一个场景** —— 复制 `scenarios/backend_intern.json` 改简历/JD/题库，再配一份 `.answers.json`（候选人脚本）。
2. **加一个工具** —— `TOOL_SCHEMAS` 里加一条 Schema，`ToolBox.dispatch()` 里加一个分支。**不用改主循环。**
3. **换模型 / 换供应商** —— `.env` 里改 `CHAT_MODEL`，或改 `DEFAULT_BASE_URL` 指向任何 OpenAI 兼容端点。
4. **加语料** —— 往 `knowledge/` 丢 markdown（或 PDF），`python -m kb.build --rebuild`。
5. **换 embedding** —— 抽一层 provider，注意维度变了必须重建库。
6. **多模型路由** —— 供应商注册表 + 错误分类 + 限流时中断询问用户 + checkpoint 断点续跑（路线图阶段 5）。
7. **Web 界面** —— `orchestrator.py` 的核心函数 `run_interview()` 与打印逻辑是分开的，可以直接被 Streamlit 调用。

---

## 11. 与早期形态的差异

| | 早期（平台配置包） | 现在 |
|---|---|---|
| 决策循环 | 跑在 AgentTeams 平台上 | `orchestrator.py` 自己实现 |
| 角色划分 | 5 个 Worker（Lead + 4 面试官） | **1 个 Agent**，靠工具和提示词分阶段 |
| 工具调用 | HTTP 工具网关（18090 端口） | 进程内直调 `ToolBox.dispatch()` |
| 上下文传递 | Lead 显式路由给 Worker | `messages` 一份历史全带 |
| Skill | 11 个独立 SKILL.md | 收敛进 `agent/prompts.py` 和工具实现 |
| 评分 | mock 按字数打分 | LLM 判断维度 + 代码算加权分 |

**为什么从 5 个 Agent 收敛成 1 个？**
因为"多 Agent"在早期形态里是**平台强制的形态**（每个 Worker 是一个独立会话），
不是问题本身需要的。真正的难点在"多轮时序 + 工具路径 + 失败恢复"，
这些在一个循环里反而更清楚。等单循环跑稳了，再按需拆——**而不是先拆再想为什么拆。**
