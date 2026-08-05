---
name: coding-question-picker
description: 从题库按"难度 + 知识点"选 1 道算法题，返回题目 + 标准答案 + 评分要点
metadata:
  version: "0.1.0"
  maturity: demo
---

# Coding Question Picker

## Purpose

根据候选人熟练技能 + JD 缺口，从 mock 题库选 1 道 LeetCode 中等题，并返回：

- 题目描述
- 标准答案思路
- 评分要点（时间复杂度、边界条件、代码风格）

## Inputs

- `track`（"coding"）
- `difficulty`（"easy" | "medium" | "hard"，默认 medium）
- `focus`（知识点数组，如 `["链表", "树", "哈希表"]`）
- 候选人熟练技能（从 `skill-extractor` 传入，避免出超出范围的题）

## Procedure

1. 调用 `mock_question_bank.pick(track="coding", difficulty, focus)`。
2. 题库返回候选题列表（每题含 `tags` + `difficulty` + `solution_outline`）。
3. 按以下规则选 1 道：
   - 优先匹配候选人**熟练技能对应标签**的题
   - 候选人不熟悉的标签作为"小挑战"加入备选
   - 完全无匹配时退化到通用中等题（标签：数组、字符串）
4. 校验题目不能超出候选人熟练技能（避免出"红黑树"给纯 CRUD 候选人）。
5. 返回题目 + 评分要点。

## Output Contract

```json
{
  "question_id": "lc-146-lru-cache",
  "title": "LRU 缓存",
  "difficulty": "medium",
  "tags": ["哈希表", "链表", "设计"],
  "description": "请你设计并实现一个 LRU (Least Recently Used) 缓存...",
  "solution_outline": "哈希表 + 双向链表，O(1) get/put",
  "scoring_rubric": {
    "data_structure_choice": 3,
    "time_complexity": 3,
    "edge_cases": 2,
    "code_clarity": 2
  },
  "max_score": 10,
  "evidence_refs": ["question:lc-146"]
}
```

## Quality Gates

- 同一候选人同一场面试不重复出题。
- 题目难度不超过候选人熟练技能上限 + 1 档。
- 评分要点（rubric）必须包含：数据结构选择、时间复杂度、边界条件。
