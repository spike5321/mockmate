# -*- coding: utf-8 -*-
"""知识库存储层：切分 → 向量化 → 写入 Chroma。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
这一层是从 rag-knowledge-assistant 项目迁移过来的，但顺手修掉了原项目里
三个真实存在的问题，并在切分策略上又往前走了一步。四处改动都写在对应
代码的注释里，这里先列个总纲：

 ① 切分策略 —— 原实现只按 "\\n\\n" 切段，再把段落按字数累加到 400 字。
    两个毛病：
      a) pypdf 抽出来的 PDF 文本往往几乎不含空行，切不出段落，于是退化成
         按**字符位置**硬切，边界落在句子中间（而不是段落/行的边界上）；
      b) 更关键的是边界本身：它是"任意位置的 400 字"——
         实测问「缓存击穿」，命中的片段开头却是「缓存雪崩」的内容，
         因为两个小节被从中间切开又重新拼到了一起。
    现在改成：**先按 markdown 标题切小节**，小节内再按段落聚合。

 ② 覆盖式更新 —— 原实现的重入库判定是「这个文件名已存在就整篇跳过」，
    而且不报错。文档改了内容后重新入库永远不生效，还完全静默。

 ③ 片段 id 带内容指纹 —— 从 "文件名::序号" 变成 "文件名::序号::内容hash"。

 ④ 向量顺序校验 —— 接口返回的向量顺序不保证和输入一致，必须按 index 排回来。
    （这条在 agent/llm.py 的 embed() 里）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Callable

import chromadb

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / ".kb"            # 向量库落盘目录（.gitignore 已忽略）
DOCS_DIR = ROOT / "knowledge"    # 语料目录
COLLECTION_NAME = "mockmate_kb"

# 向量库的"空间"。余弦距离在语义检索里比欧氏距离更合适：
# 它只看方向不看长度，短句和长句也能公平比较。
# 选 cosine 的另一个好处是 distance = 1 - 余弦相似度，
# 算出来的 score 天然落在 0~1，直接能当"相似度"展示。
COLLECTION_META = {"hnsw:space": "cosine"}

CHUNK_SIZE = 400      # 单个片段的目标长度（字）
CHUNK_OVERLAP = 80    # 超长段落硬切时的重叠长度，避免答案正好被切在接缝上
SUPPORTED_SUFFIX = {".md", ".txt", ".pdf"}

# markdown 标题行（# ~ ####）。用它当切分边界。
_HEADING = re.compile(r"^(#{1,4})\s+(.+)$", re.M)

_collection = None


# ---------------------------------------------------------------------------
# 文档读取与切分
# ---------------------------------------------------------------------------


def read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    raise ValueError(f"不支持的文件类型: {suffix}")


def _pack_paragraphs(body: str, chunk_size: int, overlap: int) -> list[str]:
    """按空行分段，把相邻小段聚合成不超过 chunk_size 的块。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]

    # ★ 修正 ①a：切不出段落时退回按单行切。
    #   PDF 抽取的文本常常一行一段、几乎没有空行，于是"段落"只有一个。
    #   原逻辑此时要么整篇算一片（不足 chunk_size 时），要么按字符位置硬切
    #   （把句子从中间劈开）。退回按行切之后，边界落在行首。
    if len(paragraphs) <= 1 and "\n" in body:
        paragraphs = [ln.strip() for ln in body.split("\n") if ln.strip()]

    pieces: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 1 <= chunk_size:
            current = f"{current}\n{para}".strip()
            continue
        if current:
            pieces.append(current)
        # 单段本身就超长（比如整段没有空行的表格）→ 硬切，带重叠
        while len(para) > chunk_size:
            pieces.append(para[:chunk_size])
            para = para[chunk_size - overlap :]
        current = para
    if current:
        pieces.append(current)
    return pieces


def split_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """把一篇文档切成检索片段。

    ★ 修正 ①b（在 ①a 之上又深了一层）：**先按 markdown 标题切小节**，
    每个小节再按段落聚合。

    为什么这一步很关键？原来的做法只管按字数累加到 400 字，切出来的边界是
    "任意位置的 400 字"。实测就是这样：问「缓存击穿」，
    命中的片段开头却是「缓存雪崩」的正文 —— 两个小节被从中间切开又重新拼
    在了一起。片段里混着两三个知识点，语义自然被稀释，相似度全线偏低。

    改成按标题切之后，一个片段 = 一个知识点，这正是面试情报最自然的检索粒度。

    另外每条片段前面会带上所属小节标题（如【2. 缓存击穿】），
    这样模型拿到片段就能知道"这段话是在讲哪个知识点"，
    而不是看到一段没头没尾的正文。
    """
    text = text.replace("\r\n", "\n").strip()
    parts = _HEADING.split(text)

    # 切成 (标题, 正文) 列表。parts 的结构是 [标题前内容, #, 标题1, 正文1, ##, 标题2, 正文2, ...]
    sections: list[tuple[str, str]] = []
    preamble = parts[0].strip()
    if preamble:
        sections.append(("", preamble))
    for i in range(1, len(parts) - 1, 3):
        title = parts[i + 1].strip()
        body = parts[i + 2].strip()
        if title or body:
            sections.append((title, body))

    chunks: list[str] = []
    for title, body in sections:
        if not body:
            continue
        for piece in _pack_paragraphs(body, chunk_size, overlap):
            chunks.append(f"【{title}】\n{piece}" if title else piece)
    return chunks


def collect_files(targets: list[Path]) -> list[Path]:
    """把"文件或目录"的混合列表展开成文件列表，目录递归展开。"""
    files: list[Path] = []
    for t in targets:
        if t.is_dir():
            files.extend(sorted(p for p in t.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIX))
        elif t.exists():
            files.append(t)
    return files


# ---------------------------------------------------------------------------
# 向量库
# ---------------------------------------------------------------------------


def get_collection():
    """拿向量库里的集合（不存在就建）。

    加了模块级缓存：Chroma 每次 PersistentClient 都要读 sqlite，
    检索在面试过程中会被调用多次，没必要反复建客户端。
    """
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(str(KB_DIR))
        _collection = client.get_or_create_collection(COLLECTION_NAME, metadata=COLLECTION_META)
    return _collection


def _chunk_id(source: str, index: int, text: str) -> str:
    """★ 修正 ③：id 里带上内容指纹，内容变了 id 就变。"""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    return f"{source}::{index}::{digest}"


def ingest(
    files: list[Path],
    embed_fn: Callable[[list[str]], list[list[float]]],
    reset: bool = False,
) -> list[dict]:
    """把文档切分、向量化后写入向量库。

    embed_fn 由调用方传入（通常是 LLMClient.embed），这样存储层不用关心
    向量是用哪个模型、哪家服务算出来的 —— 换 embedding 不影响这一层。

    返回每个文件的处理结果，供命令行打印。
    """
    col = get_collection()

    if reset:
        existing = col.get(include=[]).get("ids") or []
        if existing:
            col.delete(ids=existing)

    results: list[dict] = []
    for path in files:
        text = read_file(path)
        chunks = split_text(text)
        if not chunks:
            results.append({"source": path.name, "chunks": 0, "status": "empty"})
            continue

        # 先向量化再删旧数据：万一网络挂了，旧索引还在，不至于查不到东西
        try:
            vectors = embed_fn(chunks)
        except Exception as exc:  # noqa: BLE001
            results.append(
                {"source": path.name, "chunks": len(chunks), "status": "error", "error": str(exc)}
            )
            continue

        # ★ 修正 ②：覆盖式更新。文档改了内容，重新入库会真正生效。
        col.delete(where={"source": path.name})

        col.add(
            ids=[_chunk_id(path.name, i, c) for i, c in enumerate(chunks)],
            documents=chunks,
            embeddings=vectors,
            metadatas=[{"source": path.name, "chunk": i} for i in range(len(chunks))],
        )
        results.append({"source": path.name, "chunks": len(chunks), "status": "added"})

    return results
