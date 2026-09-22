# -*- coding: utf-8 -*-
"""Web 界面（app.py）的冒烟测试。

★ 为什么必须单独写这一份：**pytest 平时根本不会 import app.py**。

    Streamlit 的脚本只有在 `streamlit run` 里才会被执行。普通 import 既不渲染、
    也发现不了引用错误和缩进错误 —— 阶段 4 就吃过这个亏：一个 `with` 块的缩进
    被编辑器吃掉，单测全绿，页面直接白屏。

    所以这里用 Streamlit 自带的 `AppTest`：它**真的把脚本跑一遍**，
    任何异常都会落到 `at.exception` 上。

★ 测试范围只到"页面能加载、控件长得对"。
    点"开始面试"会真的调模型、还会往 scenarios/ 写报告，那是 e2e 的事，不是单测。
    （报告被覆盖这个坑有专门的记录：run14 那份 README 实测数据就这样被污染过一次。）
"""

from __future__ import annotations

from pathlib import Path

import pytest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="需要 Streamlit ≥ 1.28 才有 AppTest"
).AppTest

#: Streamlit 的 TextInput 类型枚举（已实测核对过，不是猜的）：
#:   {0: DEFAULT, 1: PASSWORD, 2: EMAIL, 3: URL, 4: PHONE, 5: SEARCH}
PASSWORD = 1


@pytest.fixture(scope="module")
def app():
    """整个模块只跑一次页面（AppTest 每次 run 都要重新执行脚本，挺慢的）。"""
    instance = AppTest.from_file(str(APP_PATH), default_timeout=90)
    instance.run()
    return instance


def test_app_loads_without_exception(app):
    """★ 最重要的一条：页面加载不能有异常。

    没有这一条的话，import 错误、拼错的控件名、缩进被吃掉…… 全都只在
    浏览器里才暴露出来。
    """
    assert not app.exception, [str(e.value) for e in app.exception]


def test_page_has_the_two_tabs(app):
    """主区是「开始一场新的 / 接着跑没跑完的」两块。"""
    assert [tab.label for tab in app.tabs] == ["开始一场新的", "接着跑没跑完的"]


def test_sidebar_has_scenario_and_model_controls(app):
    labels = [widget.label for widget in app.sidebar.text_input]
    assert "面试官模型" in labels
    assert "评分模型" in labels
    assert [box.label for box in app.sidebar.selectbox] == ["面试场景", "供应商"]
    assert any(button.label == "开始面试" for button in app.button)


def test_api_key_field_is_masked(app):
    """★ 临时 Key 的输入框必须是密码框。

    这是 Key 纪律在界面这一层的落点：演示的时候会共享屏幕，
    普通输入框旁边有人看一眼就记住了。
    """
    field = next(w for w in app.sidebar.text_input if w.label == "API Key")
    assert field.proto.type == PASSWORD
    # 顺带确认它不是"所有框都长这样"——别的框确实还是普通文本
    assert next(w for w in app.sidebar.text_input if w.label == "面试官模型").proto.type != PASSWORD


def test_model_defaults_come_from_env(monkeypatch):
    """侧栏的默认模型要跟着 .env 走，而不是写死在界面里。"""
    monkeypatch.setenv("CHAT_MODEL", "deepseek-chat")
    monkeypatch.setenv("SCORE_MODEL", "deepseek-chat")

    instance = AppTest.from_file(str(APP_PATH), default_timeout=90)
    instance.run()

    assert not instance.exception
    assert next(w for w in instance.sidebar.text_input if w.label == "面试官模型").value == "deepseek-chat"
    assert next(w for w in instance.sidebar.text_input if w.label == "评分模型").value == "deepseek-chat"
