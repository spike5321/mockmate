---
name: motivation-probe
description: 围绕"为什么这家公司 / 这个岗位"连问 2 问，探测真实动机
metadata:
  version: "0.1.0"
  maturity: demo
---

# Motivation Probe

## Purpose

行为面的"动机探测"专项 Skill。围绕"为什么这家公司 / 这个岗位 / 这个时间点"连问 2 问，探测候选人动机的真实性、深度、与岗位的匹配度。

## Inputs

- `company`：目标公司名
- `role`：目标岗位
- `candidate_profile`：候选人画像（含项目、实习、动机相关线索）

## Procedure

1. 第 1 问（直球）：**"你为什么想加入我们公司？"**
   - 期望回答：业务理解 + 个人兴趣 + 长期规划
2. 第 2 问（深入，根据第 1 问回答动态调整）：
   - 回答空泛 → "你了解过我们最近的某个产品吗？有什么想法？"
   - 回答具体 → "你提到的产品/业务，你认为目前最大的挑战是什么？"
3. 评分要点：
   - 真诚度（不是从 JD 抄的）
   - 深度（了解公司业务 / 产品 / 行业）
   - 匹配度（个人经历 + 兴趣 + 岗位的连接）
4. 失败处理：候选人完全不了解公司 → 给一段公司简介提示，但不替候选人回答。

## Output Contract

```json
{
  "questions": [
    {
      "step": 1,
      "question": "你为什么想加入字节跳动？",
      "expected_outline": "对字节业务（如抖音/飞书）的理解 + 个人技术兴趣 + 长期规划",
      "scoring_focus": "真诚度 + 业务理解"
    },
    {
      "step": 2,
      "fallback": "如果候选人回答空泛",
      "question": "你了解飞书最近做的某个功能吗？你会用吗？",
      "expected_outline": "能说出具体功能 + 自己的使用体验 + 改进建议",
      "scoring_focus": "真实使用过 + 思考深度"
    }
  ],
  "scoring_rubric": {
    "sincerity": 4,
    "depth": 3,
    "match": 3
  }
}
```

## Quality Gates

- 2 问必须构成"直球 → 深入"的递进关系。
- 第 2 问必须根据第 1 问回答动态调整（不能是固定的 2 道题）。
- 评分要点覆盖：真诚、深度、匹配。
