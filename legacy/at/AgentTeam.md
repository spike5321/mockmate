# MockMate Demo AgentTeam

这个文件描述 demo 使用的 Team 形态。主运行路径是 AgentTeams + 真实 LLM Worker + HTTP mock 工具网关。

## AgentTeams 运行时

| AgentTeams 概念 | Demo 设计 |
| --- | --- |
| Manager 房间 | 接收自包含的 Agent 创建消息 |
| Team 房间 | Matrix 会话列表中名称以 `Team` 开头；用户通过 `@<team_leader_name>` 发送面试任务 |
| TeamLeader Worker | 创建 Team 时由 manager 生成的独立 Worker `mockmate-leader` |
| Worker 房间 | 运行 5 个角色明确的 LLM Agent（1 Lead + 4 Worker） |
| Worker 运行时 | 统一使用 `qwenpow`（`copow`/`QwenPaw`） |
| 创建策略 | `manager` 串行创建 4 个业务 Worker + 创建 Team 时再生成独立 TeamLeader Worker `mockmate-leader`；禁止把业务 Worker 指定为 leader |
| AgentSpec | 4 个业务 Worker 内联在 `at/create_agents_messages.md` |
| 任务输入 | `at/run_demo_task_message.md` 中的简历引用 + 目标岗位 |
| 工具调用 | HTTP mock 工具网关（`tools/mock_tool_server.py`） |
| Skill Registry | 当前运行时使用创建消息中的内联 Skill 语义；`skills/*/SKILL.md` 用于评审和后续替换 |

AgentTeams 组件通常运行在 Docker 中，因此运行时不依赖宿主机上的项目目录路径。Worker 通过 HTTP 地址访问工具网关，并根据 `scenario_id` 查询对应面试场景数据。

## 工作流

1. TeamLeader `mockmate-leader` 接收 Team 房间中的面试任务，提取 `scenario_id`、候选人简历和目标岗位，调度业务 Worker。
2. `Resume Analyst Agent` 读取简历和 JD 知识库，输出候选人画像 + 缺口分析 + 面试重点方向。
3. `Technical Interviewer Agent` 主动调用题库 + RAG 出 3 道题（算法 + 系统设计 + 项目深挖），每问立即评分。
4. `HR Interviewer Agent` 推进 4 阶段行为面（自我介绍 + 动机 + 压力 + 规划），每问立即评分。
5. `Feedback Coach Agent` 校准评分、渲染 6 维雷达 + 7 天训练计划，输出 Markdown + JSON 双格式报告；TeamLeader 汇总最终报告并回复用户。

## Demo 场景

| 场景 ID | 候选人 | 目标岗位 | 流程 |
| --- | --- | --- | --- |
| `backend_intern` | Zhang San，985 CS，大三 | 字节跳动 后端开发实习生 | 简历分析 → 3 轮技术面 → 4 阶段 HR 面 → 复盘报告 |

## 当前进度

- [x] 5 个 Agent 定义（1 Lead + 4 Workers）
- [x] 11 个 Skill 定义
- [x] 5 个 Mock 工具 Python 实现（已端到端跑通）
- [x] 1 个完整 Demo 场景 `backend_intern`
- [x] Mock 工具网关 HTTP 服务
- [x] 500 字作品简介
- [ ] AgentTeams 端到端集成（Step 2）
- [ ] 真实 LLM API 联调（Step 2）
- [ ] Demo 视频录制（Step 3）
- [ ] 19 页方案 PPT（Step 3）
