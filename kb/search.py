# -*- coding: utf-8 -*-
"""检索层：把问题变成召回，去语料里找最相关的几个片段。

这一层现在有**两路召回**：

    向量路（kb/embed.py 算向量 + Chroma）—— 比语义，问法和原文不一样也能命中
    关键词路（kb/bm25.py）              —— 比字面，专有名词（LRU / 三次握手）更可靠

默认两路都跑再融合。也可以只用其中一路：

    retrieve(q, mode="vector")   # 只看语义
    retrieve(q, mode="bm25")     # 只看关键词
    retrieve(q, mode="hybrid")   # 两路 + 融合（默认）

融合算法默认 normalized_sum（归一化加权求和），另有 rrf 可选：

    retrieve(q, mode="hybrid", fusion="rrf")

为什么默认不是 RRF —— 见 kb/fusion.py 开头，那里有 20 个查询的实测数据，
以及"等权 RRF 在这个列表长度下会把两路的第一名算成同分"这条结构性原因。

这是 RAG 里的 "R"（Retrieval）。对应的 "G"（Generation）不在这里 ——
在 MockMate 里，生成的角色由面试官模型自己扮演：检索回来的片段会作为
工具结果交回给它，由它决定怎么用、要不要再检索一次。

**这个分工就是 Agentic RAG 和固定管线的分界线。**

向量化不在这里实现 —— 统一走 kb.embed.embed_texts()。
改造前这个文件里有一份自己的 LLMClient 建法，和 kb/build.py 里那份重复，
换 embedding 时只改一处就会让"库"和"查询词"落到不同的向量空间。
"""

from __future__ import annotations

from kb.bm25 import BM25
from kb.embed import embed_texts, provider_info
from kb.fusion import DEFAULT_FUSION, FUSIONS, fuse
from kb.store import get_collection, get_embed_sig

#: 每路先各取多少条，再拿去融合。
#: 比 k 大一些是因为融合会筛掉一部分 —— 只取 k 条的话，融合后可能连 k 条都凑不齐。
FETCH_K = 8

DEFAULT_MODE = "hybrid"
MODES = ("hybrid", "vector", "bm25")

_bm25_cache: tuple | None = None      # (缓存键, BM25 实例)


def _get_bm25(ids: list[str], docs: list[str]) -> BM25:
    """BM25 索引：惰性构建 + 缓存。

    缓存键是「片段数 + 全部 id 的哈希」。id 里本来就带内容指纹
    （见 kb/store.py 的 _chunk_id），内容一变 id 就变，缓存自然失效 ——
    不用再额外存一份内容摘要去比对。
    """
    global _bm25_cache
    key = (len(ids), hash(tuple(ids)))
    if _bm25_cache is None or _bm25_cache[0] != key:
        _bm25_cache = (key, BM25(docs))
    return _bm25_cache[1]


def reset_cache() -> None:
    """清掉 BM25 索引缓存。重建了向量库、或者测试里换了语料，调一下。"""
    global _bm25_cache
    _bm25_cache = None


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


def retrieve(
    query: str,
    k: int = 3,
    mode: str = DEFAULT_MODE,
    fusion: str = DEFAULT_FUSION,
) -> list[dict]:
    """检索与 query 最相关的 k 个片段。

    返回 [{"text", "source", "chunk", "score", "via"}]：

      score —— 0~1 的余弦相似度（越大越像）。**不管走哪条路，这个值都是真的**：
               向量路是拿全部片段算的距离，所以关键词召回的片段也能填上分数，
               不会出现"这条没有分"这种让人困惑的结果。
      via   —— 这条是怎么被找出来的：vector / keyword / both
    """
    if mode not in MODES:
        raise ValueError(f"mode 只能是 {MODES} 之一，收到 {mode!r}")
    if fusion not in FUSIONS:
        raise ValueError(f"fusion 只能是 {FUSIONS} 之一，收到 {fusion!r}")

    col = get_collection()
    count = col.count()
    if count == 0:
        # 库空时直接返回，连模型都不用加载 ——
        # 本地向量模型第一次加载要十几秒，空库时白等就太蠢了。
        return []

    _assert_same_space()

    got = col.get(include=["documents", "metadatas"])
    all_ids: list[str] = list(got["ids"])
    all_docs: list[str] = list(got["documents"])
    all_meta: list[dict] = list(got["metadatas"])

    # ---- 向量路 ----
    # ★ n_results 取**全部**而不是 FETCH_K：这样每个片段都有真实相似度可以回填。
    #   语料只有几十条，多算这点距离可以忽略。
    distances: dict[str, float] = {}
    vector_scored: list[tuple[str, float]] = []
    if mode in ("hybrid", "vector"):
        vector = embed_texts([query])[0]
        res = col.query(query_embeddings=[vector], n_results=count)
        # cosine 空间下 distance = 1 - 余弦相似度
        ranked = [(cid, 1 - dist) for cid, dist in zip(res["ids"][0], res["distances"][0])]
        distances = dict(zip(res["ids"][0], res["distances"][0]))
        # 融合只看前 FETCH_K 条 —— 后面的名次太靠后，参与也没意义
        vector_scored = ranked[:FETCH_K]
    vector_ids = [cid for cid, _ in vector_scored]

    # ---- 关键词路 ----
    keyword_scored: list[tuple[str, float]] = []
    if mode in ("hybrid", "bm25"):
        keyword_scored = [
            (all_ids[i], score) for i, score in _get_bm25(all_ids, all_docs).top_k(query, FETCH_K)
        ]
    keyword_ids = [cid for cid, _ in keyword_scored]

    # ---- 融合 ----
    if mode == "vector":
        order = vector_ids
    elif mode == "bm25":
        order = keyword_ids
    else:
        order = [cid for cid, _ in fuse([vector_scored, keyword_scored], method=fusion)]

    by_id = {cid: (doc, meta) for cid, doc, meta in zip(all_ids, all_docs, all_meta)}
    hits: list[dict] = []
    for cid in order[:k]:
        doc, meta = by_id.get(cid, ("", {}))
        in_vector = cid in vector_ids
        in_keyword = cid in keyword_ids
        hits.append(
            {
                "text": doc,
                "source": meta.get("source", "?"),
                "chunk": meta.get("chunk"),
                # cosine 空间下 distance = 1 - 余弦相似度
                "score": round(1 - distances[cid], 4) if cid in distances else None,
                "via": (
                    "both"
                    if in_vector and in_keyword
                    else ("vector" if in_vector else "keyword")
                ),
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
