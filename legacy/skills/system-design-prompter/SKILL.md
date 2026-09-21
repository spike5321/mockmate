---
name: system-design-prompter
description: 按岗位高频题选 1 道系统设计题，并给出 3 步追问路径
metadata:
  version: "0.1.0"
  maturity: demo
---

# System Design Prompter

## Purpose

为候选人出 1 道贴近岗位的高频系统设计题（短链 / 秒杀 / Feed 流 / 排行榜等），并提前设计 3 步追问路径，根据候选人回答的深度逐步深入。

## Inputs

- `target_role`：岗位名（后端 / 前端 / 数据等）
- `jd_match`：JD 匹配结果，决定出题方向
- 候选人项目经验（避免出"亿级流量"给只做过 1200 QPS 的候选人）

## Procedure

1. 从 `mock_question_bank.pick(track="system_design", role)` 拉候选题列表。
2. 选 1 道最贴近候选人经验的题：
   - 后端实习 → 短链 / 秒杀 / Feed 流
   - 数据实习 → 实时数仓 / 离线数仓
   - 前端实习 → 无限滚动 / 协同编辑
3. 设计 3 步追问路径（从浅到深）：
   - Step 1: 数据模型 / API 设计
   - Step 2: 容量估算 / 性能瓶颈
   - Step 3: 一致性 / 容错 / 监控
4. 输出题面 + 追问路径。

## Output Contract

```json
{
  "question_id": "sd-short-url",
  "title": "设计一个短链生成系统",
  "context": "假设你做一个类似 t.cn 的短链服务，QPS 约 1 万，写多读少。",
  "requirements": [
    "生成短链",
    "短链跳转原 URL",
    "支持自定义短链"
  ],
  "follow_up_path": [
    {
      "step": 1,
      "question": "你会怎么设计数据模型和 API？",
      "expected_outline": "短链 -> 原 URL 映射，REST API..."
    },
    {
      "step": 2,
      "question": "QPS 1 万，需要分库分表吗？缓存怎么设计？",
      "expected_outline": "Redis 缓存 + 哈希分片..."
    },
    {
      "step": 3,
      "question": "短链生成算法怎么选？发号器、Hash、Base62？",
      "expected_outline": "Snowflake / 自增 + Base62..."
    }
  ],
  "scoring_rubric": {
    "data_model": 2,
    "api_design": 2,
    "scalability": 3,
    "consistency": 2,
    "tradeoff_analysis": 1
  },
  "evidence_refs": ["question:sd-short-url"]
}
```

## Quality Gates

- 追问路径必须 3 步，每步对应一个评分维度。
- 题面不超出候选人经验上限 1 个量级（如只做过 1200 QPS 不出 100 万 QPS 的题）。
- 评分要点覆盖：数据模型、API、可扩展性、一致性、权衡分析。
