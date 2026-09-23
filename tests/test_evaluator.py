# -*- coding: utf-8 -*-
"""评分器单测：解析、归一化、加权、覆盖率、熔断、缓存、降级。

这个文件的核心主张是那句设计原则 ——
**模型负责判断，代码负责计算**。
所以"解析"和"算术"这两块必须逐条钉死：模型给的输入千奇百怪（代码块包裹、
百分制、键名写错、只给一半维度），而代码这边不许出错、不许静默送分。

全部离线：用一个假 LLM 顶替真实客户端，不联网、不花额度。
"""

from __future__ import annotations

import pytest

from agent.evaluator import (
    DIMENSION_HINTS,
    GENERIC_RUBRICS,
    MAX_SCORE,
    SYSTEM_PROMPT,
    AnswerEvaluator,
    _as_rate,
    _extract_json,
    _normalize_dimensions,
    _rubric_for,
    _weighted_score,
)
from agent.llm import LLMError

# ===========================================================================
# 假 LLM：只实现 .chat()，返回值由测试给定
# ===========================================================================


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class StubLLM:
    """按顺序吐出预设的回复；遇到 Exception 就抛出来（模拟限流 / 网络故障）。"""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.seen: list[list[dict]] = []

    def chat(self, messages, **kwargs):
        self.calls += 1
        self.seen.append(messages)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Reply(item)


CODING_Q = {
    "id": "lc-146-lru-cache",
    "track": "coding",
    "title": "LRU 缓存",
    "description": "实现一个 O(1) 的 LRU 缓存。",
    "solution_outline": "哈希表 + 双向链表。",
    "scoring_rubric": {
        "data_structure_choice": 3,
        "time_complexity": 3,
        "edge_cases": 2,
        "code_clarity": 2,
    },
}

ALL_ONES = (
    '{"dimensions": {"data_structure_choice": 1.0, "time_complexity": 1.0,'
    ' "edge_cases": 1.0, "code_clarity": 1.0}, "comment": "满分", "evidence": ["哈希表加双向链表"]}'
)


def _stub(replies: list, **kw) -> tuple[AnswerEvaluator, StubLLM]:
    llm = StubLLM(replies)
    return AnswerEvaluator(llm=llm, verbose=False, **kw), llm


# ===========================================================================
# ① 解析：从模型的自由发挥里把 JSON 抠出来
# ===========================================================================


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('好的，我的评分是：\n{"a": 1}\n以上。', {"a": 1}),
    ],
)
def test_extract_json_handles_model_chatter(text, expected):
    """「严格输出 JSON」是叮嘱不是保证 —— 剥代码块、掐头去尾都得兜住。"""
    assert _extract_json(text) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "没有 JSON", "[1, 2, 3]", "{坏掉的"])
def test_extract_json_returns_none_on_garbage(text):
    assert _extract_json(text) is None


# ===========================================================================
# ② 归一化：模型给的量纲和键名都可能不对
# ===========================================================================


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.8, 0.8),
        (1, 1.0),
        (0, 0.0),
        (8, 0.8),          # 十分制
        (80, 0.8),         # 百分制
        ("0.8", 0.8),
        ("80", 0.8),
        ("0.8分", 0.8),
        (-1, 0.0),         # 越界向下夹紧
        pytest.param(True, None, id="bool-is-not-a-number"),
        pytest.param("abc", None, id="non-numeric-string"),
        pytest.param(None, None, id="none"),
        pytest.param([1], None, id="list"),
    ],
)
def test_as_rate_normalizes_scales(value, expected):
    """模型可能给 0.8 / 8 / 80 / "0.8" —— 按量级折回 0~1，这是解析层的事。"""
    assert _as_rate(value) == expected


def test_normalize_dimensions_maps_exact_keys():
    raw = {"time_complexity": 0.5, "edge_cases": 1}
    assert _normalize_dimensions(CODING_Q["scoring_rubric"], raw) == {
        "time_complexity": 0.5,
        "edge_cases": 1.0,
    }


def test_normalize_dimensions_fuzzy_matches_renamed_key():
    """模型偶尔自作主张改键名 —— 互为子串就认，但仍要落到 rubric 的键上。"""
    raw = {"data_structure": 1.0}
    assert _normalize_dimensions(CODING_Q["scoring_rubric"], raw) == {
        "data_structure_choice": 1.0
    }


def test_normalize_dimensions_drops_unknown_and_invalid():
    """匹配不上就丢掉：宁可少算一个维度，也不要把分安错地方。"""
    raw = {"totally_made_up": 1.0, "clarity": "看不懂", "time_complexity": 0.6}
    assert _normalize_dimensions(CODING_Q["scoring_rubric"], raw) == {"time_complexity": 0.6}


def test_normalize_dimensions_handles_non_dict():
    assert _normalize_dimensions(CODING_Q["scoring_rubric"], "oops") == {}


# ===========================================================================
# ③ 加权：这一步必须在代码里，不能交给模型
# ===========================================================================


def test_weighted_score_all_full_marks():
    rubric = CODING_Q["scoring_rubric"]
    assert _weighted_score(rubric, {k: 1.0 for k in rubric}) == MAX_SCORE


def test_weighted_score_all_zero():
    rubric = CODING_Q["scoring_rubric"]
    assert _weighted_score(rubric, {k: 0.0 for k in rubric}) == 0.0


def test_weighted_score_missing_dimensions_are_neutral():
    """漏报是解析问题，不该让候选人买单：按 0.5 中性值计入，不是 0 分。"""
    rubric = CODING_Q["scoring_rubric"]          # 权重合计 10
    got = _weighted_score(rubric, {"data_structure_choice": 1.0})
    # 3 分权重拿满 + 7 分权重按中性 0.5 → 3 + 3.5 = 6.5
    assert got == pytest.approx(6.5)


def test_weighted_score_zero_weight_rubric_is_not_a_zero_division():
    assert _weighted_score({}, {}) == 0.0


# ===========================================================================
# ④ 权重表来源：题库题用自带 rubric，自拟题按题型兜底
# ===========================================================================


def test_rubric_for_prefers_question_own_rubric():
    q = {"track": "coding", "scoring_rubric": {"a": 3, "b": 2}}
    assert _rubric_for(q) == {"a": 3.0, "b": 2.0}


def test_rubric_for_skips_zero_weight_entries():
    """权重 0 的维度写进提示词只会浪费 token。"""
    q = {"track": "coding", "scoring_rubric": {"a": 3, "b": 0}}
    assert _rubric_for(q) == {"a": 3.0}


def test_rubric_for_falls_back_by_track():
    assert _rubric_for({"track": "project"}) == {
        k: float(v) for k, v in GENERIC_RUBRICS["project"].items()
    }


def test_rubric_for_unknown_track_uses_hr():
    assert _rubric_for({"track": "poetry"}) == {
        k: float(v) for k, v in GENERIC_RUBRICS["hr"].items()
    }


def test_generic_rubrics_weigh_ten_points():
    """兜底权重必须和题库口径一致（10 分制），否则自拟题的分数没法横向比。"""
    for track, rubric in GENERIC_RUBRICS.items():
        assert sum(rubric.values()) == MAX_SCORE, track


def test_every_generic_dimension_has_a_hint():
    """每个维度都要有中文释义 —— 光给英文键名会削弱判分标准的一致性。"""
    missing = [k for k in GENERIC_RUBRICS.values() for k in k if k not in DIMENSION_HINTS]
    assert not missing, f"这些维度没有释义: {missing}"


def test_every_bank_rubric_dimension_has_a_hint():
    """题库里所有 scoring_rubric 的键也都要能查到释义。

    题库会持续加题，某天有人写了个新维度忘了加释义，这条测试会拦下来。
    """
    from tools.mock_tools import QUESTION_BANK

    def walk(node):
        if isinstance(node, dict):
            if "scoring_rubric" in node:
                yield from node["scoring_rubric"]
            else:
                for v in node.values():
                    yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)

    keys = set(walk(QUESTION_BANK))
    assert keys, "题库里一道带 scoring_rubric 的题都没有？结构可能变了"
    missing = sorted(k for k in keys if k not in DIMENSION_HINTS)
    assert not missing, f"题库用了没有释义的维度: {missing}"


# ===========================================================================
# ⑤ LLM 评分：正常路径
# ===========================================================================


def test_llm_scoring_computes_score_from_dimensions():
    ev, llm = _stub([ALL_ONES])
    result = ev.score(CODING_Q, "哈希表加双向链表，get/put 都是 O(1)。")

    assert result["source"] == "llm"
    assert result["score"] == 10
    assert result["dimensions"]["edge_cases"] == 1.0
    assert result["weights"]["time_complexity"] == 3.0
    assert result["comment"] == "满分"
    assert result["evidence"] == ["哈希表加双向链表"]
    assert llm.calls == 1


def test_llm_scoring_survives_fenced_json():
    ev, _ = _stub([f"```json\n{ALL_ONES}\n```"])
    assert ev.score(CODING_Q, "x")["source"] == "llm"


def test_scoring_prompt_has_no_conversation_history():
    """★ 刻意设计，不是漏实现。

    评分请求只发「系统提示 + 这一道题」，不带整场 messages。
    两个原因：避免光环效应（前面答得好会抬高后面的分）、省 token。
    这条测试把它钉住 —— 以后有人"顺手"把历史接进来，这里会红。
    """
    ev, llm = _stub([ALL_ONES])
    ev.score(CODING_Q, "哈希表加双向链表。")

    messages = llm.seen[0]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "LRU" in messages[1]["content"]
    assert "哈希表加双向链表" in messages[1]["content"]


def test_scoring_uses_temperature_zero():
    """评分是"判定"不是"创作" —— 同一份答案评两次该得到同一个分。"""
    class Recorder(StubLLM):
        def chat(self, messages, **kwargs):
            self.kwargs = kwargs
            return super().chat(messages, **kwargs)

    llm = Recorder([ALL_ONES])
    AnswerEvaluator(llm=llm, verbose=False).score(CODING_Q, "答案")
    assert llm.kwargs.get("temperature") == 0.0


def test_score_is_clamped_to_zero_ten():
    """维度达成度是 0~1，但夹紧逻辑要存在 —— 万一解析层漏了不会溢出。"""
    ev, _ = _stub(
        ['{"dimensions": {"data_structure_choice": 1, "time_complexity": 1,'
         ' "edge_cases": 1, "code_clarity": 1}, "comment": "c", "evidence": []}']
    )
    score = ev.score(CODING_Q, "答案")["score"]
    assert 0 <= score <= MAX_SCORE


def test_evidence_string_is_wrapped_into_list():
    ev, _ = _stub(
        ['{"dimensions": {"data_structure_choice": 1, "time_complexity": 1,'
         ' "edge_cases": 1, "code_clarity": 1}, "comment": "c", "evidence": "原话"}']
    )
    assert ev.score(CODING_Q, "原话")["evidence"] == ["原话"]


def test_hallucinated_evidence_is_not_reported():
    ev, _ = _stub(
        ['{"dimensions": {"data_structure_choice": 1, "time_complexity": 1,'
         ' "edge_cases": 1, "code_clarity": 1}, "comment": "c", "evidence": "并未说过"}']
    )
    assert ev.score(CODING_Q, "实际回答")["evidence"] == []


# ===========================================================================
# ⑥ 覆盖率：只给一半维度就交差，比不给分更危险
# ===========================================================================


def test_partial_coverage_is_rejected():
    """★ 模型只给 data_structure_choice=1.0，其余靠 0.5 中性值补，
    总分照样能到 6.5 分 —— 这个分数看着有效，其实没依据。
    覆盖率低于 60% 必须判为失败，而不是"少算几个维度"。
    """
    ev, _ = _stub(
        ['{"dimensions": {"data_structure_choice": 1.0}, "comment": "只给一个", "evidence": []}']
    )
    result = ev.score(CODING_Q, "答案")
    assert result["source"] == "rule-fallback"
    assert "覆盖" in result["fallback_reason"]


def test_coverage_at_threshold_passes():
    """边界：正好覆盖 60% 权重（3+3=6/10）算通过，缺的维度走中性值 0.5。"""
    ev, _ = _stub(
        ['{"dimensions": {"data_structure_choice": 1.0, "time_complexity": 1.0},'
         ' "comment": "c", "evidence": []}']
    )
    result = ev.score(CODING_Q, "答案")
    assert result["source"] == "llm"
    # 6 分权重拿满 + 4 分权重按 0.5 → 6 + 2 = 8
    assert result["score"] == 8


# ===========================================================================
# ⑦ 降级与熔断：失败了可以降级，但降级之后别装作还能行
# ===========================================================================


def test_unparseable_reply_falls_back():
    ev, _ = _stub(["我拒绝输出 JSON"])
    result = ev.score(CODING_Q, "答案")
    assert result["source"] == "rule-fallback"
    assert result["dimensions"] == {}
    assert isinstance(result["score"], int)


def test_llm_error_falls_back():
    ev, _ = _stub([LLMError("账户已达到速率限制")])
    result = ev.score(CODING_Q, "答案")
    assert result["source"] == "rule-fallback"
    assert "速率限制" in result["fallback_reason"]


def test_fallback_marks_reason_that_it_is_degraded():
    """降级不是丢人的事，假装没降级才是 —— 报告里要能看出来。"""
    ev, _ = _stub([LLMError("boom")])
    result = ev.score(CODING_Q, "答案")
    assert "规则降级评分" in result["comment"]


def test_circuit_breaker_stops_calling_llm_after_repeated_failures():
    """★ 熔断器的价值是省时间。

    LLM 不可用时每次评分都要先把重试跑满（429 是 10+20+40=70 秒）才降级，
    7 道题就是白等 8 分钟。连续失败 2 次后就该切到规则打分把流程跑完。
    """
    ev, llm = _stub([LLMError("1"), LLMError("2"), ALL_ONES])

    q1 = {**CODING_Q, "id": "q1"}
    q2 = {**CODING_Q, "id": "q2"}
    q3 = {**CODING_Q, "id": "q3"}

    assert ev.score(q1, "答案")["source"] == "rule-fallback"
    assert ev.score(q2, "答案")["source"] == "rule-fallback"
    # 第三次即使手里有正常回复，也不该再去调 LLM
    assert ev.score(q3, "答案")["source"] == "rule-fallback"
    assert llm.calls == 2

    result = ev.score(q3, "答案")
    assert llm.calls == 2, "熔断后不该再发起请求"


def test_success_resets_failure_counter():
    """偶发一次失败不该累计 —— 成功了就把计数器清零。"""
    ev, _ = _stub([LLMError("偶发"), ALL_ONES, ALL_ONES])
    assert ev.score({**CODING_Q, "id": "q1"}, "答案")["source"] == "rule-fallback"
    assert ev.score({**CODING_Q, "id": "q2"}, "答案")["source"] == "llm"
    assert ev._consecutive_failures == 0


def test_use_llm_false_never_calls_model():
    ev, llm = _stub([ALL_ONES], use_llm=False)
    assert ev.score(CODING_Q, "答案")["source"] == "rule-fallback"
    assert llm.calls == 0


def test_no_client_never_crashes():
    """离线自检脚本不配 API Key —— score() 必须无条件返回结果，不抛异常。"""
    ev = AnswerEvaluator(llm=None, verbose=False)
    assert ev.score(CODING_Q, "答案")["source"] == "rule-fallback"


# ===========================================================================
# ⑧ 缓存：同一题同一答案不重复花钱
# ===========================================================================


def test_same_question_and_answer_is_cached():
    ev, llm = _stub([ALL_ONES])
    a = ev.score(CODING_Q, "一模一样的答案")
    b = ev.score(CODING_Q, "一模一样的答案")
    assert a is b
    assert llm.calls == 1


def test_cache_is_keyed_on_answer_content():
    """答案变了就得重新评 —— 否则改完答案分数不动，很难排查。"""
    ev, llm = _stub([ALL_ONES, ALL_ONES])
    ev.score(CODING_Q, "第一版答案")
    ev.score(CODING_Q, "第二版答案")
    assert llm.calls == 2


def test_cache_key_is_question_id_plus_answer_hash():
    """缓存键的实现细节也钉一下：题目 id + 答案哈希。"""
    k1 = AnswerEvaluator._cache_key(CODING_Q, "abc")
    k2 = AnswerEvaluator._cache_key(CODING_Q, "abc")
    k3 = AnswerEvaluator._cache_key({**CODING_Q, "id": "other"}, "abc")
    assert k1 == k2
    assert k1 != k3
    assert k1.startswith("lc-146-lru-cache::")


# ===========================================================================
# ⑨ 提示词本身：几条硬约束不能丢
# ===========================================================================


@pytest.mark.parametrize(
    "keyword",
    ["不要因为回答长就给高分", "不要翻译", "不要在 comment 里写分数", "0.0 ~ 1.0"],
)
def test_system_prompt_keeps_hard_constraints(keyword):
    """这几句是评分质量的命根子，改提示词时别顺手删了。"""
    assert keyword in SYSTEM_PROMPT


def test_rule_fallback_scores_long_answer_more_than_short_one():
    """降级路径的行为基线：它只看长度。

    这条测试同时说明"为什么需要 LLM 评分"—— 长度和答得好不好是两件事。
    """
    ev = AnswerEvaluator(llm=None, verbose=False)
    short = ev.score({**CODING_Q, "id": "s"}, "不知道")
    long_ = ev.score({**CODING_Q, "id": "l"}, "废话。" * 60)
    assert short["score"] < long_["score"]
