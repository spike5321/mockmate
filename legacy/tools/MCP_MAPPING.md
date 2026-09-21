# MCP 映射说明

初赛 demo 使用 HTTP mock 工具网关，让 AgentTeams 中的 Docker Worker 可以通过网络访问 mock 简历、JD、题库、评分和报告工具。

当前工具网关**不是** MCP Server，但每个 HTTP 工具都有明确的未来 MCP 映射。后续只需要把 HTTP endpoint 替换为真实 MCP Server 或 Higress MCP 代理，Agent 的 Prompt/Skill/工具契约可以保持稳定。

## HTTP 调用协议

```text
POST http://<MOCK_TOOL_BASE_URL>/tools/{scenario_id}/{tool_name}.{function_name}
Content-Type: application/json
Body: {<args...>}
```

示例：

```bash
# 1. 读简历
curl -X POST http://127.0.0.1:18090/tools/backend_intern/mock_resume.read_resume \
  -H 'Content-Type: application/json' -d '{}'

# 2. 拉 JD
curl -X POST http://127.0.0.1:18090/tools/backend_intern/mock_jd.fetch_jd \
  -H 'Content-Type: application/json' -d '{}'

# 3. 出算法题
curl -X POST http://127.0.0.1:18090/tools/backend_intern/mock_question_bank.pick \
  -H 'Content-Type: application/json' \
  -d '{"track": "coding", "difficulty": "medium", "focus": ["链表"]}'

# 4. 出系统设计题
curl -X POST http://127.0.0.1:18090/tools/backend_intern/mock_question_bank.pick \
  -H 'Content-Type: application/json' \
  -d '{"track": "system_design"}'

# 5. 出 HR 题
curl -X POST http://127.0.0.1:18090/tools/backend_intern/mock_question_bank.pick \
  -H 'Content-Type: application/json' \
  -d '{"track": "hr", "stage": "pressure"}'

# 6. 校准评分
curl -X POST http://127.0.0.1:18090/tools/backend_intern/mock_evaluator.cross_check \
  -H 'Content-Type: application/json' -d '{"record": {"track": "coding", "score": 7}}'

# 7. 渲染报告
curl -X POST http://127.0.0.1:18090/tools/backend_intern/mock_report.render \
  -H 'Content-Type: application/json' \
  -d '{"template": "default", "data": {"candidate": "Zhang San", "overall_score": 76}}'
```

## 工具映射

| HTTP mock tool | Demo function | 未来 MCP tool | 真实场景 |
|---|---|---|---|
| `mock_resume` | `read_resume` | `user.profile.read` | 简历 PDF 解析 + 标准化 |
| `mock_jd` | `fetch_jd` | `recruiter.jd.search` | 拉勾/Boss/LinkedIn JD 抓取 |
| `mock_jd` | `search_jd_kb` | `vector.search` | Milvus / Qdrant / ES 检索 |
| `mock_question_bank` | `pick` | `quiz.bank.query` | LeetCode API + 自建 HR 题库 |
| `mock_evaluator` | `score_answer` | `llm.judge.score` | 多 LLM 裁判投票 |
| `mock_evaluator` | `cross_check` | `llm.judge.cross_check` | 校准 + 防幻觉 |
| `mock_report` | `render` | `doc.report.render` | Notion / 飞书 / Markdown 模板渲染 |

## RAG 说明

`rag:jd_kb` 是 demo 阶段的内置 RAG，由 `mock_jd.search_jd_kb` 实现：
- 知识源：`scenarios/{scenario_id}.json` 中的 `jd_kb` 字段
- 检索：关键词匹配 + 截断（demo 简化版）
- 未来：替换为真实向量数据库（Milvus / Qdrant）+ Embedding

## Agent 调用关系（简化）

```
Resume Analyst       → mock_resume.read_resume + mock_jd.fetch_jd + rag:jd_kb.search
Technical Interviewer → mock_question_bank.pick(coding/system_design) + mock_evaluator.score_answer + rag:jd_kb.search
HR Interviewer       → mock_question_bank.pick(hr) + mock_evaluator.score_answer
Feedback Coach       → mock_evaluator.cross_check + mock_report.render
```

## 替换路径

| 当前 | 后续替换 |
|---|---|
| HTTP mock 工具网关 | Higress MCP 代理 / 真实 MCP Server |
| `mock_jd.search_jd_kb` 关键词匹配 | Milvus / Qdrant 向量检索 |
| `mock_evaluator` 规则打分 | 多 LLM 裁判投票 + RLHF |
| `scenarios/*.json` 静态场景 | 真实简历 PDF 解析 + 真实 JD 抓取 |
