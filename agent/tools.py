# -*- coding: utf-8 -*-
"""工具层：Agent 的"手"。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
这个文件里有**两个完全不同的东西**，初学最容易混淆：

  ① TOOL_SCHEMAS —— 给模型看的「说明书」
     模型看不见你的 Python 代码。它唯一知道的，就是我们发给它的这段 JSON：
     工具叫什么名字、什么时候该用、要传哪些参数。写得清不清楚，
     直接决定模型会不会用、用得对不对。

  ② ToolBox —— 真正执行代码的地方
     模型说"我要调 pick_question，参数是 track=coding"，
     它自己什么都不会做，只是发了个请求。**真正去执行的永远是我们的代码。**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么 ToolBox 需要"会话状态"？

  模型调 score_answer 时只能给一个 question_id —— 它没法把整道题原样背回来
  （题目里有打分规则、参考答案，很长，让它复述纯属浪费 token 且必然抄错）。
  所以 pick_question 出题时先把题目存进 ToolBox，score_answer 再取出来。

  这就是 **Agent 的短期记忆**。工具调用之所以比"调个函数"复杂，原因就在这：
  工具之间要共享上下文，而模型只负责"下指令"。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from tools.mock_tools import (
    mock_evaluator_score_answer,
    mock_jd_fetch_jd,
    mock_jd_search_jd_kb,
    mock_question_bank_pick,
    mock_report_render,
    mock_resume_read_resume,
)

# ===========================================================================
# ① 工具说明书（发给模型的 JSON Schema）
# ===========================================================================

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_resume",
            "description": "读取当前候选人的简历。面试开始后应当第一时间调用，必须先看过简历再出题。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_jd",
            "description": "读取目标岗位的 JD（职位描述），包含岗位要求技能、加分项和职责。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_jd_kb",
            "description": (
                "检索岗位知识库，取回面试情报：面试流程、高频技术考点、常见追问套路。"
                "知识库用的是**向量检索**，所以 query 直接写成一句自然语言描述你想知道什么就行，"
                "不需要堆关键词 —— 例如「缓存和数据库怎么保证一致」。"
                "问法和资料里的原话不一样也能命中，这正是它比关键词匹配强的地方。"
                "建议在出题之前检索一次，让题目贴近真实的考察重点。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言描述，例如「Redis 缓存三大问题怎么答」",
                    },
                    "top_k": {"type": "integer", "description": "返回条数，默认 3"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pick_question",
            "description": (
                "从题库里取一道题。技术面算法题用 track=coding（需带 difficulty），"
                "系统设计题用 track=system_design，HR 行为面用 track=hr（需带 stage）。"
                "每次只取一道，问完并拿到候选人回答、评分之后，再取下一道。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "track": {
                        "type": "string",
                        "enum": ["coding", "system_design", "hr"],
                        "description": "题目类型",
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["easy", "medium", "hard"],
                        "description": "仅 track=coding 时需要，默认 medium",
                    },
                    "stage": {
                        "type": "string",
                        "enum": ["self_intro", "motivation", "pressure", "career_plan"],
                        "description": "仅 track=hr 时需要，HR 面的四个阶段",
                    },
                },
                "required": ["track"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_answer",
            "description": (
                "给候选人对某道题的回答打分。question_id 必须是 pick_question 返回过的 id。"
                "候选人每回答完一题就要立刻评分，不要攒着。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string", "description": "pick_question 返回的题目 id"},
                    "answer": {"type": "string", "description": "候选人刚才的原话"},
                },
                "required": ["question_id", "answer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_report",
            "description": (
                "提交并落盘最终面试复盘报告。**必须在你认为面试全部结束后调用**，"
                "调用之前要确保技术面和 HR 面都已经问完并评过分。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "overall_score": {"type": "integer", "description": "综合评分，0-100 的整数"},
                    "radar": {
                        "type": "object",
                        "description": "六维雷达分数，每个维度 0-100",
                        "properties": {
                            "tech_depth": {"type": "integer"},
                            "system_design": {"type": "integer"},
                            "project_pitch": {"type": "integer"},
                            "coding": {"type": "integer"},
                            "behavioral": {"type": "integer"},
                            "motivation_fit": {"type": "integer"},
                        },
                        "required": ["tech_depth", "system_design", "project_pitch", "coding", "behavioral", "motivation_fit"],
                    },
                    "highlights": {"type": "array", "items": {"type": "string"}, "description": "亮点，2-4 条"},
                    "weaknesses": {"type": "array", "items": {"type": "string"}, "description": "短板，2-4 条"},
                    "improvements": {"type": "array", "items": {"type": "string"}, "description": "改进建议，3-5 条"},
                    "next_7_days_plan": {
                        "type": "array",
                        "description": "未来 7 天训练计划，7 条",
                        "items": {
                            "type": "object",
                            "properties": {
                                "day": {"type": "integer"},
                                "task": {"type": "string"},
                            },
                            "required": ["day", "task"],
                        },
                    },
                    "verdict": {"type": "string", "description": "一句话结论，例如「建议补 Kafka 后投递」"},
                },
                "required": ["overall_score", "radar", "highlights", "weaknesses", "improvements", "verdict"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_interview",
            "description": "结束整场面试。**必须在你已经调用过 submit_report 之后**才能调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "结束原因，一句话"},
                },
                "required": ["reason"],
            },
        },
    },
]


# ===========================================================================
# ② 真正执行的地方
# ===========================================================================


class ToolBox:
    """工具的实际执行者，同时持有本轮面试的会话状态。"""

    # ★ 合法取值表。注意 TOOL_SCHEMAS 里的 "enum" 只是**写给模型看的提示**，
    #   不是强制约束 —— 模型照样可能传一个不存在的值进来。
    #   真正的校验必须落在自己的代码里，否则非法输入会被静默兜底成默认值，
    #   而模型永远不知道自己传错了（实测传 difficulty="impossible" 时，
    #   底层 mock 题库会默默换成 medium 出一道题，看上去一切正常）。
    VALID_TRACKS = {"coding", "system_design", "hr"}
    VALID_DIFFICULTIES = {"easy", "medium", "hard"}
    VALID_STAGES = {"self_intro", "motivation", "pressure", "career_plan"}

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id

        # --- 会话状态（Agent 的短期记忆）---
        self.questions: dict[str, dict] = {}   # question_id -> 题目原文
        self.records: list[dict] = []           # 逐题记录：题目 / 回答 / 分数
        self.last_question: dict | None = None  # 最近一次出的题（给模拟候选人用）

        # ★ 待答题状态（第一次跑挂了之后补的，见文末「踩坑记录」）
        #   有值 = 台上有一道题还等着候选人回答。
        #   为什么要这个字段？因为"模型说话了"不等于"模型在提问" ——
        #   开场白、过渡语、口头总结都是说话。靠猜（比如看句子里有没有问号）
        #   一定会在某个边界上猜错，而猜错的代价是整个循环卡死。
        #   用状态表达，就永远不会猜错：pick_question 一出题就置位，
        #   候选人一回答就清空。
        self.pending_question: dict | None = None

        # --- 收尾状态 ---
        self.finished = False
        self.finish_reason: str | None = None
        self.report_path: str | None = None
        self.report_md_path: str | None = None

        # --- 统计 ---
        self.call_count = 0

    # -- 统一入口 -----------------------------------------------------------

    def dispatch(self, name: str, args: dict) -> tuple[bool, dict]:
        """执行一次工具调用，返回 (成功与否, 结果)。

        注意这里的异常处理策略 —— 这是 Agent 和普通程序最大的区别之一：

        **工具出错不能直接崩，要把错误信息当成"结果"交回给模型。**
        模型看到 {"error": "参数不对: ..."} 之后，会自己改参数重试。
        这就是所谓「失败恢复」：循环不因为一次失败而终止，模型有纠错的机会。
        """
        self.call_count += 1
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            return False, {"error": f"没有这个工具: {name}"}
        try:
            payload = handler(**args)
        except TypeError as exc:
            # 参数写错了 —— 告诉模型，让它自己修
            return False, {"error": f"参数不匹配: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return False, {"error": f"{type(exc).__name__}: {exc}"}

        # ★ 「成功」不能只看有没有抛异常。
        #   工具内部也会返回业务性错误（比如模型编了一个不存在的 question_id，
        #   _t_score_answer 会返回 {"error": ...}），这时没抛异常，
        #   第一版就把它当成 OK 打了出来 —— 日志里一片绿，实际全是错的，
        #   排查时完全看不出来。所以这里要再看一眼返回体。
        if isinstance(payload, dict) and payload.get("error"):
            return False, payload
        return True, payload

    # -- 各个工具的实现 -----------------------------------------------------
    # 命名约定：_t_<工具名>，dispatch 靠 getattr 自动找过来

    def _t_read_resume(self) -> dict:
        return mock_resume_read_resume(self.scenario_id)

    def _t_fetch_jd(self) -> dict:
        return mock_jd_fetch_jd(self.scenario_id)

    def _t_search_jd_kb(self, query: str, top_k: int = 3) -> dict:
        """在岗位知识库里做**向量检索**。

        ── 这一版和第一版的区别 ──
        第一版是 query.split() + 子串匹配：换个说法就检索不到 ——
        问「缓存击穿怎么答」匹配不上写着「缓存穿透」的段落，
        因为它在比字符，不是在比语义。
        现在走真正的向量检索（Chroma + embedding-3），比的是语义相似度，
        问法和资料里的原话不一样也能命中。

        ── 两个工程上的讲究 ──
        1. 知识库依赖是**惰性导入**的：没装 chromadb 时其它工具照常工作，
           只有真调检索才报错。可选依赖就该是可选的样子。
        2. 向量库没建时**回退到内置语料，而不是报错**。「还没入库」是很正常的
           状态，不该让整场面试挂掉 —— 这叫优雅降级。
        """
        try:
            from kb.search import retrieve
        except ImportError as exc:  # noqa: BLE001
            return {"error": f"知识库依赖未安装（需要 chromadb / pypdf）: {exc}"}

        try:
            hits = retrieve(query, k=top_k)
        except Exception as exc:  # noqa: BLE001
            # 检索失败要把错误交回模型（它可以改 query 重试），
            # 但绝不能伪装成"没搜到" —— 那会让它以为知识库里真的没这内容。
            return {"error": f"知识库检索失败: {type(exc).__name__}: {exc}"}

        if hits:
            return {
                "query": query,
                "top_k": top_k,
                "hits": hits,
                "hit_count": len(hits),
                "retriever": "vector: chroma + embedding-3",
                "note": "score 是 0~1 的语义相似度，越高越相关；source 是片段出处",
            }

        # 向量库为空 → 回退到场景自带的 jd_kb（关键词匹配）
        out = mock_jd_search_jd_kb(self.scenario_id, query, top_k)
        out["hit_count"] = len(out.get("hits", []))
        out["retriever"] = "mock: 关键词匹配（向量库未构建时的回退）"
        return out

    def _t_pick_question(
        self,
        track: str,
        difficulty: str | None = None,
        stage: str | None = None,
    ) -> dict:
        # 先自己做入参校验，出错就把错误交回模型让它改（失败恢复）
        if track not in self.VALID_TRACKS:
            return {"error": f"track 只能是 {sorted(self.VALID_TRACKS)} 之一，收到 {track!r}"}
        if track == "coding" and difficulty and difficulty not in self.VALID_DIFFICULTIES:
            return {"error": f"difficulty 只能是 {sorted(self.VALID_DIFFICULTIES)} 之一，收到 {difficulty!r}"}
        if track == "hr" and stage and stage not in self.VALID_STAGES:
            return {"error": f"stage 只能是 {sorted(self.VALID_STAGES)} 之一，收到 {stage!r}"}

        q = mock_question_bank_pick(
            scenario_id=self.scenario_id, track=track, difficulty=difficulty, stage=stage
        )
        if "id" not in q:
            return q  # 题库没货，原样把错误信息交回模型

        self.questions[q["id"]] = q
        self.last_question = q
        self.pending_question = q          # ★ 出题 = 上台有一道题等着回答

        # 回给模型的字段挑一下：solution_outline 和 scoring_rubric 要留着，
        # 因为后面评分要靠它；但 controls / tags 之类噪音就不必给了。
        keep = ("id", "track", "title", "description", "context", "requirements",
                "follow_up_path", "question", "scenario", "stage",
                "good_answer_outline", "solution_outline", "tags")
        return {k: q[k] for k in keep if k in q}

    def _t_score_answer(self, question_id: str, answer: str) -> dict:
        q = self.questions.get(question_id)
        if q is None:
            return {"error": f"没有出过 id={question_id} 的题，请先用 pick_question 出题"}

        result = mock_evaluator_score_answer(self.scenario_id, q, answer)
        record = {
            "question_id": question_id,
            "track": q.get("track"),
            "stage": q.get("stage"),
            "question": q.get("title") or q.get("question") or q.get("description", "")[:60],
            "answer": answer,
            "score": result.get("score"),
            "comment": result.get("comment"),
            "evidence_refs": result.get("evidence_refs", []),
        }
        self.records.append(record)
        return record

    def _t_submit_report(
        self,
        overall_score: int,
        radar: dict,
        highlights: list,
        weaknesses: list,
        improvements: list,
        verdict: str,
        next_7_days_plan: list | None = None,
    ) -> dict:
        scenario = mock_resume_read_resume(self.scenario_id)
        candidate = scenario.get("candidate", {})

        data = {
            "candidate": candidate.get("name", "未知"),
            "target_role": candidate.get("target_role", ""),
            "target_company": candidate.get("target_company", ""),
            "interview_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "overall_score": overall_score,
            "radar": radar,
            "highlights": highlights,
            "weaknesses": weaknesses,
            "improvements": improvements,
            "next_7_days_plan": next_7_days_plan or [],
            "verdict": verdict,
            "rounds": self.records,          # 逐题原始记录，报告里能回溯到原答案
            "generated_by": "orchestrator (自研调度循环)",
        }

        out = mock_report_render(self.scenario_id, "default", data)
        self.report_path = out.get("report_path")
        self.report_md_path = out.get("md_path")

        # ★ 只把路径回给模型，不把整篇 Markdown 塞回去 ——
        #   报告可能有几千字，塞进上下文纯属浪费钱，模型也不需要看到它。
        return {
            "ok": True,
            "report_path": self.report_path,
            "report_md_path": self.report_md_path,
            "round_count": len(self.records),
            "note": "报告已落盘，请不要在回复里复述全文，只做简短总结。",
        }

    def _t_end_interview(self, reason: str) -> dict:
        self.finished = True
        self.finish_reason = reason
        return {"ok": True, "reason": reason, "rounds_scored": len(self.records)}

    def consume_pending(self) -> dict | None:
        """取走当前待答题并清空。

        候选人答完一道题就调一次。返回值拿去做候选人的回答依据，
        同时标记"这道题已经用过了"，避免同一道题被反复回答。
        """
        q, self.pending_question = self.pending_question, None
        return q

    # -- 给外部用的汇总 -----------------------------------------------------

    def summary(self) -> dict:
        scores = [r["score"] for r in self.records if isinstance(r.get("score"), int)]
        return {
            "tool_calls": self.call_count,
            "questions_asked": len(self.questions),
            "answers_scored": len(self.records),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
            "finished": self.finished,
            "finish_reason": self.finish_reason,
            "report_path": self.report_path,
        }

    def dump_records(self) -> str:
        return json.dumps(self.records, ensure_ascii=False, indent=2)
