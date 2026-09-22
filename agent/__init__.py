# -*- coding: utf-8 -*-
"""MockMate 自研 Agent 层。

模块划分（对应一次完整决策的四个部分）：

    llm.py        怎么跟大模型说话（HTTP + function calling 协议）
    tools.py      给模型看的工具说明书 + 真正执行工具的 ToolBox
    prompts.py    系统提示词 —— 决定 Agent 的行为方式
    candidate.py  模拟候选人（陪练对象，让流程能自动跑完）
    loop.py       （即将）把主循环从 orchestrator.py 抽出来复用

主入口在上一层的 orchestrator.py。
"""

from agent.candidate import CandidateSim
from agent.llm import ERROR_KINDS, LLMClient, LLMError, LLMReply, classify_error
from agent.tools import TOOL_SCHEMAS, ToolBox

__all__ = [
    "CandidateSim",
    "ERROR_KINDS",
    "LLMClient",
    "LLMError",
    "LLMReply",
    "TOOL_SCHEMAS",
    "ToolBox",
    "classify_error",
]
