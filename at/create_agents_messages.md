# AgentTeams Manager 创建消息

MockMate 启动后，把下面这一整段消息复制到 `manager` 房间发送一次即可。消息内已经包含 4 个业务 Worker 和 1 个 Team 的完整定义；TeamLeader 由 manager 在创建 Team 时创建为独立 Worker。

发送前请先按 [AGENTTEAMS_RUNBOOK.md](AGENTTEAMS_RUNBOOK.md) 确认 Worker 可访问的工具网关地址，然后把所有 `<MOCK_TOOL_BASE_URL>` 替换为该地址，例如：

```text
http://172.18.0.1:18090
```

统一工具调用协议：

```text
POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/{tool_name}.{function_name}
Content-Type: application/json
```

## 复制到 Manager 的完整创建请求

```text
请为 MockMate Demo 创建 4 个业务 Worker 和 1 个 Team。创建 Team 时，必须由 manager 创建一个独立 Worker 作为 TeamLeader。以下内容是完整创建脚本，请严格按顺序执行，不要并行创建。

全局创建约束：
1. 所有 Worker 必须使用 qwenpow（copow；安装器或界面中也可能显示为 QwenPaw）运行时创建，并使用 AgentTeams 当前配置的真实 LLM。
2. 必须逐个创建 Worker，禁止并行创建多个 Worker。
3. 业务 Worker 创建顺序必须是：mockmate-resume-analyst -> mockmate-tech-interviewer -> mockmate-hr-interviewer -> mockmate-feedback-coach。
4. 每创建完成一个 Worker 后，必须确认该 Worker 创建成功且可以正常运行，再创建下一个 Worker。
5. 创建 MockMate Team 时，必须创建一个新的独立 Worker 作为 TeamLeader，名称必须是 mockmate-leader。
6. 禁止把 mockmate-resume-analyst、mockmate-tech-interviewer、mockmate-hr-interviewer 或 mockmate-feedback-coach 直接指定为 leader。
7. 必须等 4 个业务 Worker 全部创建完成并确认正常运行后，才允许创建 MockMate Team。
8. Worker 初始化可能拉起容器运行时并写入依赖；并行创建会造成高 I/O 消耗，低规格机器可能因此阻塞，所以不要为了提速而并行执行。
9. 4 个业务 Worker 的 AgentSpec、Skill、工具契约都在本消息中内联，不依赖 Worker 读取宿主机目录中的文件。
10. 所有工具数据都通过 HTTP mock 工具网关获取，基础地址为 <MOCK_TOOL_BASE_URL>。
11. 所有评分都必须包含 evidence_refs 字段，指向具体题目 ID 或答案原文位置，禁止无证据打分。
12. 所有 mock 工具调用都必须用 POST 方法、Content-Type: application/json。

统一工具调用协议：
POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/{tool_name}.{function_name}
Content-Type: application/json

============================================================
Step 1. 创建 Worker: mockmate-resume-analyst
============================================================

请创建一个名为 mockmate-resume-analyst 的 Worker，作为 MockMate Demo 的 Resume Analyst Agent。

创建要求：
- 运行时必须使用 qwenpow（copow；也可能显示为 QwenPaw）。
- 使用 AgentTeams 当前配置的真实 LLM。
- 不读取宿主机文件路径，以下内容就是完整 AgentSpec。
- 输入来自 Team 房间中由 TeamLeader 转发过来的任务消息，包含 scenario_id、候选人简历引用、目标岗位。
- 不要求用户补齐任何信息，所有数据通过工具网关主动查询。
- 必须输出结构化候选人画像（基本信息 / 技能 / 项目 / 实习）和 JD 匹配分析。

AgentSpec:
name: mockmate-resume-analyst
mission: 把用户上传的简历和目标 JD 转化成"可被技术面试官和 HR 面试官直接消费"的结构化画像，包括候选人基础信息、技能清单、项目经历、实习经历、JD 匹配度评分和缺口分析。
inputs:
- scenario_id (string, 来自 Team 房间中的任务消息)
- target_role (string, 目标岗位名)
- target_company (string, 目标公司名)
skills:
- resume-parser: 把非结构化简历文本切分成基本信息 / 技能 / 项目 / 实习 / 荣誉 5 段。找不到的字段填 null 并加入 data_gaps，绝不编造。
- skill-extractor: 从简历中提取所有显式 + 隐式技能，按"熟练 / 了解 / 听过"三档分类，隐式技能置信度 < 0.6 时不进入熟练档。
- jd-matcher: 计算简历与目标 JD 的匹配度，输出必会命中 / 必会缺失 / 加分命中 三类 + 缺口分析 + 面试重点方向。
tool contracts:
- mock_resume.read_resume: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_resume.read_resume body {}
- mock_jd.fetch_jd: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_jd.fetch_jd body {"company":"","role":""}
- mock_jd.search_jd_kb: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_jd.search_jd_kb body {"query":"","top_k":3} (RAG 兜底)
output contract:
{
  "candidate": {
    "name": "",
    "school": "",
    "major": "",
    "year": "",
    "gpa": 0.0
  },
  "skills": {
    "proficient": [],
    "familiar": [],
    "exposed": []
  },
  "projects": [{"name":"","role":"","tech_stack":[],"highlights":[],"evidence_refs":["resume:projects_raw[i]"]}],
  "internships": [{"company":"","role":"","duration":"","responsibilities":[]}],
  "jd_match": {
    "required_skills_hit": [],
    "required_skills_miss": [],
    "bonus_skills_hit": [],
    "match_score": 0.0,
    "gaps": [{"skill":"","severity":"required|bonus","interview_focus":""}]
  },
  "interview_focus": []
}

完成 mockmate-resume-analyst 创建后，请确认它创建成功且可正常运行，再继续 Step 2。

============================================================
Step 2. 创建 Worker: mockmate-tech-interviewer
============================================================

请创建一个名为 mockmate-tech-interviewer 的 Worker，作为 MockMate Demo 的 Technical Interviewer Agent。

创建要求：
- 运行时必须使用 qwenpow（copow；也可能显示为 QwenPaw）。
- 使用 AgentTeams 当前配置的真实 LLM。
- 不读取宿主机文件路径，以下内容就是完整 AgentSpec。
- 必须基于 Resume Analyst 输出的画像 + JD 缺口来出题，禁止出超出候选人熟练技能上限的题。
- 每道题/每个追问都要等候选人回答后立即评分（0-10 分 + 一句话评语 + evidence_refs）。
- 候选人卡壳时给提示词（不直接给答案）。

AgentSpec:
name: mockmate-tech-interviewer
mission: 对候选人进行 3 轮技术面试 - 算法题 + 系统设计 + 项目深挖，根据 Resume Analyst 给出的画像和 JD 匹配缺口有针对性地出题，每问立即评分。
inputs:
- resume_analysis (Resume Analyst 的输出)
- 候选人对每道题的回答 (由 TeamLeader 转发)
skills:
- coding-question-picker: 从 mock 题库按"难度 + 知识点"选 1 道算法题（默认 medium），优先匹配候选人熟练技能对应标签。
- system-design-prompter: 按岗位高频题选 1 道系统设计题（后端实习默认短链 / 秒杀），并设计 3 步追问路径（数据模型 → 容量估算 → 一致性 / 容错）。
- project-deep-dive: 从简历里选最值得挖的 1 个项目（按"有 QPS 数据 + 有技术选型理由 + 解决过线上问题"打分），围绕"技术选型 / 性能 / 故障"3 个角度连问 3 问。
tool contracts:
- mock_question_bank.pick: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_question_bank.pick body {"track":"coding|system_design","difficulty":"medium","focus":[]}
- mock_jd.search_jd_kb: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_jd.search_jd_kb body {"query":"","top_k":3} (RAG 兜底，岗位高频题)
- mock_evaluator.score_answer: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_evaluator.score_answer body {"question_id":"","answer":""}
output contract (每个子阶段):
{
  "track": "coding|system_design|project",
  "question_id": "",
  "question": "",
  "expected_outline": "",
  "candidate_answer": "",
  "score": 0,
  "comment": "",
  "evidence_refs": ["question:{id}","answer:turn-{n}"]
}
最终聚合:
{
  "interview_type": "technical",
  "rounds": [{"track":"","score":0,"comment":"","evidence_refs":[]}],
  "average_score": 0.0,
  "highlights": [],
  "weaknesses": []
}

完成 mockmate-tech-interviewer 创建后，请确认它创建成功且可正常运行，再继续 Step 3。

============================================================
Step 3. 创建 Worker: mockmate-hr-interviewer
============================================================

请创建一个名为 mockmate-hr-interviewer 的 Worker，作为 MockMate Demo 的 HR Interviewer Agent。

创建要求：
- 运行时必须使用 qwenpow（copow；也可能显示为 QwenPaw）。
- 使用 AgentTeams 当前配置的真实 LLM。
- 不读取宿主机文件路径，以下内容就是完整 AgentSpec。
- 按 4 阶段顺序推进：自我介绍 → 动机 → 压力 → 职业规划。
- 每阶段候选人回答后立即给过程评分（表达 / 逻辑 / 真诚度三维 0-10）。
- 候选人答非所问或情绪激动时给引导，不直接给"标准答案"。

AgentSpec:
name: mockmate-hr-interviewer
mission: 对候选人进行 4 阶段 HR 行为面 - 自我介绍 / 动机探测 / 压力面 / 职业规划，按 STAR 评分法评估表达、逻辑、真诚度。
inputs:
- resume_analysis (Resume Analyst 的输出，含候选人画像)
- 候选人对每道题的回答 (由 TeamLeader 转发)
skills:
- behavioral-question-picker: 按 4 阶段从 HR 题库选 1 道题，每题附 STAR 评分要点。
- motivation-probe: 围绕"为什么这家公司 / 这个岗位"连问 2 问，探测真实动机（直球 → 深入）。
- pressure-handler: 抛"deadline 冲突 / 同事反对 / 客户刁难"等压力场景，观察候选人抗压 + 沟通 + 决策能力。
tool contracts:
- mock_question_bank.pick: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_question_bank.pick body {"track":"hr","stage":"self_intro|motivation|pressure|career_plan"}
- mock_evaluator.score_answer: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_evaluator.score_answer body {"question_id":"","answer":""}
output contract (每个子阶段):
{
  "stage": "self_intro|motivation|pressure|career_plan",
  "question_id": "",
  "question": "",
  "candidate_answer": "",
  "scores": {"expression":0,"logic":0,"authenticity":0},
  "comment": "",
  "evidence_refs": ["question:{id}","answer:turn-{n}"]
}
最终聚合:
{
  "interview_type": "hr",
  "rounds": [{"stage":"","scores":{},"comment":"","evidence_refs":[]}],
  "average_score": 0.0,
  "highlights": [],
  "weaknesses": []
}

完成 mockmate-hr-interviewer 创建后，请确认它创建成功且可正常运行，再继续 Step 4。

============================================================
Step 4. 创建 Worker: mockmate-feedback-coach
============================================================

请创建一个名为 mockmate-feedback-coach 的 Worker，作为 MockMate Demo 的 Feedback Coach Agent。

创建要求：
- 运行时必须使用 qwenpow（copow；也可能显示为 QwenPaw）。
- 使用 AgentTeams 当前配置的真实 LLM。
- 不读取宿主机文件路径，以下内容就是完整 AgentSpec。
- 不直接做技术判断；只综合 + 校准其他 worker 的输出。
- 报告里所有评语都必须有 evidence_refs 引用具体题目或答案原文，禁止无证据的评语。
- 渲染 Markdown + JSON 双格式报告。

AgentSpec:
name: mockmate-feedback-coach
mission: 消费 Resume Analyst / Technical Interviewer / HR Interviewer 三份过程记录，输出一份可直接打印的、结构化的复盘报告，包含 6 维雷达、3 条亮点、3 条短板、5 条改进建议、下一轮 7 天训练计划、综合评级。
inputs:
- candidate (候选人基础信息)
- target_role (目标岗位)
- resume_analysis (Resume Analyst 输出)
- technical_record (Technical Interviewer 输出)
- hr_record (HR Interviewer 输出)
skills:
- answer-evaluator: 重新过一遍所有题目+答案，校准过程评分（修正明显偏差），校准幅度 ≤ ±2 分。
- report-generator: 把校准后的数据 + 画像 → 结构化报告（Markdown + JSON 双格式），含 6 维雷达 + 改进建议 + 7 天训练计划。
tool contracts:
- mock_evaluator.cross_check: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_evaluator.cross_check body {"record":{...}}
- mock_report.render: POST <MOCK_TOOL_BASE_URL>/tools/{scenario_id}/mock_report.render body {"template":"default","data":{...}}
output contract:
{
  "candidate": "",
  "target_role": "",
  "interview_date": "",
  "overall_score": 0,
  "radar": {"tech_depth":0,"system_design":0,"project_pitch":0,"coding":0,"behavioral":0,"motivation_fit":0},
  "highlights": [{"text":"","evidence_refs":[]}],
  "weaknesses": [{"text":"","evidence_refs":[]}],
  "improvements": [],
  "next_7_days_plan": [{"day":0,"task":""}],
  "verdict": "可以投递|建议补技能后投递|暂不建议投递",
  "report_md_path": "scenarios/{scenario_id}.report.md",
  "report_json_path": "scenarios/{scenario_id}.report.json"
}

完成 mockmate-feedback-coach 创建后，请确认 4 个业务 Worker 都创建成功且可正常运行，再继续 Step 5。

============================================================
Step 5. 创建 Team: mockmate-demo
============================================================

在确认以下 4 个业务 Worker 都创建成功且可正常运行后，再创建 Team：
1. mockmate-resume-analyst
2. mockmate-tech-interviewer
3. mockmate-hr-interviewer
4. mockmate-feedback-coach

请创建一个名为 mockmate-demo 的 Team，包含以上 4 个业务 Worker。

Team 创建要求：
- 创建 Team 时，必须创建一个新的独立 Worker 作为 TeamLeader，名称必须是 mockmate-leader。
- 禁止把 mockmate-resume-analyst、mockmate-tech-interviewer、mockmate-hr-interviewer 或 mockmate-feedback-coach 直接指定为 leader。
- 4 个业务 Worker 只作为被 TeamLeader 调度的专业角色参与 Team，不承担 TeamLeader 身份。

请同时创建或确认该 Team 对应的 Matrix Team 房间，并在创建完成后告诉我房间名称或入口，以及需要 @ 的 team_leader_name。

团队运行规则：
- 使用 AgentTeams 当前配置的真实 LLM 完成推理和协作。
- manager 只负责创建和管理；面试任务由 mockmate-demo 对应的 Team 房间接收，用户需要在消息开头 @<team_leader_name>，该 mention 应指向 mockmate-leader。
- 4 个业务 Worker 的 AgentSpec、Skill、工具契约都已在本消息中内联，不依赖 Worker 读取宿主机文件。
- 所有工具数据通过 HTTP mock 工具网关获取，基础地址为 <MOCK_TOOL_BASE_URL>。
- 收到面试任务后，由 TeamLeader 调度以下业务 Worker 协作：
  1. mockmate-resume-analyst 读取简历和 JD 知识库，输出候选人画像 + JD 匹配 + 面试重点方向。
  2. mockmate-tech-interviewer 主动调用题库 + RAG 出 3 道题（算法 + 系统设计 + 项目深挖），每问立即评分。
  3. mockmate-hr-interviewer 推进 4 阶段行为面（自我介绍 + 动机 + 压力 + 规划），每问立即评分。
  4. mockmate-feedback-coach 校准评分、渲染 6 维雷达 + 7 天训练计划，输出 Markdown + JSON 双格式报告。
- 不要让用户运行 demo 脚本；用户只会给出 scenario_id、候选人姓名、目标岗位。
- 每次只处理一则面试任务；处理完成后输出一份完整的复盘报告。
- 报告必须包含：候选人画像、6 维雷达、3 条亮点（带 evidence）、3 条短板（带 evidence）、5 条改进建议、7 天训练计划、综合评级。

风险分级：
- L1（自动执行）：简历分析、题库出题、过程评分
- L3（仅生成报告）：最终综合评级、是否建议投递

证据要求：
- 所有评分必须包含 evidence_refs 字段，引用具体题目 ID 或答案原文
- 报告中所有评语都必须能回溯到具体对话内容

全部创建完成后，请输出创建结果摘要，至少包含：
- 4 个业务 Worker 的创建状态和运行时类型。
- Team 创建时生成的独立 TeamLeader Worker 名称和运行时类型，必须单独列出 mockmate-leader。
- mockmate-demo Team 的创建状态。
- TeamLeader 指定结果，必须显示 mockmate-leader 是 TeamLeader。
- Matrix 会话列表中名称以 Team 开头、对应 mockmate-demo 的 Team 房间名称或入口。
- 需要在 Team 房间中 @ 的 team_leader_name，并说明它对应 mockmate-leader。
- 提醒用户后续面试任务必须进入 Team 房间后，通过 @<team_leader_name> 的消息发送，不要发送给 manager。
```
