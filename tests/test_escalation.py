# -*- coding: utf-8 -*-
"""失败升级阶梯单测。全部离线 —— 交互用注入的假 ask，不真的去读键盘。"""

from __future__ import annotations

from orchestrator import _alternative_models, ask_what_to_do, should_auto_switch


class _FakeAsk:
    """按脚本回答的假输入。答完就给 EOFError，模拟"读不到输入"。"""

    def __init__(self, *answers: str):
        self._answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.asked.append(prompt)
        if not self._answers:
            raise EOFError
        return self._answers.pop(0)


# ===========================================================================
# 该不该自动切（第二级）
# ===========================================================================


def test_auto_switch_when_fallback_configured():
    assert should_auto_switch("rate_limit", "glm-4.5-air", "glm-4.5-flash") is True


def test_no_auto_switch_without_fallback():
    assert should_auto_switch("rate_limit", None, "glm-4.5-flash") is False
    assert should_auto_switch("rate_limit", "", "glm-4.5-flash") is False


def test_no_auto_switch_when_fallback_is_the_same_model():
    """备选 == 当前，等于没配 —— 别在那儿假装切换、白跑一轮。"""
    assert should_auto_switch("rate_limit", "glm-4.5-flash", "glm-4.5-flash") is False


def test_auth_failure_never_auto_switches():
    """★ Key 错了换模型没用 —— 同一个 Key 换谁来回答都一样。

    这种"换了也白换"的动作绝不能自动做：用户会以为系统在自救，
    其实是拿着坏 Key 又试了一遍。
    """
    assert should_auto_switch("auth", "glm-4.5-air", "glm-4.5-flash") is False


def test_other_kinds_do_auto_switch():
    for kind in ("rate_limit", "model_missing", "server", "network", "other"):
        assert should_auto_switch(kind, "fallback", "current") is True


# ===========================================================================
# 问人（第三级）的各个出口
# ===========================================================================


def test_retry_option():
    assert ask_what_to_do("rate_limit", "boom", "m1", ["m2"], _FakeAsk("1")) == "retry"


def test_switch_to_first_alternative():
    assert ask_what_to_do("rate_limit", "boom", "m1", ["m2"], _FakeAsk("2")) == "model:m2"


def test_switch_to_second_alternative():
    got = ask_what_to_do("rate_limit", "boom", "m1", ["m2", "m3"], _FakeAsk("3"))
    assert got == "model:m3"


def test_fix_key_option():
    """菜单编号会随备选模型数量浮动，这里确认它真的落在 fix_key 上。"""
    assert ask_what_to_do("auth", "bad key", "m1", ["m2"], _FakeAsk("3")) == "fix_key"
    assert ask_what_to_do("auth", "bad key", "m1", [], _FakeAsk("2")) == "fix_key"


def test_give_up_option():
    assert ask_what_to_do("auth", "bad key", "m1", ["m2"], _FakeAsk("4")) == "give_up"
    assert ask_what_to_do("auth", "bad key", "m1", [], _FakeAsk("3")) == "give_up"


def test_empty_input_means_give_up():
    """直接回车 = 放弃 —— 不想思考的时候，给他一条最省事的路。"""
    assert ask_what_to_do("rate_limit", "boom", "m1", ["m2"], _FakeAsk("")) == "give_up"


def test_unknown_input_means_give_up():
    assert ask_what_to_do("rate_limit", "boom", "m1", [], _FakeAsk("xyz")) == "give_up"


def test_eof_means_give_up():
    """★ 读不到输入时必须体面退出。

    管道里跑、CI 里跑、后台跑都会走到这条路径 ——
    一个给人评审的项目，绝不能因为"在等人敲键盘"就永久挂在那儿。
    """
    ask = _FakeAsk()          # 一次回答都不给
    assert ask_what_to_do("rate_limit", "boom", "m1", ["m2"], ask) == "give_up"
    assert ask.asked          # 确认它确实问了，不是没问就返回


def test_keyboard_interrupt_means_give_up():
    def interrupted(_prompt: str = "") -> str:
        raise KeyboardInterrupt

    assert ask_what_to_do("rate_limit", "boom", "m1", [], interrupted) == "give_up"


def test_kind_is_shown_as_plain_chinese(capsys):
    """菜单里显示的得是人话 —— 用户看不懂 rate_limit 是什么。"""
    ask_what_to_do("rate_limit", "boom", "m1", [], _FakeAsk("1"))
    out = capsys.readouterr().out
    assert "限流" in out
    assert "rate_limit" not in out


def test_menu_lists_the_alternative_models(capsys):
    ask_what_to_do("rate_limit", "boom", "glm-4.5-flash", ["glm-4.5-air"], _FakeAsk("1"))
    out = capsys.readouterr().out
    assert "glm-4.5-air" in out


# ===========================================================================
# 备选模型从哪儿来
# ===========================================================================


def test_alternatives_are_same_provider_only():
    """★ 只列同一家的模型。

    模型名跨供应商不通用 —— 把别家的名字列进菜单是害人：
    用户选了它，下一轮只会再收到一个"模型不存在"。
    """
    from agent.providers import PROVIDERS, guess_provider

    alternatives = _alternative_models("glm-4.5-flash")
    assert alternatives, "智谱应该还有别的模型能换"

    provider = PROVIDERS[guess_provider("glm-4.5-flash")]
    for name in alternatives:
        assert name in provider.models
    assert "glm-4.5-flash" not in alternatives      # 不含当前这个


def test_alternatives_are_empty_for_an_unknown_model():
    assert _alternative_models("some-model-nobody-registered") == []
