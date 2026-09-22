# -*- coding: utf-8 -*-
"""主循环的行为测试。用假 LLM 跑整场，不联网。

为什么值得单独一个文件：主循环有相当一部分行为是**过程性**的 ——
预算提醒、防死循环保险丝、运行质量警告…… 它们不在任何单个函数的返回值里，
只有真的把一场跑一遍才看得见。
"""

from __future__ import annotations

import pytest

from agent import checkpoint
from agent.llm import LLMClient, LLMReply


def _talking() -> LLMReply:
    return LLMReply(content="（只是说话，没有调用任何工具）", tool_calls=[])


def _calling() -> LLMReply:
    return LLMReply(
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_resume", "arguments": "{}"},
            }
        ],
    )


def _always_talking(self, messages, tools=None, temperature=0.3):
    """只会说话、从不调工具的模型（模拟不支持 function calling 的那种）。"""
    return _talking()


def _uses_tools(self, messages, tools=None, temperature=0.3):
    """规规矩矩调工具的模型。"""
    return _calling()


@pytest.fixture
def offline_runs(tmp_path, monkeypatch):
    """断点和轨迹都写到临时目录 —— 跑测试不该往仓库里堆文件。"""
    monkeypatch.setattr(checkpoint, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("MOCKMATE_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-test")   # 只用来建客户端，不会真发请求
    return tmp_path


def _run(monkeypatch, answers_path, reply_fn, max_turns: int = 6) -> dict:
    import orchestrator

    monkeypatch.setattr(LLMClient, "chat", reply_fn)
    return orchestrator.run_interview(
        scenario_id="backend_intern",
        answers_path=answers_path,
        max_turns=max_turns,
        model="glm-4.5-flash",
        verbose=True,
        use_llm_score=False,
        interactive=False,
    )


# ===========================================================================
# 「这个模型到底会不会用工具」
# ===========================================================================


def test_warns_when_model_never_calls_tools(
    monkeypatch, sandbox_scenarios, offline_runs, capsys
):
    """★ 不支持 function calling 的模型**不会报错**，它只会一直说话。

    所以这条提醒必须在**过程中**就出现 —— 等跑完才说，用户已经白等一整场、
    还烧掉了额度。而且那场"看起来是跑完了"（有轮数、有对话记录），实际什么都没产出。
    """
    summary = _run(
        monkeypatch,
        sandbox_scenarios / "backend_intern.answers.json",
        _always_talking,
    )

    out = capsys.readouterr().out
    assert "不支持 function calling" in out
    assert summary["tool_calls"] == 0


def test_no_warning_when_model_uses_tools(
    monkeypatch, sandbox_scenarios, offline_runs, capsys
):
    """会调工具的模型不该看到这条提醒 —— 误报比不报更烦人。"""
    _run(monkeypatch, sandbox_scenarios / "backend_intern.answers.json", _uses_tools)

    assert "不支持 function calling" not in capsys.readouterr().out


def test_warning_is_printed_only_once(
    monkeypatch, sandbox_scenarios, offline_runs, capsys
):
    """提醒一次就够 —— 每轮都喊会把真正重要的输出淹掉。"""
    _run(
        monkeypatch,
        sandbox_scenarios / "backend_intern.answers.json",
        _always_talking,
        max_turns=8,
    )

    assert capsys.readouterr().out.count("不支持 function calling") == 1


def test_silence_counter_resets_after_a_tool_call(
    monkeypatch, sandbox_scenarios, offline_runs, capsys
):
    """★ 连续计数必须能被一次工具调用打断。

    否则一场"说说、调调"的正常面试也会攒够阈值被误报。
    这里让模型交替：说话 / 调工具 / 说话 / 调工具 / 说话 / 说话 ——
    最长连续静默只有末尾 2 轮，够不着阈值，所以**不该**出现提醒。
    （如果不归零，早就攒到 3 次了。）
    """
    seq = {"n": 0}

    def alternating(self, messages, tools=None, temperature=0.3):
        seq["n"] += 1
        if seq["n"] in (2, 4):          # 第 2、4 轮调工具
            return _calling()
        return _talking()

    _run(
        monkeypatch,
        sandbox_scenarios / "backend_intern.answers.json",
        alternating,
        max_turns=6,
    )

    assert "不支持 function calling" not in capsys.readouterr().out
