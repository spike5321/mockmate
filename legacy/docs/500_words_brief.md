# MockMate 面试官联盟 · 500 字作品简介

## 项目名称

**MockMate 面试官联盟** — 给"明年要找工作的大三/大四学生"用的多 Agent 模拟面试系统。

## 解决的真问题

应届生找实习/校招有 3 个真实痛点：(1) 真人模拟面试**机会少、价格贵、约不到**；(2) 单一 ChatGPT 练面试太"温柔"，**没有差异化风格**——而真实面试中你会被技术官、HR、压力面官连续拷问；(3) 练完不知道**哪里差、怎么量化、下一轮练什么**，导致大量学生真面试才"踩坑"。

## 目标用户

**2026 年应届生**（计算机相关专业，大三/大四/研二），求职方向包括互联网技术岗（后端/前端/算法/数据）和产品/运营岗。当前 Demo 主场景为"后端开发实习面试"。

## 核心方案

1 个 Lead + 4 个不同风格 AI 面试官 + 11 个 Skill + 5 个 Mock 工具 + 1 套 JD 知识库 RAG：

- **Interview Coordinator (Lead)**：独立 TeamLeader，负责任务拆解、上下文传递、状态管理；
- **Resume Analyst**：`resume-parser` + `skill-extractor` + `jd-matcher` 把简历 + JD 转结构化画像；
- **Technical Interviewer**：`coding-question-picker` + `system-design-prompter` + `project-deep-dive` 出 3 道题（算法 + 系统设计 + 项目深挖），每问立即评分；
- **HR Interviewer**：`behavioral-question-picker` + `motivation-probe` + `pressure-handler` 推进 4 阶段行为面；
- **Feedback Coach**：`answer-evaluator` + `report-generator` 校准评分、生成 6 维雷达 + 7 天训练计划。

## 创新点

(1) **多 Agent 风格差异化**：4 个 worker 各自独立的 Prompt/Skill/工具契约，模拟真实面试中的 4 种人；(2) **上下文流式传递**：Lead 把"简历分析 + JD + 候选人答复"在 worker 之间显式流转；(3) **证据可回溯**：每条评语都有 `evidence_refs` 指向具体题目/答案原文，避免幻觉。

## 可复用/开放能力

- 5 个 Mock 工具全部有未来真实 MCP 映射（`user.profile.read`、`recruiter.jd.search`、`quiz.bank.query` 等），替换路径清晰；
- 11 个 Skill 按统一规范（输入/输出/依赖/失败处理）描述，可独立注册到 Nacos AI Registry；
- 场景数据可扩展：从后端实习扩到产品/数据/校招，**只新增 `scenarios/*.json`**，Agent 不变。

## 当前完成度

5 个 Agent + 11 个 Skill + 5 个 Mock 工具 Python 实现（已端到端跑通）+ 1 个完整 Demo 场景 `backend_intern`（简历+JD+RAG 知识库）+ Mock 工具网关 HTTP 服务可启动。Step 1（项目骨架）已完成；Step 2（AgentTeams 真实 LLM 端到端）进行中。
