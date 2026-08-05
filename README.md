# MockMate · 面试官联盟

> **"找不到人练面试，那就让 4 个 AI 面试官陪你练。"**
>
> 一个面向"明年要找工作的应届生"的多 Agent 模拟面试系统。Lead 总调度 + 4 个不同风格的 AI 面试官 + 8 个可复用 Skill + 5 个 Mock 工具 + 1 套 JD 知识库 RAG，零成本 7×24 陪你练完一整轮真实面试，输出一份结构化复盘报告。

[![Status](https://img.shields.io/badge/status-M1%20Demo-yellow)]() [![Agents](https://img.shields.io/badge/agents-5-blue)]() [![Skills](https://img.shields.io/badge/skills-11-green)]() [![Tools](https://img.shields.io/badge/tools-5%20mock%20%2B%201%20RAG-orange)]()

---

## 1. 项目背景

### 1.1 真实痛点

- 真人模拟面试**机会少、价格贵、约不到**；
- 用单一 ChatGPT 练面试太"温柔"，**没有差异化风格**；
- 练完不知道**哪里差、怎么量化、下一轮练什么**；
- 算法/系统设计/项目/行为面**需要分角色练**，人工切换成本高。

### 1.2 我们的解法

**1 个总调度 + 4 个不同风格面试官 + 1 份结构化报告**，用 AgentTeams 把"多角色陪练"变成可 7×24 复用的产品。

---

## 2. 核心 Agent 团队

| # | Agent | 角色定位 | 关键 Skill | 调用工具 |
|---|---|---|---|---|
| 0 | **Interview Coordinator**（Lead） | 总调度 | 任务拆解、上下文传递、状态管理、汇总 | 不直接调工具 |
| 1 | **Resume Analyst** | 简历分析师 | `resume-parser`、`skill-extractor`、`jd-matcher` | `mock_resume`、`mock_jd`、`rag:jd_kb` |
| 2 | **Technical Interviewer** | 技术面试官 | `coding-question-picker`、`system-design-prompter`、`project-deep-dive` | `mock_question_bank`、`rag:jd_kb` |
| 3 | **HR Interviewer** | HR 行为面 | `behavioral-question-picker`、`motivation-probe`、`pressure-handler` | `mock_question_bank` |
| 4 | **Feedback Coach** | 反馈教练 | `answer-evaluator`、`report-generator` | `mock_evaluator`、`mock_report` |

**Lead 的特殊性**：由 manager 在创建 Team 时生成独立 Worker `mockmate-leader`，**不**由业务 Worker 兼任，确保上下文与工具调用解耦。

---

## 3. Demo 场景

| 场景 ID | 用户画像 | 面试目标 | 4 轮结构 |
|---|---|---|---|
| `backend_intern` | 大三，985 CS，GPA 3.6，有 1 段小厂后端实习 + 1 个课程项目 | 字节跳动 / 腾讯 后端开发实习 | 简历分析 → 算法 + 系统设计 + 项目深挖 + HR 行为面 → 复盘报告 |

更多场景（产品实习 / 数据实习 / 校招）见 `scenarios/` 目录。

---

## 4. 目录结构

```
mockmate/
├── README.md                       # 本文件
├── agents/                         # 5 个 Agent 定义
│   ├── interview-coordinator/Agent.md   # Lead
│   ├── resume-analyst/Agent.md
│   ├── technical-interviewer/Agent.md
│   ├── hr-interviewer/Agent.md
│   └── feedback-coach/Agent.md
├── skills/                         # 11 个 Skill 定义
│   ├── resume-parser/SKILL.md
│   ├── skill-extractor/SKILL.md
│   ├── jd-matcher/SKILL.md
│   ├── coding-question-picker/SKILL.md
│   ├── system-design-prompter/SKILL.md
│   ├── project-deep-dive/SKILL.md
│   ├── behavioral-question-picker/SKILL.md
│   ├── motivation-probe/SKILL.md
│   ├── pressure-handler/SKILL.md
│   ├── answer-evaluator/SKILL.md
│   └── report-generator/SKILL.md
├── tools/                          # 5 mock 工具 + 映射
│   ├── __init__.py
│   ├── mock_tool_server.py         # HTTP 工具网关
│   ├── mock_tools.py               # 5 个 mock 工具实现
│   ├── tool_catalog.json
│   └── MCP_MAPPING.md
├── scenarios/                      # 场景数据
│   └── backend_intern.json
├── at/                             # AgentTeams 配置
│   ├── AgentTeam.md
│   ├── AGENTTEAMS_RUNBOOK.md
│   ├── create_agents_messages.md
│   ├── run_demo_task_message.md
│   └── team_spec.json
└── docs/
    ├── 500_words_brief.md          # 500 字作品简介
    └── architecture.md             # 架构图源材料
```

---

## 5. 最短运行流程（待 Step 2 完善）

1. 启动 mock 工具网关：

   ```bash
   python3 tools/mock_tool_server.py --host 0.0.0.0 --port 18090
   ```

2. 安装 AgentTeams 并按 `at/AGENTTEAMS_RUNBOOK.md` 配置 LLM。

3. 在 manager 房间创建 5 个 Worker + 1 个 Team（详见 `at/create_agents_messages.md`）。

4. 进入 Team 房间，`@<team_leader_name>` 发送 `scenarios/backend_intern.json` 中的"面试任务"。

5. 等待 Lead 调度 4 个 worker 完成 4 轮面试，最后由 Feedback Coach 给出结构化报告。

---

## 6. 风险与安全分级

| 等级 | 动作 | 策略 |
|---|---|---|
| L1 | 简历分析、题库出题、过程评分 | 自动化执行（mock 工具直接返回） |
| L3 | 最终面试报告、综合评级、是否建议进入下一轮 | 只生成报告，**用户最终决定** |

Mock 工具网关在打分时强制要求 `evidence_refs`（每条评分都要回到题目 / 简历原文），审计可追溯。

---

## 7. 后续替换点

| 当前 | 后续方向 |
|---|---|
| 5 个 mock 工具 | 真实 MCP Server / Higress MCP 代理（映射见 `tools/MCP_MAPPING.md`） |
| `scenarios/*.json` 静态场景 | 真实简历解析（PDF/DOCX）、真实 JD 抓取（拉勾/Boss） |
| Skill 内联在 AgentSpec | Nacos AI Registry / AgentTeams Skill Registry 按版本/标签动态加载 |
| Mock 评分 | 引入多裁判员 LLM 投票 + 人类反馈（RLHF） |

---

## 8. 许可

MIT（暂定，初赛提交前确认）
