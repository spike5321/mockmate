# -*- coding: utf-8 -*-
"""检索层：把问题转成向量，去向量库里找最像的片段。

这是 RAG 里的 "R"（Retrieval）。对应的 "G"（Generation）不在这里 ——
在 MockMate 里，生成的角色由面试官模型自己扮演：检索回来的片段会作为
工具结果交回给它，由它决定怎么用、要不要再检索一次。

**这个分工就是 Agentic RAG 和固定管线的分界线。**

向量化不在这里实现 —— 统一走 kb.embed.embed_texts()。
改造前这个文件里有一份自己的 LLMClient 建法，和 kb/build.py 里那份重复，
换 embedding 时只改一处就会让"库"和"查询词"落到不同的向量空间。
"""

from __future__ import annotations

from kb.embed import embed_texts, provider_info
from kb.store import get_collection, get_embed_sig


def _assert_same_space() -> None:
    """确认「库里的向量」和「现在给查询词算的向量」是同一套。

    不做这个检查也不会报错 —— 相似度会静静变成一堆噪声，
    看起来"检索还能用"，只是结果莫名其妙。这类错最难查，所以宁可明确失败。
    """
    built = get_embed_sig()
    now = provider_info()["signature"]
    if built and built != now:
        raise RuntimeError(
            f"向量库是用 {built} 建的，当前配置是 {now}。"
            f"两套向量空间不可比（维度相同也未必通用），请重建："
            f"python -m kb.build --rebuild"
        )


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
        # 库空时直接返回，连模型都不用加载 ——
        # 本地模型第一次加载要十几秒，空库时白等就太蠢了。
        return []

    _assert_same_space()

    vector = embed_texts([query])[0]
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
    try:
        current = provider_info()["signature"]
    except (ValueError, RuntimeError):
        current = "?"
    return {
        "chunks": col.count(),
        "sources": sources,
        "built_with": get_embed_sig(),   # 库是谁建的（老库可能是 None）
        "current": current,              # 现在的配置
    }
