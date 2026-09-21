"""
Mock 工具实现 - MockMate 面试官联盟

5 个 mock 工具（HTTP 工具网关调用）：
  1. mock_resume        - 读取候选人简历
  2. mock_jd            - 读取/检索岗位 JD
  3. mock_question_bank - 算法/系统设计/HR 题库
  4. mock_evaluator     - 答案评分
  5. mock_report        - 渲染结构化报告

所有工具都是纯函数 + 读取 scenarios/{scenario_id}.json，零外部依赖。
未来替换为真实 MCP 时，Agent 的 Prompt/Skill/工具契约保持稳定。
"""

import json
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 路径与场景加载
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "scenarios"


def load_scenario(scenario_id: str) -> Dict[str, Any]:
    """加载场景 JSON。"""
    path = SCENARIOS_DIR / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {scenario_id}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. mock_resume
# ---------------------------------------------------------------------------


def mock_resume_read_resume(scenario_id: str) -> Dict[str, Any]:
    """读取候选人简历。

    入参: {}
    出参: { "resume_id": ..., "candidate": {...}, "resume_text": "..." }
    """
    scenario = load_scenario(scenario_id)
    candidate = scenario.get("candidate", {})
    return {
        "resume_id": scenario_id,
        "candidate": candidate,
        "resume_text": candidate.get("resume_text", ""),
        "source": "mock_resume.read_resume",
    }


# ---------------------------------------------------------------------------
# 2. mock_jd
# ---------------------------------------------------------------------------


def mock_jd_fetch_jd(scenario_id: str, company: Optional[str] = None, role: Optional[str] = None) -> Dict[str, Any]:
    """获取目标 JD。"""
    scenario = load_scenario(scenario_id)
    jd = scenario.get("target_jd", {})
    return {
        "company": company or jd.get("company", ""),
        "role": role or jd.get("role", ""),
        "required_skills": jd.get("required_skills", []),
        "bonus_skills": jd.get("bonus_skills", []),
        "responsibilities": jd.get("responsibilities", []),
        "jd_text": jd.get("jd_text", ""),
        "source": "mock_jd.fetch_jd",
    }


def mock_jd_search_jd_kb(scenario_id: str, query: str, top_k: int = 3) -> Dict[str, Any]:
    """RAG 兜底：从 JD 知识库检索同岗位常见要求。"""
    scenario = load_scenario(scenario_id)
    jd_kb = scenario.get("jd_kb", [])
    # 简单关键词匹配 + 截断
    results = []
    for entry in jd_kb:
        score = sum(1 for kw in query.split() if kw in entry.get("text", ""))
        if score > 0:
            results.append({"score": score, **entry})
    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "query": query,
        "top_k": top_k,
        "hits": results[:top_k],
        "source": "mock_jd.search_jd_kb (RAG)",
    }


# ---------------------------------------------------------------------------
# 3. mock_question_bank
# ---------------------------------------------------------------------------

# 内置题库（demo 规模，按需扩展）
QUESTION_BANK = {
    "coding": {
        "medium": [
            {
                "id": "lc-146-lru-cache",
                "title": "LRU 缓存",
                "tags": ["哈希表", "链表", "设计"],
                "description": "请你设计并实现一个 LRU (Least Recently Used) 缓存，支持 get 和 put 操作，要求 O(1) 时间复杂度。",
                "solution_outline": "哈希表 + 双向链表，O(1) get/put。",
                "scoring_rubric": {
                    "data_structure_choice": 3,
                    "time_complexity": 3,
                    "edge_cases": 2,
                    "code_clarity": 2,
                },
            },
            {
                "id": "lc-25-reverse-k-group",
                "title": "K 个一组翻转链表",
                "tags": ["链表", "递归"],
                "description": "给你链表的头节点 head，每 k 个节点一组进行翻转，返回修改后的链表。k 是正整数，小于等于链表长度。",
                "solution_outline": "迭代 + 虚拟头节点，每组翻转后拼接。",
                "scoring_rubric": {
                    "data_structure_choice": 3,
                    "time_complexity": 2,
                    "edge_cases": 3,
                    "code_clarity": 2,
                },
            },
            {
                "id": "lc-200-island-number",
                "title": "岛屿数量",
                "tags": ["DFS", "BFS", "图"],
                "description": "给你一个由 '1'（陆地）和 '0'（水）组成的二维网格，计算岛屿的数量。",
                "solution_outline": "DFS / BFS 遍历，访问过的格子标记。",
                "scoring_rubric": {
                    "data_structure_choice": 3,
                    "time_complexity": 2,
                    "edge_cases": 2,
                    "code_clarity": 3,
                },
            },
        ],
        "easy": [
            {
                "id": "lc-1-two-sum",
                "title": "两数之和",
                "tags": ["哈希表", "数组"],
                "description": "给定整数数组和目标值，返回两个数的下标使它们相加等于目标值。",
                "solution_outline": "哈希表一次遍历，O(n)。",
                "scoring_rubric": {"data_structure_choice": 3, "time_complexity": 3, "edge_cases": 2, "code_clarity": 2},
            }
        ],
    },
    "system_design": {
        "backend_intern": [
            {
                "id": "sd-short-url",
                "title": "设计一个短链生成系统",
                "context": "假设你做一个类似 t.cn 的短链服务，QPS 约 1 万，写多读少。",
                "requirements": ["生成短链", "短链跳转原 URL", "支持自定义短链"],
                "follow_up_path": [
                    {"step": 1, "question": "数据模型和 API 怎么设计？", "expected_outline": "短链 -> 原 URL 映射，REST API..."},
                    {"step": 2, "question": "QPS 1 万，缓存怎么设计？", "expected_outline": "Redis 缓存 + 哈希分片..."},
                    {"step": 3, "question": "短链生成算法怎么选？", "expected_outline": "Snowflake / 自增 + Base62..."},
                ],
                "scoring_rubric": {"data_model": 2, "api_design": 2, "scalability": 3, "consistency": 2, "tradeoff_analysis": 1},
            },
            {
                "id": "sd-seckill",
                "title": "设计一个秒杀系统",
                "context": "商品 1000 件，10 万用户同时抢购，怎么保证不超卖？",
                "requirements": ["不超卖", "高并发", "良好用户体验"],
                "follow_up_path": [
                    {"step": 1, "question": "前端怎么限流？", "expected_outline": "按钮置灰 + 验证码 + 队列"},
                    {"step": 2, "question": "库存怎么扣减？", "expected_outline": "Redis 预扣 + 异步落 DB"},
                    {"step": 3, "question": "如何防作弊？", "expected_outline": "风控 + IP 限流 + 设备指纹"},
                ],
                "scoring_rubric": {"data_model": 2, "api_design": 2, "scalability": 3, "consistency": 2, "tradeoff_analysis": 1},
            },
        ],
    },
    "hr": {
        "self_intro": [
            {
                "id": "hr-self-intro-001",
                "stage": "self_intro",
                "question": "请用 1 分钟介绍你自己，重点说说你最匹配这个岗位的 1 段经历。",
                "scoring_rubric": {"structure": 2, "highlight_match": 3, "authenticity": 3, "time_control": 2},
                "good_answer_outline": "学校 + 专业 + 关键项目 + 为什么匹配",
            }
        ],
        "motivation": [
            {
                "id": "hr-motivation-001",
                "stage": "motivation",
                "question": "你为什么想加入我们公司？",
                "scoring_rubric": {"sincerity": 4, "depth": 3, "match": 3},
                "good_answer_outline": "对业务的理解 + 个人兴趣 + 长期规划",
            }
        ],
        "pressure": [
            {
                "id": "hr-pressure-deadline-001",
                "scenario": "deadline_conflict",
                "question": "你同时被分配了 2 个紧急任务，PM 说都重要，明天都要上线，你怎么办？",
                "scoring_rubric": {"stress_resistance": 3, "analysis": 3, "communication": 2, "decision_making": 2},
                "good_answer_outline": "评估工作量 + 风险 + 业务影响 → 主动沟通排序 + 给出建议 → 必要时求助",
            }
        ],
        "career_plan": [
            {
                "id": "hr-career-001",
                "stage": "career_plan",
                "question": "未来 1-3 年你有什么规划？",
                "scoring_rubric": {"clarity": 3, "feasibility": 3, "motivation": 4},
                "good_answer_outline": "短期 (打基础) + 中期 (深耕领域) + 长期 (独当一面)",
            }
        ],
    },
}


def mock_question_bank_pick(
    scenario_id: str,
    track: str,
    difficulty: Optional[str] = None,
    focus: Optional[List[str]] = None,
    stage: Optional[str] = None,
) -> Dict[str, Any]:
    """从题库选 1 道题。

    入参: { track, difficulty?, focus?, stage? }
      - track: "coding" | "system_design" | "hr"
      - difficulty: "easy" | "medium" | "hard"（仅 coding 必填）
      - focus: 知识点列表（仅 coding 生效）
      - stage: hr 子阶段（self_intro / motivation / pressure / career_plan）
    """
    bank = QUESTION_BANK.get(track, {})

    if track == "coding":
        candidates = bank.get(difficulty or "medium", [])
        if focus:
            # 按 focus 标签优先排序
            candidates = sorted(candidates, key=lambda q: -sum(1 for f in focus if f in q.get("tags", [])))
        if not candidates:
            candidates = QUESTION_BANK["coding"]["medium"]
        question = random.choice(candidates[:3])  # 在 top3 中随机
    elif track == "system_design":
        scenario = load_scenario(scenario_id)
        role_key = "backend_intern" if "后端" in scenario.get("target_jd", {}).get("role", "") else "backend_intern"
        candidates = bank.get(role_key, bank.get("backend_intern", []))
        question = random.choice(candidates) if candidates else candidates[0]
    elif track == "hr":
        stage = stage or "self_intro"
        candidates = bank.get(stage, [])
        question = candidates[0] if candidates else None
    else:
        question = None

    if question is None:
        return {"error": f"No question found for track={track}, stage={stage}", "source": "mock_question_bank.pick"}

    return {**question, "track": track, "source": "mock_question_bank.pick"}


# ---------------------------------------------------------------------------
# 4. mock_evaluator
# ---------------------------------------------------------------------------


def mock_evaluator_cross_check(scenario_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """校准评分（demo 阶段用规则校准，真实环境接 LLM 裁判）。"""
    # demo 阶段：直接返回原分数 + 校准说明
    return {
        "calibrated_record": record,
        "calibration_log": [
            {
                "round_id": record.get("track", "unknown"),
                "original_score": record.get("score", 0),
                "calibrated_score": record.get("score", 0),
                "reason": "demo 阶段：保持原分（真实环境接 LLM 裁判投票）",
            }
        ],
        "source": "mock_evaluator.cross_check",
    }


def mock_evaluator_score_answer(scenario_id: str, question: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """对单道题答案打分（demo 用规则，真实环境用 LLM）。"""
    answer_len = len(answer.strip())
    if answer_len < 20:
        return {"score": 3, "comment": "回答过短，未展开", "evidence_refs": [f"answer:{question.get('id', 'unknown')}"]}
    if answer_len < 100:
        return {"score": 6, "comment": "回答有一定内容，可再深入", "evidence_refs": [f"answer:{question.get('id', 'unknown')}"]}
    return {"score": 8, "comment": "回答较充分（demo 自动评分，真实环境接 LLM 裁判）", "evidence_refs": [f"answer:{question.get('id', 'unknown')}"]}


# ---------------------------------------------------------------------------
# 5. mock_report
# ---------------------------------------------------------------------------


def mock_report_render(
    scenario_id: str,
    template: str,
    data: Dict[str, Any],
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """渲染结构化报告。

    返回: { "report_md": "...", "report_json": {...}, "report_path": "..." }

    `out_dir` 指定报告落盘目录，默认写 `scenarios/`（真实运行就该写那里）。
    自检脚本（`e2e_test.py`）会传一个临时目录 —— 否则跑一次自检就把
    `scenarios/*.report.md` 覆盖成 mock 数据了，那是真实运行产物的位置。
    """
    target_dir = Path(out_dir) if out_dir else SCENARIOS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    # 写 JSON 报告
    report_path = target_dir / f"{scenario_id}.report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 渲染 Markdown 报告
    md = _render_markdown_report(data)
    md_path = target_dir / f"{scenario_id}.report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    return {
        "report_md": md,
        "report_json": data,
        "report_path": str(report_path),
        "md_path": str(md_path),
        "source": "mock_report.render",
    }


#: 报告里显示的题型中文名
_TRACK_LABELS = {
    "coding": "算法题",
    "system_design": "系统设计",
    "project": "项目深挖",
    "hr": "HR 行为面",
}

#: 评分维度的短标签（给报告读者看的，不是给模型看的）。
#   注意它和 agent/evaluator.py 里的 DIMENSION_HINTS 是**两份不同的东西**：
#   那边是「给模型的判分说明」（长、中性、要能覆盖多种题型），
#   这边是「报告表格里的列名」（3~5 个字，塞得进一行）。
#   混成一份的话，两边都会别扭。
_DIM_LABELS = {
    "data_structure_choice": "选型",
    "time_complexity": "复杂度",
    "edge_cases": "边界",
    "code_clarity": "代码表达",
    "correctness": "正确性",
    "complexity": "复杂度",
    "data_model": "数据模型",
    "api_design": "接口设计",
    "scalability": "扩展性",
    "consistency": "一致性",
    "tradeoff_analysis": "权衡取舍",
    "completeness": "完整度",
    "specificity": "具体性",
    "technical_depth": "技术深度",
    "impact": "结果影响",
    "reflection": "反思",
    "structure": "结构",
    "highlight_match": "亮点匹配",
    "authenticity": "真实度",
    "time_control": "信息密度",
    "sincerity": "真诚度",
    "depth": "思考深度",
    "match": "岗位匹配",
    "stress_resistance": "抗压",
    "analysis": "分析",
    "communication": "沟通",
    "decision_making": "决策",
    "clarity": "清晰度",
    "feasibility": "可行性",
    "motivation": "动机",
    "relevance": "切题",
    "substance": "实质内容",
    "fit": "匹配度",
}


def _render_markdown_report(data: Dict[str, Any]) -> str:
    """把数据渲染成 Markdown 报告。"""
    lines = []
    lines.append(f"# MockMate 模拟面试报告")
    lines.append("")
    lines.append(f"**候选人**: {data.get('candidate', '')}  ")
    lines.append(f"**目标岗位**: {data.get('target_role', '')}  ")
    lines.append(f"**面试日期**: {data.get('interview_date', '')}  ")
    lines.append("")

    # 中断兜底：这份报告是故障后补出来的，必须让人一眼看见，别当成完整结果读
    if data.get("interrupted"):
        lines.append("> ⚠️ **本次面试提前中断** —— 以下仅为已完成部分的结果，"
                     "不代表完整面试表现。原因见文末「结论」。")
        lines.append("")

    lines.append(f"**总体评分**: **{data.get('overall_score', 0)}** / 100")
    if data.get("question_avg") is not None:
        # ★ 两个数字并排显示，作用不一样：
        #   总体分是模型的综合判断（含印象分），逐题均分是硬数据。
        #   放在一起，读者一眼能看出两者是否自洽 ——
        #   如果逐题都是 8 分而总体只有 60，那这个总体分就值得怀疑了。
        lines.append(f"**逐题均分**: {data['question_avg']} / 10（由系统按逐题评分算出）")
    lines.append("")

    # 雷达
    radar = data.get("radar", {})
    if radar:
        lines.append("## 6 维雷达")
        lines.append("")
        lines.append("| 维度 | 分数 |")
        lines.append("|---|---|")
        for k, v in radar.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # 亮点
    highlights = data.get("highlights", [])
    if highlights:
        lines.append("## 亮点")
        lines.append("")
        for h in highlights:
            lines.append(f"- {h.get('text', h) if isinstance(h, dict) else h}")
        lines.append("")

    # 短板
    weaknesses = data.get("weaknesses", [])
    if weaknesses:
        lines.append("## 短板")
        lines.append("")
        for w in weaknesses:
            lines.append(f"- {w.get('text', w) if isinstance(w, dict) else w}")
        lines.append("")

    # 改进建议
    improvements = data.get("improvements", [])
    if improvements:
        lines.append("## 改进建议")
        lines.append("")
        for i, imp in enumerate(improvements, 1):
            lines.append(f"{i}. {imp}")
        lines.append("")

    # 7 天训练计划
    plan = data.get("next_7_days_plan", [])
    if plan:
        lines.append("## 下一轮 7 天训练计划")
        lines.append("")
        lines.append("| 天 | 任务 |")
        lines.append("|---|---|")
        for p in plan:
            lines.append(f"| Day {p.get('day', '')} | {p.get('task', '')} |")
        lines.append("")

    # 结论
    verdict = data.get("verdict", "")
    if verdict:
        lines.append("## 结论")
        lines.append("")
        lines.append(f"> {verdict}")
        lines.append("")

    # ------------------------------------------------------------------
    # 逐题评分明细（数据附录）
    #
    # ★ 这一块是**代码生成的硬数据**，不是模型写的 —— 这也是它存在的意义：
    #   亮点/短板/建议都是模型的主观解读，读者没法验证；
    #   而这里的每一分、每个维度、每条判分依据，都能逐条回溯到原答案。
    #   有这块在，报告的"可信部分"和"解读部分"就分得开了。
    # ------------------------------------------------------------------
    rounds = data.get("rounds", [])
    if rounds:
        lines.append("## 逐题评分明细")
        lines.append("")

        track_avg = data.get("track_avg") or {}
        if track_avg:
            seg = " ・ ".join(
                f"{_TRACK_LABELS.get(t, t)} {v}" for t, v in track_avg.items()
            )
            lines.append(f"- 分项均分：{seg}（10 分制）")

        llm_n = sum(1 for r in rounds if r.get("source") == "llm")
        if llm_n:
            lines.append(f"- 评分来源：LLM 评分 {llm_n} 题，规则降级 {len(rounds) - llm_n} 题")
        else:
            lines.append("- 评分来源：全部为规则降级评分（LLM 评分未生效）")
        lines.append("")

        for i, r in enumerate(rounds, 1):
            track = _TRACK_LABELS.get(str(r.get("track")), str(r.get("track") or ""))
            title = " ".join(str(r.get("question") or "").split())
            lines.append(f"### {i}. {title[:46]} · {track} · **{r.get('score')} / 10**")
            lines.append("")

            dims = r.get("dimensions") or {}
            weights = r.get("weights") or {}
            if dims:
                bits = []
                for key, rate in dims.items():
                    label = _DIM_LABELS.get(key, key)
                    weight = weights.get(key)
                    suffix = f"（权重 {weight:g}）" if isinstance(weight, (int, float)) else ""
                    try:
                        bits.append(f"{label} `{float(rate):.2f}`{suffix}")
                    except (TypeError, ValueError):
                        bits.append(f"{label} `{rate}`{suffix}")
                lines.append("- 维度得分：" + " · ".join(bits))

            comment = r.get("comment")
            if comment:
                lines.append(f"- 点评：{comment}")

            evidence = r.get("evidence_refs") or []
            if evidence:
                quote = " ".join(str(evidence[0]).split())[:80]
                lines.append(f"- 判分依据：「{quote}」")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------

TOOL_REGISTRY = {
    "mock_resume": {
        "read_resume": mock_resume_read_resume,
    },
    "mock_jd": {
        "fetch_jd": mock_jd_fetch_jd,
        "search_jd_kb": mock_jd_search_jd_kb,
    },
    "mock_question_bank": {
        "pick": mock_question_bank_pick,
    },
    "mock_evaluator": {
        "cross_check": mock_evaluator_cross_check,
        "score_answer": mock_evaluator_score_answer,
    },
    "mock_report": {
        "render": mock_report_render,
    },
}


def call_tool(scenario_id: str, tool_name: str, function_name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一入口：通过 tool_name + function_name 调用 mock 工具。"""
    args = args or {}
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        return {"error": f"Unknown tool: {tool_name}"}
    func = tool.get(function_name)
    if func is None:
        return {"error": f"Unknown function: {tool_name}.{function_name}"}
    try:
        return func(scenario_id=scenario_id, **args)
    except TypeError:
        # 函数签名不匹配 scenario_id 时，按需调整
        return func(**args)
