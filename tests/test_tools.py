# -*- coding: utf-8 -*-
"""工具层单测：ToolBox 的入参校验、状态流转、评分落账、报告锚定。

这里全部用 evaluator=None（规则打分），所以**不需要 API Key、不联网**。
被测的是确定性逻辑 —— 也就是"能不能被机器判定对错"的那部分。

有意没测的：`_t_read_resume` / `_t_fetch_jd` 只是把 scenario JSON 原样读出来，
测它们等于测"文件读得出来吗"，价值很低。
"""

from __future__ import annotations

import json

import pytest

from agent.tools import TOOL_SCHEMAS, ToolBox

SCENARIO = "backend_intern"

#: 100 字以上 → 规则打分给 8 分。降级路径的测试需要它。
LONG_ANSWER = "我先说结论，再从三个层面展开说明这个方案的取舍和边界条件。" * 6
SHORT_ANSWER = "不太清楚。"


@pytest.fixture
def box() -> ToolBox:
    """一个没接评分器的工具箱（离线、规则打分）。"""
    return ToolBox(SCENARIO, evaluator=None)


# ===========================================================================
# 工具说明书本身
# ===========================================================================


def test_schema_names_have_implementations(box):
    """每条发给模型的"说明书"背后都得有一个真实现 —— 否则模型一调就报错。

    这条测试是防呆：以后加工具时忘了写 `_t_xxx`，这里会立刻红。
    """
    for item in TOOL_SCHEMAS:
        name = item["function"]["name"]
        assert hasattr(box, f"_t_{name}"), f"工具 {name} 有说明书但没有实现"


def test_schema_is_json_serializable():
    """说明书要真的能塞进请求体 —— 里面混进不可序列化的对象就发不出去。"""
    json.dumps(TOOL_SCHEMAS, ensure_ascii=False)


def test_end_interview_requires_submit_report_first():
    """提示词里写死的顺序约束：先交报告、再结束。"""
    text = next(
        s["function"]["description"]
        for s in TOOL_SCHEMAS
        if s["function"]["name"] == "end_interview"
    )
    assert "submit_report" in text


# ===========================================================================
# dispatch：错误必须"交回模型"，而不是崩掉或假装成功
# ===========================================================================


def test_unknown_tool_is_reported_not_raised(box):
    """工具名写错 → 返回 False + 错误，循环不中断（模型看到会自己改）。"""
    ok, payload = box.dispatch("no_such_tool", {})
    assert ok is False
    assert "没有这个工具" in payload["error"]


def test_wrong_argument_name_is_caught(box):
    """参数名写错会抛 TypeError —— 必须被兜住，当成一次可恢复的失败。"""
    ok, payload = box.dispatch("pick_question", {"track": "coding", "bogus": 1})
    assert ok is False
    assert "参数不匹配" in payload["error"]


def test_missing_required_argument_is_caught(box):
    ok, payload = box.dispatch("pick_question", {})
    assert ok is False
    assert "参数不匹配" in payload["error"]


def test_business_error_is_not_counted_as_success(box):
    """★ 这是踩过的坑，必须有回归测试。

    工具内部返回 {"error": ...} 时并没有抛异常。第一版只看"有没有抛异常"，
    于是把它当成成功打了 OK —— 日志里一片绿，实际全是错的。

    用 pick_question 传一个非法 track 来触发这条业务错误路径。
    """
    ok, payload = box.dispatch("pick_question", {"track": "poetry"})
    assert ok is False, "业务错误被当成了成功"
    assert "track" in payload["error"]


# ===========================================================================
# 入参校验：enum 只是给模型看的提示，不构成约束
# ===========================================================================


def test_invalid_track_rejected(box):
    ok, payload = box.dispatch("pick_question", {"track": "poetry"})
    assert ok is False
    assert "poetry" in payload["error"]


def test_invalid_difficulty_rejected(box):
    """★ 这条防的是一个"看起来成功的失败"。

    题库对不认识的 difficulty 会**静默退回 medium**（见下一条测试），
    所以不自己校验的话，模型传了 impossible 也照样拿到一道题，
    它永远不会发现自己传错了。校验必须落在我们这一侧。
    """
    ok, payload = box.dispatch(
        "pick_question", {"track": "coding", "difficulty": "impossible"}
    )
    assert ok is False
    assert "difficulty" in payload["error"]


def test_mock_bank_would_have_silently_defaulted(box):
    """上一条测试的反证：底层题库确实会悄悄兜底，所以校验不能指望它。"""
    from tools.mock_tools import mock_question_bank_pick

    q = mock_question_bank_pick(SCENARIO, track="coding", difficulty="impossible")
    assert "id" in q, "题库行为变了：它现在会拒绝非法 difficulty"


def test_invalid_stage_rejected(box):
    ok, payload = box.dispatch("pick_question", {"track": "hr", "stage": "nope"})
    assert ok is False
    assert "stage" in payload["error"]


def test_difficulty_ignored_for_non_coding_track(box):
    """行为锁定：difficulty 只在 coding 下校验，别的题型传了也不报错。"""
    ok, _ = box.dispatch(
        "pick_question", {"track": "system_design", "difficulty": "impossible"}
    )
    assert ok is True


# ===========================================================================
# pick_question：状态流转
# ===========================================================================


def test_pick_question_registers_and_arms_pending(box):
    """出题要做三件事：登记进 questions、记 last_question、置 pending。

    pending_question 是整套循环的"开关"—— 没有它就只能靠猜模型是不是在提问。
    """
    ok, q = box.dispatch("pick_question", {"track": "system_design"})
    assert ok is True
    assert q["id"] in box.questions
    assert box.last_question["id"] == q["id"]
    assert box.pending_question is not None
    assert box.pending_question["id"] == q["id"]


def test_pick_question_strips_noise_fields(box):
    """回给模型的字段要挑过：评分要用的留着，给人看的噪音不给。"""
    ok, q = box.dispatch("pick_question", {"track": "coding", "difficulty": "medium"})
    assert ok is True
    allowed = {
        "id", "track", "title", "description", "context", "requirements",
        "follow_up_path", "question", "scenario", "stage",
        "good_answer_outline", "solution_outline", "tags",
    }
    assert set(q) <= allowed
    assert "scoring_rubric" not in q


def test_invalid_pick_does_not_arm_pending(box):
    """被拦下的出题不能留下副作用 —— 否则候选人会去回答一道不存在的题。"""
    box.dispatch("pick_question", {"track": "poetry"})
    assert box.pending_question is None
    assert box.questions == {}


# ===========================================================================
# log_custom_question：给"自拟题"补一条合法路径
# ===========================================================================


def test_custom_question_gets_sequential_id(box):
    """自拟题的 id 由系统生成，模型不再需要（也不允许）自己编。"""
    ok1, q1 = box.dispatch(
        "log_custom_question", {"track": "project", "question": "你项目为什么选 Redis？"}
    )
    ok2, q2 = box.dispatch(
        "log_custom_question", {"track": "project", "question": "压测数据怎么来的？"}
    )
    assert (ok1, ok2) == (True, True)
    assert q1["id"] == "custom-01"
    assert q2["id"] == "custom-02"


def test_custom_question_rejects_empty_text(box):
    ok, payload = box.dispatch("log_custom_question", {"track": "project", "question": "   "})
    assert ok is False
    assert "question" in payload["error"]


def test_custom_question_rejects_unknown_track(box):
    ok, payload = box.dispatch(
        "log_custom_question", {"track": "poetry", "question": "随便问问"}
    )
    assert ok is False
    assert "track" in payload["error"]


def test_custom_question_arms_pending_like_bank_question(box):
    """★ 关键一致性：自拟题和题库题在状态上完全一样，下游才不用改。"""
    box.dispatch(
        "log_custom_question", {"track": "project", "question": "讲讲你的压测数据"}
    )
    assert box.pending_question["id"] == "custom-01"
    assert box.pending_question["custom"] is True


def test_custom_question_keeps_rubric_in_outline_field(box):
    """rubric 存进 good_answer_outline —— 复用了题库题已有的字段，评分器不用改。"""
    ok, q = box.dispatch(
        "log_custom_question",
        {"track": "project", "question": "讲讲性能优化", "rubric": "量化数据, 踩过的坑"},
    )
    assert ok is True
    assert box.questions[q["id"]]["good_answer_outline"] == "量化数据, 踩过的坑"


# ===========================================================================
# score_answer：没有合法 id 时要给出「合法路径」
# ===========================================================================


def test_score_unknown_id_returns_hint(box):
    """★ 弱模型会自己编 id（run13 编了 13 个）。

    光说"这个 id 不存在"没用 —— 它想完成任务，只是不知道正确的路。
    报错必须捎上"该怎么拿到一个存在的 id"。
    """
    ok, payload = box.dispatch(
        "score_answer", {"question_id": "pick_question_coding_1", "answer": LONG_ANSWER}
    )
    assert ok is False
    assert "没有出过" in payload["error"]
    assert "hint" in payload
    assert "log_custom_question" in payload["hint"]


def test_score_after_pick_appends_record(box):
    _, q = box.dispatch("pick_question", {"track": "coding", "difficulty": "medium"})
    ok, record = box.dispatch("score_answer", {"question_id": q["id"], "answer": LONG_ANSWER})
    assert ok is True
    assert record["question_id"] == q["id"]
    assert isinstance(record["score"], int)
    assert record["track"] == "coding"
    assert len(box.records) == 1


def test_record_carries_source_and_dimensions(box):
    """降级也要标出来 —— 报告里必须能看出哪几题不是 LLM 评的。"""
    _, q = box.dispatch("pick_question", {"track": "system_design"})
    _, record = box.dispatch("score_answer", {"question_id": q["id"], "answer": LONG_ANSWER})
    assert record["source"] in {"rule", "rule-fallback", "llm"}
    assert isinstance(record["dimensions"], dict)


def test_pending_survives_until_consumed(box):
    """consume_pending 是"取走并清空"—— 候选人答完一次就不能再答第二次。"""
    box.dispatch("pick_question", {"track": "hr", "stage": "self_intro"})
    first = box.consume_pending()
    assert first is not None
    assert box.pending_question is None
    assert box.consume_pending() is None


# ===========================================================================
# search_jd_kb：检索失败和检索为空是两件事
# ===========================================================================


def test_search_failure_is_an_error_not_empty_result(box, monkeypatch):
    """★ 检索报错绝不能伪装成"没搜到"—— 那会让模型以为知识库里真没这内容。"""
    pytest.importorskip("chromadb")
    from kb import search

    def boom(query, k=3):
        raise RuntimeError("向量库坏了")

    monkeypatch.setattr(search, "retrieve", boom)
    ok, payload = box.dispatch("search_jd_kb", {"query": "缓存一致性"})
    assert ok is False
    assert "检索失败" in payload["error"]


def test_empty_vector_store_falls_back_to_mock(box, monkeypatch):
    """向量库还没建 → 退到内置语料，而不是让面试挂掉（优雅降级）。"""
    pytest.importorskip("chromadb")
    from kb import search

    monkeypatch.setattr(search, "retrieve", lambda query, k=3: [])
    ok, payload = box.dispatch("search_jd_kb", {"query": "缓存 数据库"})
    assert ok is True
    assert "回退" in payload["retriever"]


# ===========================================================================
# 报告：总体分要和逐题分对得上
# ===========================================================================


def _radar(value: int = 80) -> dict:
    return {
        "tech_depth": value, "system_design": value, "project_pitch": value,
        "coding": value, "behavioral": value, "motivation_fit": value,
    }


def test_submit_report_anchors_overall_score_to_records(box, sandbox_scenarios):
    """★ 报告里的 question_avg 是代码算的，不是模型拍的。

    模型没有"逐题均分"的概念，容易写出「逐题 7~8 分、总体 75 分」这种
    对不上的组合。所以系统自己算一个锚回给它。
    """
    for track, difficulty in (("coding", "medium"), ("system_design", None)):
        _, q = box.dispatch("pick_question", {"track": track, "difficulty": difficulty})
        box.dispatch("score_answer", {"question_id": q["id"], "answer": LONG_ANSWER})

    ok, payload = box.dispatch(
        "submit_report",
        {
            "overall_score": 80, "radar": _radar(),
            "highlights": ["a"], "weaknesses": ["b"],
            "improvements": ["c"], "verdict": "建议补 Kafka",
        },
    )
    assert ok is True
    assert payload["round_count"] == 2
    # 两条 100 字以上的答案 → 规则打分各 8 分 → 均分 8.0
    assert payload["question_avg_10"] == 8.0
    assert "scored_by" in payload


def test_report_files_land_in_sandbox(box, sandbox_scenarios):
    """报告确实落盘了，而且落在沙箱里（不覆盖仓库那份真实报告）。"""
    _, q = box.dispatch("pick_question", {"track": "hr", "stage": "self_intro"})
    box.dispatch("score_answer", {"question_id": q["id"], "answer": LONG_ANSWER})
    box.dispatch(
        "submit_report",
        {
            "overall_score": 70, "radar": _radar(70),
            "highlights": [], "weaknesses": [], "improvements": [], "verdict": "x",
        },
    )
    assert (sandbox_scenarios / f"{SCENARIO}.report.md").exists()
    assert (sandbox_scenarios / f"{SCENARIO}.report.json").exists()
    assert box.report_md_path.endswith(".report.md")


def test_submit_report_without_records_has_no_average(box, sandbox_scenarios):
    """一题没评就交报告 → 均分为 None，而不是悄悄编一个 0 出来。"""
    ok, payload = box.dispatch(
        "submit_report",
        {
            "overall_score": 60, "radar": _radar(60),
            "highlights": [], "weaknesses": [], "improvements": [], "verdict": "x",
        },
    )
    assert ok is True
    assert payload["question_avg_10"] is None


def test_partial_report_is_refused_when_nothing_scored(box):
    """连一条记录都没有时，交不出"残缺但真实"的报告 —— 那就诚实地说没有。"""
    assert box.submit_partial_report("限流") is None


def test_partial_report_marks_interruption(box, sandbox_scenarios):
    """★ 中断兜底：已评的分必须保住，且要写清这是不完整的结果。"""
    _, q = box.dispatch("pick_question", {"track": "coding", "difficulty": "easy"})
    box.dispatch("score_answer", {"question_id": q["id"], "answer": LONG_ANSWER})

    out = box.submit_partial_report("限流：账户已达到速率限制")
    assert out is not None
    assert out["graded"] == 1

    saved = json.loads(
        (sandbox_scenarios / f"{SCENARIO}.report.json").read_text(encoding="utf-8")
    )
    assert saved["interrupted"] is True
    assert "中断" in saved["verdict"]
    assert "不代表完整面试表现" in saved["verdict"]


# ===========================================================================
# 收尾与汇总
# ===========================================================================


def test_end_interview_marks_finished(box):
    ok, payload = box.dispatch("end_interview", {"reason": "面试完成"})
    assert ok is True
    assert box.finished is True
    assert box.finish_reason == "面试完成"


def test_summary_separates_llm_and_rule_scoring(box):
    """summary 里 llm / rule 分开计数 —— "有多少题是真 LLM 评的"本身就是质量指标。"""
    _, q = box.dispatch("pick_question", {"track": "coding", "difficulty": "medium"})
    box.dispatch("score_answer", {"question_id": q["id"], "answer": LONG_ANSWER})
    s = box.summary()
    assert s["questions_asked"] == 1
    assert s["answers_scored"] == 1
    assert s["scored_by_llm"] + s["scored_by_rule"] == 1
    assert s["tool_calls"] == 2          # 一次出题 + 一次评分
    assert s["finished"] is False


def test_avg_by_track(box):
    """分量表未评分的题型不应出现空桶。"""
    for track, difficulty in (("coding", "medium"), ("coding", "easy"), ("system_design", None)):
        _, q = box.dispatch("pick_question", {"track": track, "difficulty": difficulty})
        box.dispatch("score_answer", {"question_id": q["id"], "answer": LONG_ANSWER})

    avg = box.avg_by_track()
    assert set(avg) == {"coding", "system_design"}
    assert avg["coding"] == 8.0


def test_records_are_json_serializable(box):
    """逐题记录里混进不可序列化对象 → 整场报告落盘失败。"""
    _, q = box.dispatch("pick_question", {"track": "hr", "stage": "self_intro"})
    box.dispatch("score_answer", {"question_id": q["id"], "answer": LONG_ANSWER})
    json.loads(box.dump_records())


def test_short_answer_scores_lower_than_long_one(box):
    """规则打分（降级路径）的行为锁定：它只看长度。"""
    _, q1 = box.dispatch("pick_question", {"track": "coding", "difficulty": "medium"})
    _, short = box.dispatch("score_answer", {"question_id": q1["id"], "answer": SHORT_ANSWER})
    _, q2 = box.dispatch("pick_question", {"track": "coding", "difficulty": "hard"})
    _, long = box.dispatch("score_answer", {"question_id": q2["id"], "answer": LONG_ANSWER})
    assert short["score"] < long["score"]
