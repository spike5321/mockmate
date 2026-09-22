# -*- coding: utf-8 -*-
"""混合检索（BM25 + 融合）单测。全部离线。

这一层的价值只在「两路合起来比单路好」上，所以测试重点也在这儿：
关键词路能不能把向量路漏掉的专有名词捞回来、融合是不是真的按名次算。
"""

from __future__ import annotations

import pytest

from kb import search
from kb.bm25 import BM25, tokenize
from kb.fusion import fuse, normalized_sum, rrf_fuse


@pytest.fixture(autouse=True)
def clean_bm25_cache():
    """BM25 索引有模块级缓存 —— 每个用例都从干净状态出发。"""
    search.reset_cache()
    yield
    search.reset_cache()


# ===========================================================================
# 切词
# ===========================================================================


def test_chinese_is_split_into_bigrams():
    """中文没空格，切成二元组：「缓存击穿」→ 缓存 / 存击 / 击穿。"""
    assert tokenize("缓存击穿") == ["缓存", "存击", "击穿"]


def test_single_chinese_char_survives():
    assert tokenize("锁") == ["锁"]


def test_latin_terms_are_kept_whole_and_lowercased():
    """★ 专有名词必须整词保留 —— 这正是加关键词路的目的。

    要是把 LRU 也切成 l / r / u，它会跟随便什么字母都撞，那等于没加。
    """
    assert tokenize("LRU") == ["lru"]
    assert "redis" in tokenize("Redis 缓存")
    assert "lru" in tokenize("LRU 缓存")


def test_symbols_stay_inside_the_term():
    """B+ 树 / C++ / .NET 这类词，符号是词的一部分，不能被切掉。"""
    assert "b+" in tokenize("B+树")
    assert "c++" in tokenize("C++ 与 Java")


def test_mixed_text():
    tokens = tokenize("Redis 的 LRU 淘汰")
    assert "redis" in tokens
    assert "lru" in tokens
    assert "淘汰" in tokens


# ===========================================================================
# BM25
# ===========================================================================


DOCS = [
    "Redis 缓存穿透是指查询一个数据库里也不存在的数据，导致每次都打到数据库。",
    "LRU 是最近最少使用的淘汰策略，用哈希表加双向链表实现 O(1)。",
    "系统设计题要先问清楚需求、规模和约束，再谈方案。",
]


def test_bm25_ranks_the_exact_match_first():
    top = BM25(DOCS).top_k("LRU 淘汰", 3)
    assert top, "应该至少命中一条"
    assert top[0][0] == 1, "讲 LRU 的那句该排第一"


def test_bm25_leaves_out_docs_with_no_hit():
    """一个词都没命中的片段不该出现在结果里 —— 凑数会让调用方以为它也相关。"""
    assert [i for i, _ in BM25(DOCS).top_k("LRU", 3)] == [1]


def test_bm25_scores_are_zero_for_an_unrelated_query():
    assert BM25(DOCS).scores("完全不相关的词儿") == [0.0, 0.0, 0.0]


def test_bm25_empty_query_is_safe():
    index = BM25(DOCS)
    assert index.scores("") == [0.0, 0.0, 0.0]
    assert index.top_k("", 3) == []


def test_bm25_empty_corpus_is_safe():
    index = BM25([])
    assert index.scores("任意") == []
    assert index.top_k("任意", 3) == []


def test_rare_terms_outweigh_common_ones():
    """★ IDF 的意义：到处都是的词不值钱。

    「面试」在三条里都有，LRU 只在一条里 —— 后者更能说明"这条讲的是什么"。
    """
    docs = [
        "面试里会问 Redis 的缓存穿透。",
        "面试里会问 LRU 淘汰策略。",
        "面试里会问系统设计。",
    ]
    index = BM25(docs)
    assert index.idf["面试"] < index.idf["lru"]


def test_bm25_order_is_stable_for_ties():
    """同分也要有固定顺序 —— 同一句话问两次给出不同排名，调试的人会以为见了鬼。"""
    index = BM25(["完全一样的句子", "完全一样的句子"])
    first = index.top_k("完全一样", 2)
    assert first == index.top_k("完全一样", 2)
    assert [i for i, _ in first] == [0, 1]


# ===========================================================================
# RRF
# ===========================================================================


def test_rrf_rewards_being_high_on_both_lists():
    fused = dict(rrf_fuse([["a", "b", "c"], ["a", "c", "b"]]))
    assert fused["a"] > fused["b"]
    assert fused["a"] > fused["c"]


def test_rrf_handles_a_route_that_missed_everything():
    """★ 关键词路碰到一句纯口语的问法，可能一条都命中不了。

    这时候融合必须安静地退化成「就用向量结果」，而不是像加权求和那样
    把整体分数一起拉垮。
    """
    assert [doc for doc, _ in rrf_fuse([["a", "b"], []])] == ["a", "b"]


def test_rrf_keeps_a_doc_found_by_only_one_route():
    """两路各自的第一名同分。

    ⚠️ 这条钉的**不是设计，是已知短板**：两路对第一名意见不一致时，
    等权 RRF 无法表达"哪一路更可信"，顺序只能由 id 决定。
    正因为如此默认融合才换成了 normalized_sum —— 见 kb/fusion.py 开头的实测。
    改这条断言之前先看 scripts/compare_retrieval.py 的数字。
    """
    fused = dict(rrf_fuse([["a"], ["z"]]))
    assert set(fused) == {"a", "z"}
    assert fused["a"] == fused["z"]      # 都是各自的第一名，得分一样


def test_rrf_result_is_sorted_desc():
    scores = [score for _, score in rrf_fuse([["b", "a"], ["a", "b"]])]
    assert scores == sorted(scores, reverse=True)


def test_rrf_empty_input():
    assert rrf_fuse([[], []]) == []


# ===========================================================================
# 归一化加权求和（默认融合）
# ===========================================================================


def test_normalized_sum_keeps_rank_gaps_within_a_route():
    """★ 和 RRF 的关键差别：同一路内部，名次差异必须被保留。

    RRF 在 8 条的列表上，第 1 名和第 8 名只差 11%；归一化之后差 100% ——
    这样"这条在本路排第几"才真的算数。
    """
    fused = dict(normalized_sum([[("a", 0.9), ("b", 0.8), ("c", 0.7)]]))
    assert fused["a"] == 1.0
    assert fused["c"] == 0.0
    assert fused["b"] == pytest.approx(0.5)


def test_normalized_sum_rewards_being_found_by_both_routes():
    """★ 混合检索的意义：两路都召回了的片段要能反超只被一路召回的第一名。

    这里是「LRU 那条」的抽象版：不是任何一路的第一名，
    但两路都给了它不低的名次，合起来应该压过单路的第一名。
    """
    vector = [("onlyvec", 0.90), ("both", 0.88), ("x", 0.70)]
    keyword = [("both", 9.0), ("y", 4.0), ("onlyvec", 1.0)]
    order = [doc for doc, _ in normalized_sum([vector, keyword])]
    assert order[0] == "both"


def test_normalized_sum_handles_a_route_that_missed_everything():
    """关键词路一条都没命中时，安静退化成"就用向量结果"。"""
    assert [d for d, _ in normalized_sum([[("a", 0.9), ("b", 0.8)], []])] == ["a", "b"]


def test_normalized_sum_empty_input():
    assert normalized_sum([[], []]) == []


def test_normalized_sum_rejects_mismatched_weights():
    with pytest.raises(ValueError, match="权重个数"):
        normalized_sum([[("a", 1.0)], [("b", 2.0)]], weights=[1.0])


def test_fuse_dispatch_matches_the_direct_calls():
    lists = [[("a", 0.9), ("b", 0.8)], [("b", 9.0), ("c", 4.0)]]
    assert fuse(lists, method="norm") == normalized_sum(lists)
    assert fuse(lists, method="rrf") == rrf_fuse([["a", "b"], ["b", "c"]])


def test_fuse_rejects_unknown_method():
    with pytest.raises(ValueError, match="method"):
        fuse([[("a", 1.0)]], method="magic")


# ===========================================================================
# retrieve 的三种模式
# ===========================================================================


class _FakeCollection:
    """按固定顺序返回"向量排名"的假库 —— 方便看清关键词路补了什么。"""

    def __init__(self, chunks: list[str]):
        self._docs = chunks
        self._ids = [f"doc{i}" for i in range(len(chunks))]

    def count(self) -> int:
        return len(self._ids)

    def get(self, include=None):
        return {
            "ids": self._ids,
            "documents": self._docs,
            "metadatas": [{"source": "t.md", "chunk": i} for i in range(len(self._ids))],
        }

    def query(self, query_embeddings, n_results):
        n = min(n_results, len(self._ids))
        return {
            "ids": [self._ids[:n]],
            "distances": [[0.1 * (i + 1) for i in range(n)]],
        }


CORPUS = [
    "Redis 缓存穿透是指查询一个数据库里也不存在的数据。",
    "LRU 是最近最少使用的淘汰策略，用哈希表加双向链表。",
    "系统设计题要先问清楚需求、规模和约束。",
]


def _stub_collection(monkeypatch):
    import kb.search as search_mod

    monkeypatch.setattr(search_mod, "get_collection", lambda: _FakeCollection(CORPUS))
    monkeypatch.setattr(search_mod, "get_embed_sig", lambda: None)
    monkeypatch.setattr(search_mod, "embed_texts", lambda texts, model=None: [[0.1, 0.2]])


def test_mode_must_be_known():
    with pytest.raises(ValueError, match="mode"):
        search.retrieve("任意", mode="fuzzy")


def test_bm25_mode_puts_the_exact_match_on_top(monkeypatch):
    """关键词模式：讲 LRU 的那条该排第一（假库里它的向量排名是第 2）。"""
    _stub_collection(monkeypatch)
    hits = search.retrieve("LRU 淘汰", k=3, mode="bm25")
    assert hits[0]["text"].startswith("LRU")


def test_vector_mode_follows_the_vector_order(monkeypatch):
    _stub_collection(monkeypatch)
    hits = search.retrieve("LRU 淘汰", k=3, mode="vector")
    assert hits[0]["text"].startswith("Redis")     # 假库把第一条排在向量第一


def test_hybrid_lifts_what_the_keyword_route_found(monkeypatch):
    """★★ 混合检索的意义就在这一条上。

    假库里向量把「Redis 缓存穿透」排第一、LRU 那条排第二；而关键词路把 LRU 排第一。
    融合之后，**两路都靠前的 LRU 那条应该反超上来** ——
    这就是"关键词路补上了向量路漏掉的专有名词"。
    """
    _stub_collection(monkeypatch)
    hits = search.retrieve("LRU 淘汰", k=3, mode="hybrid")
    assert hits[0]["text"].startswith("LRU")


def test_hybrid_accepts_both_fusion_methods(monkeypatch):
    """两种融合算法都得能跑通 —— 输的那个留着，换语料后要重比。"""
    _stub_collection(monkeypatch)
    for method in ("norm", "rrf"):
        hits = search.retrieve("LRU 淘汰", k=3, mode="hybrid", fusion=method)
        assert len(hits) == 3


def test_unknown_fusion_is_rejected():
    with pytest.raises(ValueError, match="fusion"):
        search.retrieve("任意", fusion="magic")


def test_via_field_says_how_each_hit_was_found(monkeypatch):
    _stub_collection(monkeypatch)
    hits = search.retrieve("LRU 淘汰", k=3, mode="hybrid")
    by_text = {h["text"][:3]: h["via"] for h in hits}
    assert by_text["LRU"] == "both"          # 两路都召回了
    assert hits[0]["score"] is not None      # 关键词召回的那条也有真实相似度


def test_bm25_only_hits_still_carry_a_score(monkeypatch):
    """★ 只被关键词路召回的片段，score 也不能是空的。

    向量路是拿**全部**片段算的距离，所以每个片段都有真实相似度可以回填 ——
    否则模型会收到一条"没有分"的结果，不知道该不该信它。
    """
    _stub_collection(monkeypatch)
    hits = search.retrieve("系统设计 需求", k=3, mode="hybrid")
    for hit in hits:
        assert hit["score"] is not None
