# -*- coding: utf-8 -*-
"""断点续跑单测。全部离线。

重点有两个：
  ① 存下去的东西能**原样**恢复
  ② 尤其是 messages 里的 `tool_calls` / `tool_call_id` 那一对 ——
     丢了或者重编一个，恢复后的下一轮请求会被接口直接拒绝，
     而那时用户看到的是"续跑失败"，根本想不到是 id 对不上。
"""

from __future__ import annotations

import json

import pytest

from agent import checkpoint
from agent.candidate import CandidateSim
from agent.tools import ToolBox


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path, monkeypatch):
    """断点文件写到临时目录 —— 测试不许碰真实的 runs/。"""
    monkeypatch.setattr(checkpoint, "RUNS_DIR", tmp_path)
    return tmp_path


# ===========================================================================
# 存取
# ===========================================================================


def test_save_and_load_round_trip():
    state = {
        "scenario_id": "backend_intern",
        "turn": 7,
        "messages": [{"role": "user", "content": "你好"}],
    }
    path = checkpoint.save("r1", state)
    assert path.exists()

    back = checkpoint.load("r1")
    assert back["scenario_id"] == "backend_intern"
    assert back["turn"] == 7
    assert back["version"] == checkpoint.VERSION
    assert back["run_id"] == "r1"
    assert back["messages"] == state["messages"]


def test_save_leaves_no_temp_file(isolated_runs):
    """原子写：临时文件必须已经被 rename 掉，不能留在目录里。"""
    checkpoint.save("r1", {"turn": 1})
    leftovers = [p.name for p in isolated_runs.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_overwrites_previous():
    checkpoint.save("r1", {"turn": 1})
    checkpoint.save("r1", {"turn": 5})
    assert checkpoint.load("r1")["turn"] == 5


def test_load_missing_file_is_explicit():
    with pytest.raises(FileNotFoundError):
        checkpoint.load("nope")


def test_version_mismatch_is_rejected(isolated_runs):
    """★ 结构变了就宁可明确报错，不要猜着解析。

    断点文件里装的是对话历史，猜错了恢复出来的是一份"看着能跑、其实已经坏了"
    的面试 —— 那种失败比直接报错难查得多。
    """
    checkpoint.save("r1", {"turn": 1})
    path = checkpoint.path_for("r1")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="版本"):
        checkpoint.load("r1")


# ===========================================================================
# 「最近一个没跑完的」
# ===========================================================================


def test_latest_unfinished_ignores_completed():
    checkpoint.save("old", {"turn": 30, "updated_at": "2026-01-01 00:00:00"})
    checkpoint.mark_completed("old", {"turn": 30})
    checkpoint.save("new", {"turn": 5, "updated_at": "2026-01-02 00:00:00"})

    assert checkpoint.latest_unfinished() == "new"


def test_latest_unfinished_returns_none_when_all_done():
    checkpoint.mark_completed("only", {"turn": 30})
    assert checkpoint.latest_unfinished() is None


def test_latest_unfinished_skips_broken_files(isolated_runs):
    """★ 一个坏掉的断点文件不能把别的场次挡住 ——
    最可能坏掉的那个，恰恰就是你上次写到一半的那一个。
    """
    (isolated_runs / "broken.checkpoint.json").write_text("{ not json", encoding="utf-8")
    checkpoint.save("good", {"turn": 2, "updated_at": "2026-01-01 00:00:00"})

    assert checkpoint.latest_unfinished() == "good"


def test_describe_mentions_the_interrupt_reason():
    checkpoint.save(
        "r1",
        {
            "turn": 9,
            "scenario_id": "backend_intern",
            "interrupted": {"turn": 9, "reason": "限流"},
        },
    )
    text = checkpoint.describe("r1")
    assert "未完成" in text
    assert "限流" in text


# ===========================================================================
# 各对象的 dump / load
# ===========================================================================


def test_toolbox_state_round_trip():
    box = ToolBox("backend_intern")
    box.questions["q1"] = {"id": "q1", "track": "coding"}
    box.records.append({"question_id": "q1", "score": 7})
    box.custom_count = 2
    box.pending_question = {"id": "q1"}
    box.notes.append("第 3 轮中断过，之后从断点续跑")
    box.call_count = 12

    dumped = box.dump_state()
    json.dumps(dumped, ensure_ascii=False)      # 必须能 JSON 化，否则断点写不出去

    revived = ToolBox("backend_intern")
    revived.load_state(dumped)
    assert revived.questions == box.questions
    assert revived.records == box.records
    assert revived.custom_count == 2
    assert revived.pending_question == {"id": "q1"}
    assert revived.notes == box.notes
    assert revived.call_count == 12


def test_toolbox_load_tolerates_missing_fields():
    """老断点文件少几个字段，不该让整场面试恢复不了。"""
    box = ToolBox("backend_intern")
    box.load_state({"turn": 1})          # 一个认识的字段都没有
    assert box.records == []
    assert box.finished is False
    assert box.notes == []


def test_toolbox_state_does_not_contain_the_evaluator():
    """★ evaluator 是个攥着网络连接的活对象，不能进断点文件。

    而且它的熔断器和缓存属于"这一轮运行的保护"，恢复时重置反而更合理。
    """
    box = ToolBox("backend_intern", evaluator=object())
    dumped = box.dump_state()
    assert "evaluator" not in dumped
    json.dumps(dumped, ensure_ascii=False)      # 能 JSON 化就说明没混进对象


def test_candidate_state_round_trip():
    answers = {
        "q1": "答案一",
        "_followups": {"coding": ["追问一", "追问二"]},
        "_repeat": ["我答不上来"],
    }
    sim = CandidateSim(answers)
    sim.used_keys.add("q1")
    sim.fu_count["coding"] = 2
    sim.generic_idx = 3

    dumped = sim.dump_state()
    json.dumps(dumped, ensure_ascii=False)

    revived = CandidateSim(answers)
    revived.load_state(dumped)
    assert revived.used_keys == {"q1"}
    assert revived.fu_count == {"coding": 2}
    assert revived.generic_idx == 3


# ===========================================================================
# 恢复：最要紧的一条
# ===========================================================================


def test_restore_keeps_tool_call_ids_intact():
    """★★ messages 必须原样搬回去。

    assistant 消息里的 `tool_calls[].id` 和后面 tool 消息的 `tool_call_id`
    是一对。丢了或重编任何一个，下一轮请求会因为"tool 消息对不上"被接口拒绝 ——
    而用户看到的只是"续跑失败"，根本联想不到 id 上。
    """
    from orchestrator import _restore_from_checkpoint

    messages = [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": "pick_question", "arguments": '{"track":"coding"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_abc123", "content": '{"ok":true}'},
    ]
    state = {
        "messages": messages,
        "trace": [{"turn": 1, "tool_calls": ["pick_question"]}],
        "toolbox": {"call_count": 1},
        "candidate": {"used_keys": ["q1"]},
    }

    target: list = [{"role": "user", "content": "占位"}]
    trace: list = []
    box = ToolBox("backend_intern")
    sim = CandidateSim({})

    _restore_from_checkpoint(state, box, sim, target, trace)

    assert target == messages                                  # 一字不差
    assert target[1]["tool_calls"][0]["id"] == "call_abc123"
    assert target[2]["tool_call_id"] == "call_abc123"
    assert trace == state["trace"]
    assert box.call_count == 1
    assert sim.used_keys == {"q1"}


def test_restore_with_empty_messages_keeps_current_history():
    """断点里没有 messages（老文件）时，不要把手上的历史清空。"""
    from orchestrator import _restore_from_checkpoint

    target = [{"role": "user", "content": "现有的历史"}]
    _restore_from_checkpoint({}, ToolBox("s"), CandidateSim({}), target, [])
    assert target == [{"role": "user", "content": "现有的历史"}]


# ===========================================================================
# 备注必须出现在报告里
# ===========================================================================


def test_report_renders_notes():
    """★ 「第 3 轮中断过、之后续跑」这件事必须写进报告。

    一场断过又续的面试，如果报告里不标出来，读的人会以为它是一口气跑完的 ——
    那这份报告的可信度就说不清了。
    """
    from tools.mock_tools import _render_markdown_report

    md = _render_markdown_report(
        {"candidate": "张三", "notes": ["第 3 轮中断过（限流），之后从断点续跑"]}
    )
    assert "本场备注" in md
    assert "第 3 轮中断过" in md


def test_report_without_notes_has_no_notes_section():
    """没有备注就不要冒出一个空小节 —— 空标题比没有更难看。"""
    from tools.mock_tools import _render_markdown_report

    md = _render_markdown_report({"candidate": "张三"})
    assert "本场备注" not in md
