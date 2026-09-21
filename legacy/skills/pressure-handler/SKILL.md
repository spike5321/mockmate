---
name: pressure-handler
description: 抛"deadline 冲突 / 同事反对"等压力场景，观察候选人反应
metadata:
  version: "0.1.0"
  maturity: demo
---

# Pressure Handler

## Purpose

行为面的"压力面"专项 Skill。抛 1 个"高强度场景"（如 deadline 冲突 / 与同事意见分歧 / 客户刁难），观察候选人的反应，考察抗压 + 沟通 + 解决问题能力。

## Inputs

- `scenario`（"deadline_conflict" | "colleague_disagree" | "client_difficult"）
- 候选人画像（决定场景具体内容）

## Procedure

1. 选 1 个场景，构造具体压力情境（贴合后端实习生的真实工作场景）：
   - `deadline_conflict` → "你同时被分配了 2 个紧急任务，PM 说都重要，明天都要上线，你怎么办？"
   - `colleague_disagree` → "你和资深同事在技术方案上有分歧，他认为用 MySQL 你认为用 PostgreSQL，怎么办？"
   - `client_difficult` → "产品经理坚持要你做一个你认为技术上不合理的功能，你怎么沟通？"
2. 评分要点（4 个）：
   - 抗压（不慌乱、不情绪化）
   - 分析（拆解问题、列出选项）
   - 沟通（向上 / 向下 / 平级如何沟通）
   - 决策（在不确定下做决策）
3. 追问：候选人回答空泛时追问"具体一点 / 举一个真实例子"。
4. 失败处理：候选人情绪激动 → 切换为"如果是你的话你会怎么想？"

## Output Contract

```json
{
  "scenario": "deadline_conflict",
  "question": "你同时被分配了 2 个紧急任务，PM 说都重要，明天都要上线，你怎么办？",
  "scoring_rubric": {
    "stress_resistance": 3,
    "analysis": 3,
    "communication": 2,
    "decision_making": 2
  },
  "good_answer_outline": "先评估两个任务的工作量 + 风险 + 业务影响 → 主动找 PM 沟通排序 + 给出自己的建议方案 → 必要时求助同事或上级",
  "follow_up": {
    "if_vague": "你具体怎么跟 PM 沟通的？能模拟一下吗？",
    "if_emotional": "看起来你对这种情况有压力，如果是你自己实际遇到，你打算怎么调节？"
  },
  "evidence_refs": ["question:pressure-deadline-001"]
}
```

## Quality Gates

- 场景贴近后端实习生真实工作（不出"管理 50 人团队"题）。
- 追问必须根据候选人回答**动态**调整（空泛 vs 情绪化 vs 答得好）。
- 评分要点 4 维：抗压、分析、沟通、决策。
