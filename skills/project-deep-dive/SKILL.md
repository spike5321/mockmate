---
name: project-deep-dive
description: 从简历挑 1 个项目，生成"技术选型 / 性能 / 故障"3 问
metadata:
  version: "0.1.0"
  maturity: demo
---

# Project Deep Dive

## Purpose

从候选人简历里**选最值得挖的那个项目**，围绕"技术选型 / 性能 / 故障"3 个角度连问 3 问，每问 1 个评分点。

## Inputs

- `projects_raw`：`resume-parser` 的 `projects_raw`
- `interview_focus`：`jd-matcher` 输出的重点方向

## Procedure

1. 给每个项目打分（"值得挖度"）：
   - 有 QPS / 性能数据 +3
   - 有技术栈选型理由 +2
   - 解决过线上问题 +3
   - 与 JD 重点技能匹配 +2
2. 选分数最高的 1 个项目（平分时取最近 1 年内的）。
3. 生成 3 问：
   - **技术选型**：为什么用 X 不用 Y？（考察决策能力）
   - **性能**：QPS 1200 怎么测出来的？瓶颈在哪？（考察量化能力）
   - **故障**：遇到过最严重的线上问题是什么？怎么发现的？怎么修的？（考察抗压 + 复盘能力）
4. 每问 1 个 `expected_outline` + 1 个评分要点。

## Output Contract

```json
{
  "project_picked": {
    "name": "校园二手交易平台",
    "reason": "有 QPS 数据 + 与 JD 重点匹配",
    "evidence_refs": ["resume:projects_raw[0]"]
  },
  "questions": [
    {
      "step": "tech_choice",
      "question": "为什么选 MySQL 而不是 MongoDB？",
      "expected_outline": "关系型数据 + 事务需求 + 团队熟悉度",
      "scoring_focus": "技术决策的 trade-off 分析"
    },
    {
      "step": "performance",
      "question": "QPS 1200 是怎么测出来的？系统瓶颈在哪？",
      "expected_outline": "压测工具（JMeter/wrk）+ 数据库是瓶颈 + 加缓存后到 3000",
      "scoring_focus": "量化能力 + 性能瓶颈识别"
    },
    {
      "step": "failure",
      "question": "遇到过最严重的线上问题？怎么发现、定位、修复？",
      "expected_outline": "具体故障 + 监控告警 + 排查链路 + 修复方案 + 后续改进",
      "scoring_focus": "抗压 + 复盘 + 改进闭环"
    }
  ]
}
```

## Quality Gates

- 3 问必须分别覆盖：技术选型、性能、故障（不能 3 问都问同一类）。
- 题目基于候选人**实际简历内容**，不能编造未提及的项目。
- 每问有 `expected_outline` + `scoring_focus`，便于 Technical Interviewer 即时评分。
