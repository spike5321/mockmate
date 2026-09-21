# -*- coding: utf-8 -*-
"""检索层：把问题转成向量，去向量库里找最像的片段。

这是 RAG 里的 "R"（Retrieval）。对应的 "G"（Generation）不在这里 ——
在 MockMate 里，生成的角色由面试官模型自己扮演：检索回来的片段会作为
工具结果交回给它，由它决定怎么用、要不要再检索一次。

**这个分工就是 Agentic RAG 和固定管线的分界线。**
"""

from __future__ import annotations

import os

from kb.store import get_collection

_client = None


def _get_client():
    """惰性建客户端：只有真要检索时才去读 Key、建对象。

    这样即便没配 Key，`import kb` 也不会崩 —— 只有真正调检索时才报错。
    """
    global _client
    if _client is None:
        from agent.llm import LLMClient

        api_key = os.environ.get("ZHIPU_API_KEY", "")
        if not api_key:
            raise RuntimeError("缺少 ZHIPU_API_KEY，无法向量化检索词")
        _client = LLMClient(api_key=api_key, verbose=False)
    return _client


def retrieve(query: str, k: int = 3) -> list[dict]:
    """检索与 query 最相关的 k 个片段。

    返回 [{"text", "source", "chunk", "score"}]，
    score 是 0~1 的余弦相似度（越大越像）。

    向量库是空的就返回 []，由调用方决定怎么办 —— 不在这里抛异常，
    因为"库没建"是很正常的状态，不是错误。
    """
    col = get_collection()
    count = col.count()
    if count == 0:
        return []

    vector = _get_client().embed([query])[0]
    res = col.query(query_embeddings=[vector], n_results=min(k, count))

    hits: list[dict] = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        hits.append(
            {
                "text": doc,
                "source": meta.get("source", "?"),
                "chunk": meta.get("chunk"),
                # cosine 空间下 distance = 1 - 余弦相似度
                "score": round(1 - dist, 4),
            }
        )
    return hits


def kb_status() -> dict:
    """看一眼向量库现状，给日志和界面用。"""
    col = get_collection()
    sources: dict[str, int] = {}
    if col.count():
        got = col.get(include=["metadatas"])
        for meta in got.get("metadatas") or []:
            src = meta.get("source", "?")
            sources[src] = sources.get(src, 0) + 1
    return {"chunks": col.count(), "sources": sources}
