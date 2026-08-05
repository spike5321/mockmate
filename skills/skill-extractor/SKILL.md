---
name: skill-extractor
description: 从简历中提取所有显式 + 隐式技能，按"熟练 / 了解 / 听过"三档分类
metadata:
  version: "0.1.0"
  maturity: demo
---

# Skill Extractor

## Purpose

接收 `resume-parser` 的结构化输出，把所有技能归类到三档（熟练 / 了解 / 听过），同时识别简历中**没明说但项目经历暴露出来**的隐式技能。

## Inputs

- `resume_parsed`：`resume-parser` 的输出
- 技能词典（内置，约 200 个常见后端/前端/算法/产品技能关键词）

## Procedure

1. **显式技能提取**：扫描 `skills_raw`，按 `level_hint` 映射到三档：
   - "精通" / "熟练" → `proficient`
   - "熟悉" / "了解" → `familiar`
   - 其它 → `exposed`
2. **隐式技能提取**：扫描 `projects_raw` 和 `internships_raw` 的 `tech_stack`：
   - 在 `skills_raw` 已出现的技能升级 level_hint（取较高档）
   - 未出现的技能加入 `exposed`，标注 `implicit: true, source: "project:xxx"`
   - 隐式技能的"熟练"档置信度 < 0.6 时降为 `familiar`
3. **去重 + 排序**：每档按字母排序。
4. 输出 `skill_evidence_map`：每个技能 → 出现位置（便于追问时引用）。

## Output Contract

```json
{
  "skills": {
    "proficient": ["Java", "Spring Boot", "MySQL", "Redis"],
    "familiar": ["Kafka", "Docker", "Linux"],
    "exposed": ["Kubernetes", "Spark", "Hadoop"]
  },
  "skill_evidence_map": {
    "Java": ["resume:skills_raw[0]", "resume:projects_raw[0].tech_stack"],
    "Redis": ["resume:projects_raw[0].tech_stack", "resume:internships_raw[0].responsibilities"]
  },
  "implicit_skills_count": 5,
  "explicit_skills_count": 12
}
```

## Quality Gates

- 隐式技能置信度 < 0.6 时**不**进入 `proficient`。
- 同一技能在多处出现时取最高 level_hint。
- 技能名规范化（如 "React.js" 和 "React" 视为同一技能）。
