# -*- coding: utf-8 -*-
"""知识库单测：切分策略、片段指纹、检索结果换算。

切分这块是**从 rag 项目移植时修掉三个真问题**的地方，所以测试写得比较细：
 - 按 markdown 标题切（一个片段 = 一个知识点）
 - 无空行的文本（PDF 抽取常见）要退回按行切，不能整篇变一块
 - 超长段落硬切要带重叠
 - 片段 id 带内容指纹

检索那部分不联网：用一个假向量库 + 假 embedding 客户端顶替。
"""

from __future__ import annotations

import pytest

pytest.importorskip("chromadb", reason="切分逻辑所在的模块 import 了 chromadb")

from kb.store import (  # noqa: E402
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    _chunk_id,
    _pack_paragraphs,
    collect_files,
    split_text,
)

# ===========================================================================
# 按 markdown 标题切分
# ===========================================================================

DOC = """# 面试流程

## 1. 开场

先做两三分钟的自我介绍，面试官从中抓点追问。

## 2. 缓存击穿

击穿是指某个热点 key 过期的瞬间，大量请求直接打到数据库上。

## 3. 缓存雪崩

雪崩是指大批 key 在同一时间过期，压力整体压到数据库。
"""


def test_sections_become_separate_chunks():
    """一个片段 = 一个知识点。这是修掉「缓存击穿命中的却是雪崩内容」的关键。"""
    chunks = split_text(DOC)
    assert len(chunks) == 3
    assert all(c.startswith("【") for c in chunks)


def test_chunk_boundaries_do_not_mix_topics():
    """★ 这条是那个 bug 的回归测试。

    旧实现按 400 字硬累加，切出来的片段里混着两三个知识点，语义被稀释。
    现在击穿的片段里不该出现雪崩的正文。
    """
    chunks = split_text(DOC)
    breach = next(c for c in chunks if "缓存击穿" in c)
    assert "击穿是指" in breach
    assert "雪崩是指" not in breach


def test_chunk_carries_its_section_title():
    """片段带上所属小节标题，模型才知道这段在讲什么，而不是一段没头没尾的正文。"""
    chunks = split_text(DOC)
    assert "【2. 缓存击穿】" in chunks[1]


def test_preamble_without_heading_is_kept_bare():
    """正文前的引言不属于任何小节，不该被硬安一个标题。"""
    chunks = split_text("这是一段没有标题的开场白。\n\n# 第一章\n\n正文内容。")
    assert chunks[0] == "这是一段没有标题的开场白。"
    assert chunks[1].startswith("【第一章】")


def test_heading_without_body_is_skipped():
    """只有标题没有正文的小节，切出来会是个空片段 —— 直接丢掉。"""
    chunks = split_text("# 空章节\n\n## 有内容\n\n正文。")
    assert len(chunks) == 1
    assert "空章节" not in chunks[0]


def test_empty_text_yields_no_chunks():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_crlf_is_normalized():
    """Windows 换行不该影响切分结果。"""
    assert split_text(DOC.replace("\n", "\r\n")) == split_text(DOC)


def test_paragraphs_are_packed_up_to_chunk_size():
    """同一小节内的短段落要聚合，别把每段都切成一个片段。"""
    body = "\n\n".join(f"第{i}段内容，比较短。" for i in range(5))
    chunks = split_text(f"# 标题\n\n{body}")
    assert len(chunks) == 1


def test_long_paragraph_is_hard_split_with_overlap():
    """★ 单段超长（整段没有空行的表格 / PDF 行）要硬切，并带重叠。

    重叠是为了避免答案正好被切在接缝上 —— 上一块的尾巴和下一块的开头有一段重合，
    检索时无论命中哪一块，都能看到完整的上下文。
    """
    body = "甲" * 1000
    chunks = split_text(f"# 标题\n\n{body}")
    pieces = [c.split("\n", 1)[1] for c in chunks]

    assert len(pieces) >= 2
    assert all(len(p) <= CHUNK_SIZE for p in pieces)
    assert pieces[0][-CHUNK_OVERLAP:] == pieces[1][:CHUNK_OVERLAP]


# ===========================================================================
# 无空行文本：PDF 抽取的典型形态
# ===========================================================================


def test_text_without_blank_lines_falls_back_to_line_split():
    """★ 修正 ①a 的回归测试。

    PDF 抽出来的文本常常一行一段、几乎没有空行。旧实现按 "\\n\\n" 切，
    结果是「整篇 = 1 个片段」，等于没切。所以切不出段落时要退回按行切。

    断言写成"每块都不超长"，而不是写死块数 —— 前者才是这条修正的实质，
    后者只是跟着字符数变。
    """
    body = "\n".join(f"第{i}行内容大约二十个字左右吧" for i in range(60))
    chunks = split_text(f"# 标题\n\n{body}")

    assert len(chunks) > 1, "又退化成整篇一块了"
    for chunk in chunks:
        assert len(chunk.split("\n", 1)[1]) <= CHUNK_SIZE


def test_pack_paragraphs_single_line_body():
    """直接测底层：只有一行且超长 → 硬切，不是原样返回一块。"""
    pieces = _pack_paragraphs("乙" * 900, CHUNK_SIZE, CHUNK_OVERLAP)
    assert len(pieces) >= 2
    assert all(len(p) <= CHUNK_SIZE for p in pieces)


def test_pack_paragraphs_keeps_short_paragraphs_together():
    pieces = _pack_paragraphs("短句一。\n\n短句二。\n\n短句三。", CHUNK_SIZE, CHUNK_OVERLAP)
    assert len(pieces) == 1


# ===========================================================================
# 片段 id：带内容指纹
# ===========================================================================


def test_chunk_id_changes_when_content_changes():
    """★ 修正 ③：文档改了内容，片段 id 也要变，否则更新会被当成"已存在"。"""
    a = _chunk_id("redis.md", 0, "原内容")
    b = _chunk_id("redis.md", 0, "改过的内容")
    assert a != b


def test_chunk_id_is_stable_for_same_content():
    assert _chunk_id("redis.md", 3, "同样内容") == _chunk_id("redis.md", 3, "同样内容")


def test_chunk_id_shape():
    assert _chunk_id("redis.md", 2, "内容").startswith("redis.md::2::")


# ===========================================================================
# 文件收集
# ===========================================================================


def test_collect_files_filters_by_suffix_and_recurses(tmp_path):
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    (tmp_path / "c.bin").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.pdf").write_bytes(b"%PDF-1.4")
    (sub / "e.md").write_text("x", encoding="utf-8")

    names = {p.name for p in collect_files([tmp_path])}
    assert names == {"a.md", "b.txt", "d.pdf", "e.md"}


def test_collect_files_accepts_explicit_file_and_skips_missing(tmp_path):
    f = tmp_path / "only.md"
    f.write_text("x", encoding="utf-8")
    got = collect_files([f, tmp_path / "不存在.md"])
    assert got == [f]


# ===========================================================================
# 检索：distance → 相似度
# ===========================================================================


class _FakeCollection:
    def __init__(self, distances, limit_seen=None):
        self._distances = distances
        self.limit_seen = limit_seen

    def count(self):
        return len(self._distances)

    def query(self, query_embeddings, n_results):
        if self.limit_seen is not None:
            self.limit_seen.append(n_results)
        return {
            "documents": [[f"片段{i}" for i in range(len(self._distances))]],
            "metadatas": [
                [{"source": "redis.md", "chunk": i} for i in range(len(self._distances))]
            ],
            "distances": [self._distances],
        }


class _FakeEmbedder:
    def __init__(self):
        self.texts = None

    def embed(self, texts):
        self.texts = texts
        return [[0.1, 0.2, 0.3]]


def test_retrieve_converts_cosine_distance_to_similarity(monkeypatch):
    """cosine 空间下 distance = 1 - 余弦相似度，score 要落回 0~1 的相似度口径。"""
    from kb import search

    monkeypatch.setattr(
        search, "get_collection", lambda: _FakeCollection([0.1, 0.4])
    )
    monkeypatch.setattr(search, "_client", _FakeEmbedder())

    hits = search.retrieve("缓存一致性", k=3)
    assert [h["score"] for h in hits] == [0.9, 0.6]
    assert hits[0]["source"] == "redis.md"
    assert hits[0]["chunk"] == 0


def test_retrieve_clamps_k_to_collection_size(monkeypatch):
    """库里只有 2 块时，要 5 条不能报错 —— n_results 得夹紧。"""
    from kb import search

    seen: list[int] = []
    monkeypatch.setattr(search, "get_collection", lambda: _FakeCollection([0.2, 0.3], seen))
    monkeypatch.setattr(search, "_client", _FakeEmbedder())

    search.retrieve("query", k=5)
    assert seen == [2]


def test_empty_store_returns_empty_without_embedding(monkeypatch):
    """★ 库没建是正常状态，不是错误：直接返回 []，不去读 Key、不发请求。"""
    from kb import search

    class _Exploding(_FakeEmbedder):
        def embed(self, texts):
            raise AssertionError("空库不该触发 embedding 调用")

    monkeypatch.setattr(search, "get_collection", lambda: _FakeCollection([]))
    monkeypatch.setattr(search, "_client", _Exploding())

    assert search.retrieve("anything") == []
