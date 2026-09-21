---
name: behavioral-question-picker
description: 按 4 阶段（自我介绍 / 动机 / 压力 / 规划）选 1 道 HR 题
metadata:
  version: "0.1.0"
  maturity: demo
---

# Behavioral Question Picker

## Purpose

从 HR 题库按 4 阶段（自我介绍 / 动机 / 压力 / 职业规划）各选 1 道题，每题附 STAR 评分要点（情境 / 任务 / 行动 / 结果）。

## Inputs

- `track`（"hr"）
- `stage`（"self_intro" | "motivation" | "pressure" | "career_plan"）
- `candidate_background`（候选人画像，决定题目侧重点）

## Procedure

1. 调用 `mock_question_bank.pick(track="hr", stage)`。
2. 题库返回候选题列表。
3. 按以下规则选 1 道：
   - `self_intro` → 选"结合具体经历的 1 分钟介绍"
   - `motivation` → 选"为什么这家公司 / 这个岗位"
   - `pressure` → 选"deadline 冲突 / 同事反对 / 客户刁难"中的一种
   - `career_plan` → 选"未来 1-3 年规划"
4. 附加 STAR 评分要点：
   - Situation（情境）：是否清晰交代背景
   - Task（任务）：是否明确自己要做什么
   - Action（行动）：是否具体、有细节
   - Result（结果）：是否有量化结果 + 反思
5. 输出题目 + STAR 评分要点。

## Output Contract

```json
{
  "question_id": "hr-self-intro-001",
  "stage": "self_intro",
  "question": "请用 1 分钟介绍你自己，重点说说你最匹配这个岗位的 1 段经历。",
  "scoring_rubric": {
    "structure": 2,
    "highlight_match": 3,
    "authenticity": 3,
    "time_control": 2
  },
  "star_dimensions": ["situation", "task", "action", "result"],
  "good_answer_outline": "学校 + 专业 + 关键项目 + 为什么匹配",
  "evidence_refs": ["question:hr-self-intro-001"]
}
```

## Quality Gates

- 每 stage 至少 3 道备选题，避免重复。
- 题目贴近应届生 / 实习生身份，不出"管理 50 人团队"这种不匹配题。
- 评分要点覆盖表达 / 逻辑 / 真诚度。
