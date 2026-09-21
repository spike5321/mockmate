# -*- coding: utf-8 -*-
"""pytest 公共装置。

两件事：
  ① 把仓库根目录塞进 sys.path —— 否则 `import agent.tools` 会失败。
     （pytest 默认只把测试文件所在目录加进去，而 tests/ 里没有 __init__.py）
  ② 提供 sandbox_scenarios 装置：把 scenarios/ 复制到临时目录再指过去，
     这样调用 submit_report 的测试不会覆盖仓库里那份真实报告。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def sandbox_scenarios(tmp_path, monkeypatch) -> Path:
    """把 scenarios/ 里的输入文件复制到临时目录，并把 mock_tools 指过去。

    只复制**输入**（scenario / answers），不复制 *.report.* ——
    报告是每次运行重新生成的产物，测试不需要它，也不该拿它当输入。

    为什么要这么麻烦？因为 `submit_report` 会真实落盘
    `scenarios/{id}.report.md`。在仓库里跑一次测试就把 run14 的真实报告
    覆盖掉了 —— 那是 README 里实测数据的原件。
    """
    from tools import mock_tools

    for path in (ROOT / "scenarios").glob("*.json"):
        if ".report." in path.name:
            continue
        shutil.copy(path, tmp_path / path.name)

    monkeypatch.setattr(mock_tools, "SCENARIOS_DIR", tmp_path)
    return tmp_path
