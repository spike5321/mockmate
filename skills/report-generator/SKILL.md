---
name: report-generator
description: 把校准后的数据 + 画像 → 结构化报告（Markdown + JSON）
metadata:
  version: "0.1.0"
  maturity: demo
---

# Report Generator

## Purpose

把"校准后的简历分析 + 技术面 + HR 面"过程数据，整合成一份**用户第二天就能照着练**的结构化报告。

## Inputs

- `candidate`：候选人基础信息
- `target_role`：目标岗位
- `resume_analysis`：`Resume Analyst` 输出
- `calibrated_technical`：`answer-evaluator` 校准后的技术面
- `calibrated_hr`：`answer-evaluator` 校准后的 HR 面
- `radar_template`：6 维雷达模板（技术深度 / 系统设计 / 项目表达 / 算法基础 / 行为面 / 动机匹配）

## Procedure

1. 计算 6 维雷达分（按各 round 的 score 加权平均）：
   - 技术深度 ← technical.project.score
   - 系统设计 ← technical.system_design.score
   - 项目表达 ← technical.project.score（另一权重）
   - 算法基础 ← technical.coding.score
   - 行为面 ← hr 各 round 平均
   - 动机匹配 ← hr.motivation.score
2. 提取 3 条亮点 + 3 条短板（带 `evidence_refs`）。
3. 生成 5 条改进建议（按"可立即执行"原则）。
4. 生成下一轮 7 天训练计划（每天 1 个具体任务）。
5. 渲染 Markdown + JSON 双格式输出。

## Output Contract

```json
{
  "candidate": "Zhang San",
  "target_role": "后端开发实习生 @ 字节跳动",
  "interview_date": "2026-08-02",
  "overall_score": 76,
  "radar": {
    "tech_depth": 7,
    "system_design": 6,
    "project_pitch": 8,
    "coding": 7,
    "behavioral": 8,
    "motivation_fit": 7
  },
  "highlights": [
    {
      "text": "项目表达：'二手交易平台 QPS 1200' 有数据支撑",
      "evidence_refs": ["technical.project.turn-2"]
    }
  ],
  "weaknesses": [
    {
      "text": "系统设计未考虑读写分离",
      "evidence_refs": ["technical.system_design.turn-1"]
    }
  ],
  "improvements": [
    "本周刷 10 道 LeetCode 中等，重点：链表 + 树",
    "读 1 篇短链系统设计文章并写 200 字复盘",
    "用 STAR 法重写 1 段实习经历"
  ],
  "next_7_days_plan": [
    {"day": 1, "task": "刷 3 道链表题 + 1 道树题"},
    {"day": 2, "task": "重写自我介绍 + 让朋友打分"}
  ],
  "verdict": "可以投递，建议二轮前补 Kafka + 系统设计",
  "report_md_path": "scenarios/backend_intern.report.md",
  "report_json_path": "scenarios/backend_intern.report.json"
}
```

## Quality Gates

- 报告里**所有评语都必须有 `evidence_refs`**（避免幻觉）。
- 改进建议必须"可立即执行"（不说"多刷题"，说"本周刷 10 道 LeetCode 中等"）。
- 7 天训练计划每天 1 个具体任务。
- verdict 必须是 3 选 1：可以投递 / 建议补技能后投递 / 暂不建议投递。
