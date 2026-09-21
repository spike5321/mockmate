---
name: jd-matcher
description: 计算简历与目标 JD 的匹配度，输出必会 / 加分 / 无关 三类技能 + 缺口分析
metadata:
  version: "0.1.0"
  maturity: demo
---

# JD Matcher

## Purpose

把简历里的技能和目标 JD 的要求做"匹配度计算"，输出：

- 必会技能中**简历已覆盖**的（hit）
- 必会技能中**简历未覆盖**的（miss）
- 加分技能中**简历已覆盖**的（bonus_hit）
- 整体匹配度评分（0-1）
- 缺口分析（面试时该追问的方向）

## Inputs

- `skills`：`skill-extractor` 的输出
- `target_jd`：JD 结构化数据（来自 `mock_jd.fetch_jd` 或 RAG 兜底）

## Procedure

1. 把 JD 的 `required_skills` 和 `bonus_skills` 各自与候选人技能做交集 / 差集。
2. 匹配度计算：
   ```
   match_score = 0.7 * (required_hit / required_total) + 0.3 * (bonus_hit / bonus_total)
   ```
3. 缺口分析：每个 `miss` 技能生成 1 条"该问什么"：
   - 完全没听过 → "请你介绍下 Kafka 的使用场景"
   - 听过但没用过 → "你在哪个项目里用过 Redis？解决了什么问题？"
4. 输出 `interview_focus`：把缺口转化为具体面试题方向。

## Output Contract

```json
{
  "required_skills_hit": ["Java", "MySQL", "Redis"],
  "required_skills_miss": ["Kafka", "分布式系统设计"],
  "bonus_skills_hit": ["Docker"],
  "match_score": 0.65,
  "gaps": [
    {
      "skill": "Kafka",
      "severity": "required",
      "interview_focus": "你在项目中怎么保证消息不丢失？"
    },
    {
      "skill": "分布式系统设计",
      "severity": "required",
      "interview_focus": "请描述你做过的最复杂系统的架构"
    }
  ],
  "interview_focus": [
    "项目深挖：二手交易平台 QPS 1200 的依据",
    "算法：中等难度链表/树",
    "系统设计：短链生成或秒杀"
  ]
}
```

## Quality Gates

- `required_total == 0` 时 `match_score = 0`（避免除零）。
- `gaps` 按 severity 排序：required 在前，bonus 在后。
- `interview_focus` 至少 3 条，覆盖算法 + 系统设计 + 项目。
