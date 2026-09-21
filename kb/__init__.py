# -*- coding: utf-8 -*-
"""MockMate 知识库（RAG 检索层）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
这个包在系统里的位置：

    面试官模型 ——(search_jd_kb 工具)——> kb.retrieve() ——> Chroma 向量库

它回答的问题是：**面试官出题前，怎么从一堆面试情报里找到相关的那几段？**

注意它的角色和"标准 RAG" 不一样。标准 RAG 是
「检索 → 拼进 prompt → 生成回答」一条写死的管线。
这里只做检索，**要不要检索、检索几次、拿到片段之后怎么用，
全由面试官模型自己决定**（它是通过 function calling 主动调这个工具的）。
这就是所谓 Agentic RAG —— 检索从"管线里的一步"变成"Agent 手里的一个工具"。

目录约定：
    knowledge/    语料文件（.md/.txt/.pdf，进 git 版本管理）
    .kb/          向量库落盘目录（已 gitignore，随时可用 kb.build 重建）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from kb.embed import embed_texts, provider_info
from kb.search import kb_status, retrieve

__all__ = ["retrieve", "kb_status", "embed_texts", "provider_info"]
