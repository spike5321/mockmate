# MockMate 架构说明

> 本文件是 Step 1 阶段产出的"架构图源材料"，Step 3 会基于此绘制 PPT 里的架构图。

## 端到端流程

```
用户（学生）
  │  ① 发送任务消息：scenario_id + 简历 + 目标岗位
  ↓
┌──────────────────────────────────────────────┐
│  Manager 房间（Element Web）                 │
│  接收自包含的创建请求                        │
│  → 串行创建 4 个业务 Worker                  │
│  → 创建 Team 时生成独立 TeamLeader Worker    │
└──────────────────────────────────────────────┘
  │
  ↓
┌──────────────────────────────────────────────┐
│  Team 房间（Matrix 会话列表以 Team 开头）    │
│  用户 @mockmate-leader 发送面试任务           │
└──────────────────────────────────────────────┘
  │
  ↓
┌──────────────────────────────────────────────┐
│  mockmate-leader（独立 TeamLeader）          │
│  任务拆解 + 上下文路由 + 状态管理             │
└──────────────────────────────────────────────┘
  │           │            │            │
  ↓           ↓            ↓            ↓
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ Resume  │ │Technical│ │   HR    │ │Feedback │
│ Analyst │ │Interview│ │Interview│ │  Coach  │
│ (Worker)│ │ (Worker)│ │ (Worker)│ │ (Worker)│
└─────────┘ └─────────┘ └─────────┘ └─────────┘
  │           │            │            │
  ↓           ↓            ↓            ↓
┌──────────────────────────────────────────────┐
│  HTTP Mock 工具网关（18090）                 │
│  mock_resume / mock_jd / mock_question_bank  │
│  mock_evaluator / mock_report                │
│  + rag:jd_kb（JD 知识库）                    │
└──────────────────────────────────────────────┘
  │           │            │            │
  ↓           ↓            ↓            ↓
┌──────────────────────────────────────────────┐
│  scenarios/backend_intern.json               │
│  候选人简历 + 目标 JD + RAG 知识库           │
└──────────────────────────────────────────────┘
  │
  ↓
mockmate-leader 汇总报告 → 回复用户
```

## 关键设计

### 1. Lead 与业务 Worker 严格解耦

- Lead `mockmate-leader` **不**调用任何业务工具
- Lead 的 4 个内部技能（task-decomposition / context-routing / state-management / final-synthesis）全部用 prompt 内联
- 业务 Worker 各有独立 AgentSpec / Skills / Tools，互不感知

### 2. 上下文显式流转

- Lead 维护 `interview_state`：候选人 + 岗位 + 当前阶段 + 累计评分
- 每个 worker 处理完后，**必须**把结构化输出回写给 Lead
- Lead 再把上一轮结果连同新输入传给下一轮 worker

### 3. 风险分级

| 等级 | 动作 | 策略 |
|---|---|---|
| L1 | 简历分析、题库出题、过程评分 | 自动化执行（mock 工具直接返回） |
| L3 | 最终面试报告、综合评级、是否建议进入下一轮 | 只生成报告，**用户最终决定** |

### 4. 证据可回溯

每条评语都有 `evidence_refs` 指向具体题目 / 答案原文。Feedback Coach 在渲染报告时**禁止**写入没有 evidence 的评语（避免幻觉）。

## 与未来 MCP / Skill Registry 的对接

- 5 个 Mock 工具 → 替换为真实 MCP Server，**调用方式不变**（Agent 的 prompt / skill 不变）
- 11 个 Skill → 上传到 Nacos AI Registry / AgentTeams Skill Registry，由 Worker 按版本/标签动态加载
- 场景数据 → 真实简历 PDF 解析 + 真实 JD 抓取（拉勾 / Boss）

## 端到端延迟估算

| 阶段 | 时长 |
|---|---|
| 简历分析 | ~30 秒（1 次 LLM 调用 + 2 次 mock 调用） |
| 技术面 3 轮 | ~10-15 分钟（3 次 LLM + 3 次 mock + 候选人回答 3 次） |
| HR 面 4 阶段 | ~8-10 分钟（4 次 LLM + 4 次 mock + 候选人回答 4 次） |
| 报告生成 | ~30 秒（1 次 LLM + 1 次 mock） |
| **合计** | **~20-30 分钟/次模拟面试** |
