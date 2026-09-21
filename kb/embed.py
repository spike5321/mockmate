# -*- coding: utf-8 -*-
"""向量化入口 —— 决定「文本交给谁转成向量」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么要有这一层？

改造前，向量化是散在 `build.py` 和 `search.py` 里的两段重复代码：
各自读 ZHIPU_API_KEY、各自建 LLMClient、各自调 embed()。
同一个能力有两份实现，想换 embedding 得改两个地方，而且**很容易只改一处**
（建库换了、检索没换，库和查询词向量空间不一致，检索结果直接失真）。
"支持换 embedding 模型"在那时候只是句话，代码上并不成立。

现在收敛成唯一的入口 embed_texts()，建库和检索都走它。
换 provider 只要一个环境变量，两条路径同时生效 —— 这才是真的可换。

    EMBEDDING_PROVIDER=auto   有 ZHIPU_API_KEY 就走智谱，没有就走本地（默认）
    EMBEDDING_PROVIDER=zhipu  强制走智谱（没有 Key 直接报错，不静默降级）
    EMBEDDING_PROVIDER=local  强制走本地模型

为什么要有本地兜底？不是为了"更准"，是为了**免 Key 免网络**：
评审 clone 下来不填任何配置也能建库、能检索。实测（见 README）
这个语料量级下，本地 512 维的命中率和智谱 2048 维没有差别。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
from pathlib import Path

from agent.llm import DEFAULT_EMBEDDING_MODEL

# 本地兜底用的向量模型。
#   BAAI/bge-small-zh-v1.5 —— 512 维 / 约 91MB / 中文
# fastembed 拉下来的是 Qdrant 转好的 ONNX 版（跑 onnxruntime，不依赖 torch）。
# 想换模型设 LOCAL_EMBEDDING_MODEL 即可，但**必须重建向量库**：
# 不同模型的向量空间不可比，混在一个库里检索不会报错，只是结果没意义。
DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"

PROVIDERS = ("auto", "zhipu", "local")

_local_model = None


def local_cache_dir() -> Path:
    """本地模型的缓存目录。

    ★ 不能用 fastembed 默认的 %TEMP%/fastembed_cache：
      系统清理临时目录之后模型就没了，得重新下 91MB。
      而「免 Key 免网络」正是本地模型存在的全部价值 —— 模型不在本地，价值就没了。
    """
    override = os.environ.get("FASTEMBED_CACHE_PATH")
    return Path(override) if override else Path.home() / ".cache" / "fastembed"


def local_model_name() -> str:
    return os.environ.get("LOCAL_EMBEDDING_MODEL") or DEFAULT_LOCAL_MODEL


def active_provider() -> str:
    """当前实际生效的 provider。auto 在这里被解析成具体的那个。"""
    name = (os.environ.get("EMBEDDING_PROVIDER") or "auto").strip().lower()
    if name not in PROVIDERS:
        raise ValueError(f"EMBEDDING_PROVIDER 只能是 {PROVIDERS} 之一，收到 {name!r}")
    if name == "auto":
        # 有 Key 用智谱（免费额度够用且更省事），没有就用本地模型
        return "zhipu" if os.environ.get("ZHIPU_API_KEY") else "local"
    return name


def _get_local_model():
    global _local_model
    if _local_model is None:
        # ★ Windows 上不设这个开关，本地模型**第一次运行必然失败**：
        #   HuggingFace 下载完要把 blobs/ 软链接成 snapshots/，普通用户没有
        #   建软链接的权限，报错是 "NoSuchFile: model_optimized.onnx" ——
        #   看起来像"模型没下载完"，其实 94MB 的 onnx 早就躺在缓存里了。
        #   这个报错极具误导性，实测踩过一次。
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError(
                "本地向量模型需要 fastembed：pip install fastembed "
                "（或者配 ZHIPU_API_KEY 走智谱）"
            ) from exc

        cache = local_cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        _local_model = TextEmbedding(local_model_name(), cache_dir=str(cache))
    return _local_model


def provider_info(model: str | None = None) -> dict:
    """当前向量化的"身份"：provider / model / signature。

    signature 会被写进向量库，检索时用来发现「库和当前配置不是一套」。
    为什么要比字符串而不是比维度？因为**维度相同 ≠ 向量空间相同**：
    512 维的中文向量模型有好几个，它们的向量互相检索是没意义的。
    """
    name = active_provider()
    if model:
        resolved = model
    elif name == "local":
        resolved = local_model_name()
    else:
        resolved = DEFAULT_EMBEDDING_MODEL
    return {"provider": name, "model": resolved, "signature": f"{name}:{resolved}"}


def embed_texts(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """把文本批量转成向量。**全项目唯一的向量化入口。**

    建库（kb.build）和检索（kb.search）都调这里，
    所以换 provider 不会出现"一边换了一边没换"的情况。
    """
    if not texts:
        return []
    info = provider_info(model)
    if info["provider"] == "local":
        return _embed_local(list(texts))
    return _embed_zhipu(list(texts), info["model"])


def _embed_local(texts: list[str]) -> list[list[float]]:
    model = _get_local_model()
    # fastembed 返回 numpy 数组，转回 list —— 交给 Chroma 之前统一成纯 Python 类型
    return [vector.tolist() for vector in model.embed(texts)]


def _embed_zhipu(texts: list[str], model: str) -> list[list[float]]:
    from agent.llm import LLMClient

    api_key = os.environ.get("ZHIPU_API_KEY", "")
    if not api_key:
        # 显式指定 zhipu 却没有 Key → 报错。绝不静默降级成本地，
        # 否则用户配了 Key 却发现"怎么检索质量变差了"，根本想不到是这里。
        raise RuntimeError("EMBEDDING_PROVIDER=zhipu 需要配置 ZHIPU_API_KEY")
    client = LLMClient(api_key=api_key, verbose=False)
    return client.embed(texts, embedding_model=model)
