---
name: resume-parser
description: 把非结构化简历文本切分成基本信息 / 技能 / 项目 / 实习 / 荣誉 5 段
metadata:
  version: "0.1.0"
  maturity: demo
---

# Resume Parser

## Purpose

把一份非结构化的简历（Markdown / 纯文本 / PDF 提取后的文本）切分成结构化 5 段：基本信息、技能、项目、实习、荣誉/奖项。这是后续 `skill-extractor` 和 `jd-matcher` 的基础。

## Inputs

- `resume_text`（string）：原始简历文本
- `resume_format`（"markdown" | "plain" | "pdf_extracted"）

## Procedure

1. 识别标题行（学校名 / "教育背景" / "项目经历" / "实习经历" / "技能" / "荣誉"）作为段分隔符。
2. 把每段内容解析为对应结构：
   - 基本信息：姓名、学校、专业、年级、GPA、联系方式
   - 技能：技能名 + 熟练度关键词（"熟练" / "了解" / "熟悉" / "精通"）
   - 项目：项目名 + 角色 + 时间 + 技术栈 + 产出（用 bullet 列表）
   - 实习：公司 + 岗位 + 时间 + 职责（用 bullet 列表）
   - 荣誉：奖项 + 时间
3. 找不到的字段填 `null`，不要编造。
4. 保留每段的 `source_line` 引用，便于回溯。

## Output Contract

```json
{
  "basic": {
    "name": "Zhang San",
    "school": "XX大学",
    "major": "计算机科学与技术",
    "year": "大三",
    "gpa": 3.6,
    "contact": "zhangsan@xx.edu.cn"
  },
  "skills_raw": [
    {"name": "Java", "level_hint": "熟练", "source_line": "熟悉 Java、Spring Boot"},
    {"name": "Spring Boot", "level_hint": "熟练", "source_line": "熟悉 Java、Spring Boot"}
  ],
  "projects_raw": [
    {
      "name": "校园二手交易平台",
      "role": "后端主程",
      "duration": "2025-03 ~ 2025-06",
      "tech_stack": ["Spring Boot", "MySQL", "Redis"],
      "bullets": ["QPS 1200", "上线 6 个月稳定运行"],
      "source_line": "校园二手交易平台（2025.03-2025.06）..."
    }
  ],
  "internships_raw": [...],
  "honors_raw": [...],
  "data_gaps": ["未找到联系方式", "GPA 字段为空"]
}
```

## Quality Gates

- 每段至少要有 1 个 `source_line` 引用，否则视为"该段为空"。
- 找不到的字段一律 `null` + 加入 `data_gaps`，**绝不**编造内容。
- 技能名去重：相同技能出现多次只保留 1 个，取最高 level_hint。
