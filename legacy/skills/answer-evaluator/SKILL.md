---
name: answer-evaluator
description: 重新过一遍所有题目+答案，校准过程评分（修正 Technical/HR 的明显偏差）
metadata:
  version: "0.1.0"
  maturity: demo
---

# Answer Evaluator

## Purpose

Feedback Coach 在生成最终报告前，对 Technical Interviewer 和 HR Interviewer 的过程评分做一次"交叉校准"——发现并修正明显偏差，确保最终报告的评分公平。

## Inputs

- `technical_record`：`Technical Interviewer` 的输出
- `hr_record`：`HR Interviewer` 的输出
- `ground_truth`（可选）：从 mock_evaluator 拉取的标准答案 + 评分要点

## Procedure

1. 拉取 `ground_truth`（题库中每道题的"标准答案要点"）。
2. 对每道题的候选人答案 + 过程评分做一致性检查：
   - 答案**明显**符合 ground_truth，但过程分 < 6 → 校准上调
   - 答案**明显**偏离 ground_truth，但过程分 > 8 → 校准下调
   - 答案模糊或过程分在 5-8 → 保持原分
3. 校准幅度不超过 ±2 分。
4. 输出校准日志（哪些题被调了分、为什么）。

## Output Contract

```json
{
  "calibrated_technical": {
    "...": "...（同 technical_record 结构，score 已校准）"
  },
  "calibrated_hr": {
    "...": "...（同 hr_record 结构，scores 已校准）"
  },
  "calibration_log": [
    {
      "round_id": "technical.coding",
      "original_score": 5,
      "calibrated_score": 7,
      "reason": "答案提到了双向链表 + 哈希表，与 ground_truth 完全一致，但过程分偏低"
    },
    {
      "round_id": "hr.self_intro",
      "original_score": 9,
      "calibrated_score": 8,
      "reason": "自我介绍超时（1 分钟讲了 2 分钟），但表达分仍较高，扣 1 分"
    }
  ],
  "average_score_before": 7.0,
  "average_score_after": 7.2
}
```

## Quality Gates

- 校准幅度 ±2 分以内。
- 每条校准必须给出**具体原因**（引用 ground_truth 或评分要点）。
- 校准后总平均分变化不超过 ±1 分（避免系统性偏移）。
