# AgentTeams 面试任务消息

4 个业务 Worker、独立 TeamLeader Worker `mockmate-leader` 以及 `mockmate-demo` Team 创建完成后，在 Element Web/Matrix 会话列表中找到名称以 `Team` 开头、对应 `mockmate-demo` 的 Team 房间。

进入 Team 房间后，在输入框先输入并选中 `@<team_leader_name>`，再把下面的面试任务复制到这条 @ 消息里发送。不要把面试任务发给 `manager`。`manager` 用于创建和管理 Agent/Team；Team 房间中的 leader 用于接收业务任务并调度 Worker。

每条消息只包含用户能自然提供的信息（候选人姓名、目标岗位、scenario_id）。候选人简历、目标 JD、面试题、评分等所有数据都应由 Agent 通过 HTTP 工具网关主动查询。

## 第一次任务：后端开发实习面试（字节跳动）

```text
@<team_leader_name>

请让你的 Team 为我安排一次完整的后端开发实习模拟面试。

scenario_id: backend_intern
候选人：张三
学校：XX大学（985） 计算机科学与技术 大三
目标岗位：后端开发实习生
目标公司：字节跳动

请按以下流程推进：
1. 让 Resume Analyst 读取我的简历并和目标 JD 做匹配分析。
2. 让 Technical Interviewer 给我出 3 道题：1 道算法（中等）+ 1 道系统设计 + 1 道项目深挖，每题请等我回答后再继续。
3. 让 HR Interviewer 推进 4 阶段行为面：自我介绍 + 动机探测 + 压力面 + 职业规划，每阶段请等我回答后再继续。
4. 让 Feedback Coach 在所有轮次结束后输出完整的复盘报告（Markdown + JSON 双格式）。

请开始。
```

## 期望输出顺序

| 阶段 | 期望信号 |
| --- | --- |
| 简历分析完成 | TeamLeader 转发 Resume Analyst 的画像 + JD 匹配 + 面试重点 |
| 技术面 Round 1 | 1 道算法题，等候选人回答 |
| 技术面 Round 2 | 1 道系统设计题，等候选人回答 |
| 技术面 Round 3 | 1 道项目深挖题（3 问），等候选人回答 |
| HR 面 Stage 1 | 自我介绍问题，等候选人回答 |
| HR 面 Stage 2 | 动机探测（2 问），等候选人回答 |
| HR 面 Stage 3 | 压力面，等候选人回答 |
| HR 面 Stage 4 | 职业规划，等候选人回答 |
| 报告输出 | Feedback Coach 输出 Markdown + JSON 报告，TeamLeader 汇总回复 |

## 后续可扩展任务（可选）

如果想再跑一次不同场景，可以新增 `scenarios/{new_scenario}.json` 后，发送以下消息：

```text
@<team_leader_name>

请用新场景跑一次模拟面试。

scenario_id: <NEW_SCENARIO_ID>
候选人：<姓名>
学校：<学校>
目标岗位：<岗位>
目标公司：<公司>
```

## 注意事项

- 候选人回答时，**直接 @ TeamLeader** 即可，TeamLeader 会自动把回答转发给当前阶段的 worker。
- 如果某阶段等待超过 5 分钟无响应，TeamLeader 会标记该阶段为 partial，继续推进。
- 报告生成后，TeamLeader 会输出报告内容摘要 + 报告文件路径（`scenarios/{scenario_id}.report.md` 和 `.json`）。
