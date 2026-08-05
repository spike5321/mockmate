# 从 0 用 AgentTeams 搭一个多 Agent 模拟面试系统

> 参加 GOAI 世界人工智能开源大赛 Agent Infra 赛道的实战记录。一个代码小白，怎么从 0 到 1 用多 Agent 框架搭出一个能跑通面试流程的模拟面试系统。

## 为什么做这个

每到大三下、大四上，朋友圈就被两类内容刷屏：刷题打卡的，和吐槽面试挂了的。我自己明年也要找工作，发现一个很现实的问题——

**想练面试，但没地方练。**

- 找学长朋友陪练？大家都很忙，欠人情
- 报付费模拟面试班？动辄 5000-10000，还未必对口
- 自己对着镜子练？没有反馈，等于白练

正好看到 Datawhale 办的 GOAI 大赛有个 Agent Infra 赛道，要求用 AgentTeams 框架做多 Agent 协作。我想，能不能用多 Agent 搭一个免费的 AI 面试官？每个 Agent 扮演一个面试环节的角色，串起来就是一场完整的模拟面试。

这就是 MockMate（面试官联盟）的由来。

## 一、AgentTeams 是什么

先简单说下 AgentTeams。这是 Datawhale 推出的多 Agent 协作框架，核心思路是：

- **Agent**：一个有明确职责的 AI 角色，有自己的 mission、能用的 skill、能调的 tool
- **Skill**：告诉 Agent「遇到某类任务该怎么做」的说明书，用 Markdown 写
- **Tool**：Agent 调用的外部能力（读简历、查题库、评分等），可以是 HTTP 接口或 MCP Server
- **Team**：把多个 Agent 组织起来，由一个 TeamLeader 调度

和单 Agent（比如直接用 ChatGPT 聊天）的区别在于：单 Agent 是一个人干所有事，多 Agent 是分工协作——每个 Agent 只管自己那一段，做完了交给下一个。这更像真实的面试：HR 不问算法题，技术面试官不问你职业规划。

## 二、5 个 Agent 怎么分工

面试这件事天然适合拆成多个角色。我设计了 5 个 Agent：

| Agent | 职责 | 用的工具 |
|---|---|---|
| **Lead**（mockmate-leader） | 纯调度，不碰工具 | 无 |
| **Resume Analyst** | 读简历 + 对齐 JD + 找技能缺口 | mock_resume / mock_jd / rag:jd_kb |
| **Tech Interviewer** | 3 轮技术面：算法 / 系统设计 / 项目深挖 | mock_question_bank / rag:jd_kb / mock_evaluator |
| **HR Interviewer** | 4 阶段行为面：自我介绍 / 动机 / 压力 / 规划 | mock_question_bank / mock_evaluator |
| **Feedback Coach** | 6 维评分 + 7 天训练计划 | mock_evaluator / mock_report |

**为什么 Lead 不兼任业务角色？** 这是踩过坑后的决定。一开始我想让 Lead 既调度又顺便做简历分析，结果发现：Lead 一旦陷进具体业务，就顾不上调度下一个 Agent，整个流程会卡住。后来改成 Lead 只管发指令和汇总结果，业务全交给 4 个 Worker，流程立刻顺了。

**Lead 的状态机长这样**：

```
收到任务 → 派简历分析 → 派技术面 → 派 HR 面 → 派复盘 → 汇总回复
```

每个状态切换都有明确的输入输出契约，下一个 Agent 拿到的就是上一个 Agent 的产出。比如 Tech Interviewer 拿到的是 Resume Analyst 输出的「技能缺口 + 面试重点」，而不是原始简历——这样它出题就有针对性。

## 三、11 个 Skill 怎么设计

Agent 光有职责不够，还得告诉它「具体怎么做」。这就是 Skill 的作用。

我给 5 个 Agent 写了 11 个 SKILL.md，比如：

- `resume-parser`：教 Resume Analyst 怎么从简历文本里提取技能栈
- `coding-question-picker`：教 Tech Interviewer 怎么根据 JD 选算法题
- `behavioral-question-picker`：教 HR Interviewer 怎么按 STAR 框架出行为面问题
- `answer-evaluator`：教 Feedback Coach 怎么给答案打分（要引用证据）

**所有 Skill 用同一套模板**：

```
Purpose   —— 这个 Skill 干什么
Inputs    —— 需要什么输入
Procedure —— 具体步骤（编号列表）
Output    —— 输出什么格式
Gates     —— 质量门禁（不达标怎么办）
```

这套模板最大的好处是**可复用**。比如 `answer-evaluator` 这个 Skill，技术面和 HR 面都要用——它定义的是「怎么评分」这个通用能力，而不是某个具体题目。换个面试场景（比如产品岗面试），Skill 几乎不用改，只要换题库和 JD 就行。

**质量门禁（Quality Gates）是我觉得最关键的设计**。举个例子，`answer-evaluator` 的门禁里有一条：「每个评分必须引用 evidence_refs（题目 ID 或答案原文位置）」。这意味着 Agent 不能说「这个回答 6 分」就完了，它得说「回答第 3 行提到了 X，但 JD 要求 Y，所以 6 分」。这样评分才有依据，也能防止 LLM 幻觉。

## 四、工具网关：先 mock 后真实

Agent 要干活就得调工具。但开发阶段，真实工具（比如真实 JD 数据库、真实 LLM 评分）不一定有，而且调一次要花钱。我的做法是**先 mock**：

写了一个 HTTP 服务（端口 18090），里面是 8 个 mock 工具函数：

- `mock_resume.read_resume` —— 返回一个写死的简历
- `mock_jd.fetch_jd` —— 返回一个写死的 JD
- `mock_jd.search_jd_kb` —— 模拟 RAG 检索（从 4 条数据里捞）
- `mock_question_bank.pick` —— 从题库里抽题
- `mock_evaluator.score_answer` —— 给答案打分
- `mock_evaluator.cross_check` —— 交叉验证
- `mock_report.render` —— 生成报告

统一协议长这样：

```
POST /tools/{scenario_id}/{tool}.{function}
```

比如调用读简历就是 `POST /tools/backend_intern/mock_resume.read_resume`。

**为什么这么设计？** 因为未来要替换成真实工具时，只需要在 `tool_catalog.json` 里把 mock 的地址换成真实 MCP Server 地址，Agent 代码一行都不用改。这就是 mock 的价值——开发阶段不依赖外部，上线阶段平滑迁移。

我已经把 5 个 mock 工具的 MCP 映射写好了：

| mock 工具 | 未来映射到 |
|---|---|
| mock_resume.read_resume | user.profile.read（真实用户系统） |
| mock_jd.fetch_jd | recruiter.jd.search（招聘平台 API） |
| mock_jd.search_jd_kb | vector.search（向量检索 MCP） |
| mock_question_bank.pick | quiz.bank.query（题库服务） |
| mock_evaluator.score_answer | llm.judge.score（LLM 评分服务） |
| mock_report.render | doc.report.render（文档生成 MCP） |

## 五、跑通了，看结果

写完代码第一件事是跑通端到端。我用一个写死场景测试：张三（985 CS 大三，GPA 3.6）面字节后端实习。

跑了 19 次工具调用，0 失败：

| 阶段 | 调了什么 | 结果 |
|---|---|---|
| 简历分析 | 3 个工具 | 提取 8 项技能，命中 2 条 RAG |
| 技术面 | 6 次调用（3 出题 + 3 评分） | 算法 8 / 系统设计 8 / 项目深挖 6 |
| HR 面 | 8 次调用（4 出题 + 4 评分） | 自我介绍 8 / 动机 6 / 压力 6 / 规划 6 |
| 复盘 | 2 个工具 | 生成 Markdown + JSON 双格式报告 |

最终报告输出：

- **综合分**：69/100
- **6 维雷达**：tech_depth 80 / system_design 80 / coding 80 / behavioral 65 / project_pitch 60 / motivation_fit 60
- **结论**：建议补技能后投递
- **7 天训练计划**：从复盘短板 → 重写项目经历 → 系统设计练习 → 刷题 → 模拟二面

看到报告生成的那一刻，挺有成就感的——一个完整的面试闭环跑通了。

## 六、踩过的坑

**坑 1：PPT 渲染引擎装不上**。slidep 是 Node.js 工具，依赖 canvas（要 C++ 编译），Windows 上死活装不上。最后换回 python-pptx 直接生成，10 分钟搞定。教训：能用 Python 就别折腾 Node 原生编译。

**坑 2：一开始 Skill 想塞太多**。最早写的 `resume-parser` 想同时做简历解析、技能提取、JD 匹配三件事，结果 Prompt 又长又乱，LLM 经常漏步骤。后来拆成三个独立 Skill（resume-parser / skill-extractor / jd-matcher），每个只干一件事，立刻清爽了。

**坑 3：评分没证据=幻觉**。第一版 Feedback Coach 输出的评分是光秃秃的「6 分」「8 分」，但为什么是这个分说不清。加了 `evidence_refs` 门禁后，每个评分必须引用题目 ID 或答案原文，评分才有说服力，也方便人工复核。

## 七、接下来

项目已经开源在 GitHub，当前是 baseline 版本，接下来打算：

1. **接真实 LLM**：把 mock_evaluator 换成真实大模型评分
2. **扩充题库**：现在只有后端实习场景，要加产品岗、运营岗、算法岗
3. **跑完整 AgentTeams Demo**：现在只是工具层跑通，要跑真实的 5 Agent 协作录视频
4. **迁移 MCP**：把 5 个 mock 工具逐步换成 MCP Server 实现

如果你也在准备面试，或者想入门多 Agent 开发，欢迎来 GitHub 看代码、提 issue。MockMate 的目标是：**让每个学生都有一位免费的 AI 面试官。**

---

**标签**：#GOAI大赛 #阿里云 #Agent Infra #Datawhale

**大赛信息**：GOAI 世界人工智能开源大赛 - Agent Infra 赛道，由 Datawhale 主办，阿里云提供算力支持。
