# -*- coding: utf-8 -*-
"""输出通道单测。全部离线。

主循环的所有输出必须只从 `emit()` 一个口子出去 —— Web 界面要"实时看面试过程"，
靠的就是换掉这一个函数。这里钉住四件事：

1. 默认行为不变（就是打印到终端）
2. 换掉之后终端必须是干净的（不能又打又收）
3. 能恢复
4. **整个文件不允许再出现绕过通道的裸 print()** ← 这条最容易忘

第 4 条为什么值得单独写一条测试：CLI 下一切正常，只有界面里少几行 ——
这类 bug 极难发现，而且发现时往往已经过了很久。
"""

from __future__ import annotations

from pathlib import Path
from threading import Barrier, Thread

import pytest

import orchestrator

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def restore_sink():
    """每个用例跑完都把输出目标恢复成默认 —— 免得污染后面的用例。"""
    yield
    orchestrator.set_sink(None)


def test_emit_prints_to_stdout_by_default(capsys):
    orchestrator.emit("你好")
    assert capsys.readouterr().out == "你好\n"


def test_empty_line_is_supported():
    """`emit()` 不给参数要能打空行 —— 原代码里 `print()` 到处都是。"""
    lines: list[str] = []
    orchestrator.set_sink(lines.append)
    orchestrator.emit()
    assert lines == [""]


def test_banner_and_log_go_through_the_channel(capsys):
    """这两个是最常用的输出助手，它们也必须走同一个口子。"""
    lines: list[str] = []
    orchestrator.set_sink(lines.append)
    orchestrator.banner("测试横幅")
    orchestrator.log(3, "🔧", "调用 read_resume() → OK")
    orchestrator.emit("普通一行")

    joined = "\n".join(lines)
    assert "测试横幅" in joined
    assert "read_resume" in joined
    assert "普通一行" in joined
    # 换了目标之后终端必须是干净的 —— 否则界面里会出现"重复输出"
    assert capsys.readouterr().out == ""


def test_set_sink_none_restores_printing(capsys):
    orchestrator.set_sink(lambda text: None)
    orchestrator.emit("被吞掉")
    assert capsys.readouterr().out == ""

    orchestrator.set_sink(None)
    orchestrator.emit("又出来了")
    assert capsys.readouterr().out == "又出来了\n"


def test_two_parallel_sessions_have_separate_output_sinks():
    ready = Barrier(2)
    captured = {"a": [], "b": []}

    def run(label):
        orchestrator.set_sink(captured[label].append)
        ready.wait()
        orchestrator.emit(label)
        orchestrator.set_sink(None)

    threads = [Thread(target=run, args=(label,)) for label in captured]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert captured == {"a": ["a"], "b": ["b"]}


def test_escalation_menu_also_goes_through_the_channel():
    """★ 故障菜单也是输出的一部分。

    界面里没有终端可敲键盘（主循环会用 interactive=False 绕开这条路），
    但菜单文本仍然必须走同一个通道 —— 否则以后想在页面上显示
    "当时系统建议怎么办"就没地方拿。
    """
    def no_input(prompt: str) -> str:
        raise EOFError

    lines: list[str] = []
    orchestrator.set_sink(lines.append)
    choice = orchestrator.ask_what_to_do("rate_limit", "429 太频繁", "glm-4.5-flash", [], ask=no_input)

    joined = "\n".join(lines)
    assert "限流" in joined
    assert "怎么办" in joined
    assert choice == "give_up"      # 读不到输入 → 按放弃处理


def test_no_print_bypasses_the_channel():
    """★ 结构约束：主循环里不允许再有绕开 emit 的 print()。

    只要有人顺手写一个 print()，那一段在界面里就会凭空消失。
    唯一允许出现 print 的地方是 emit() 的默认终端输出。
    """
    source = (ROOT / "orchestrator.py").read_text(encoding="utf-8")
    offenders = [
        f"第 {number} 行: {line.strip()}"
        for number, line in enumerate(source.splitlines(), start=1)
        if "print(" in line and line.strip() != "print(text)"
    ]
    assert offenders == [], (
        "发现绕过输出通道的 print()，请改成 emit()：\n  " + "\n  ".join(offenders)
    )
