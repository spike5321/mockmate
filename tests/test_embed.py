# -*- coding: utf-8 -*-
"""向量化入口（kb/embed.py）的单测。

这一层存在的意义是「建库和检索共用同一份向量化实现」，
所以测试重点在 **provider 怎么选、什么情况下该报错**，
全部离线：真模型一次都不加载。
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

import pytest

from kb import embed


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """每个用例都从干净的配置出发，并且不让真模型残留在模块缓存里。"""
    for key in (
        "EMBEDDING_PROVIDER",
        "ZHIPU_API_KEY",
        "LOCAL_EMBEDDING_MODEL",
        "FASTEMBED_CACHE_PATH",
        # 代码里用 setdefault 设的，这里登记一下让 monkeypatch 结束时清理掉
        "HF_HUB_DISABLE_SYMLINKS",
        "HF_HUB_DISABLE_SYMLINKS_WARNING",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(embed, "_local_model", None)


# ===========================================================================
# provider 怎么选
# ===========================================================================


def test_auto_uses_zhipu_when_key_present(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-test")
    assert embed.active_provider() == "zhipu"


def test_auto_falls_back_to_local_without_key():
    """★ 没 Key 也要能干活 —— 这是"评审 clone 下来就能跑"的关键那一步。"""
    assert embed.active_provider() == "local"


def test_explicit_provider_wins_over_key(monkeypatch):
    """配了 Key 但显式要求 local，就得听 local 的。"""
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-test")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    assert embed.active_provider() == "local"


def test_provider_name_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "LOCAL")
    assert embed.active_provider() == "local"


def test_unknown_provider_name_is_rejected(monkeypatch):
    """写错了要当场报错，不能默默按 auto 跑。"""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER"):
        embed.active_provider()


# ===========================================================================
# 签名（写进向量库的那个"身份"）
# ===========================================================================


def test_signature_distinguishes_provider_and_model(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-test")
    assert embed.provider_info()["signature"] == "zhipu:embedding-3"

    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    assert embed.provider_info()["signature"] == f"local:{embed.DEFAULT_LOCAL_MODEL}"


def test_local_model_name_can_be_overridden(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_EMBEDDING_MODEL", "jinaai/jina-embeddings-v2-base-zh")
    info = embed.provider_info()
    assert info["model"] == "jinaai/jina-embeddings-v2-base-zh"
    assert info["signature"] == "local:jinaai/jina-embeddings-v2-base-zh"


# ===========================================================================
# embed_texts 的分发
# ===========================================================================


class _FakeVector:
    """顶替 numpy 数组 —— 只用到 .tolist()。"""

    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


def test_embed_texts_routes_to_local_model(monkeypatch):
    calls = {}

    class _FakeModel:
        def embed(self, texts):
            calls["texts"] = texts
            return [_FakeVector([0.1, 0.2]) for _ in texts]

    monkeypatch.setattr(embed, "_get_local_model", lambda: _FakeModel())

    assert embed.embed_texts(["a", "b"]) == [[0.1, 0.2], [0.1, 0.2]]
    assert calls["texts"] == ["a", "b"]


def test_embed_texts_empty_input_short_circuits(monkeypatch):
    """空输入不该去加载模型（本地模型首次加载要十几秒）。"""

    def _explode():
        raise AssertionError("空输入不该加载模型")

    monkeypatch.setattr(embed, "_get_local_model", _explode)
    assert embed.embed_texts([]) == []


def test_explicit_zhipu_without_key_raises_instead_of_going_local(monkeypatch):
    """★ 显式要求 zhipu 却没有 Key → 报错，绝不静默降级。

    静默降级是最糟的选择：用户明明配了 Key（或以为配了），
    却悄悄用了本地小模型，只会觉得"检索质量怎么变差了"，
    永远想不到是这一层把 provider 换掉了。
    """
    monkeypatch.setenv("EMBEDDING_PROVIDER", "zhipu")
    with pytest.raises(RuntimeError, match="ZHIPU_API_KEY"):
        embed.embed_texts(["任意文本"])


# ===========================================================================
# 两个踩过的 Windows 坑
# ===========================================================================


def test_local_model_disables_hf_symlinks(monkeypatch):
    """★ Windows 上不设这个开关，本地模型**第一次运行必然失败**。

    HuggingFace 下载完要把 blobs/ 软链接成 snapshots/，普通用户没有建软链接的
    权限，报错却是 "NoSuchFile: model_optimized.onnx" —— 看着像模型没下完，
    其实 94MB 的 onnx 早就躺在缓存里了。
    """
    created = {}

    class _FakeTextEmbedding:
        def __init__(self, *args, **kwargs):
            created["kwargs"] = kwargs

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=_FakeTextEmbedding)
    )

    embed._get_local_model()

    assert os.environ["HF_HUB_DISABLE_SYMLINKS"] == "1"
    assert created["kwargs"]  # 确实建了模型（带缓存目录参数）


def test_default_cache_dir_is_not_system_temp():
    """★ 缓存默认不能落在系统临时目录。

    fastembed 的默认值是 %TEMP%/fastembed_cache —— 系统清理临时目录后
    模型就没了，得重新下 91MB。而「免 Key 免网络」正是本地模型的价值所在，
    模型不在本地，这个价值就没了。
    """
    cache = embed.local_cache_dir().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()

    assert cache.name == "fastembed"
    assert temp_root not in cache.parents
    assert cache == Path.home() / ".cache" / "fastembed"


def test_cache_dir_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path / "fe"))
    assert embed.local_cache_dir() == tmp_path / "fe"


def test_missing_fastembed_gives_actionable_error(monkeypatch):
    """没装 fastembed 时的报错要说清装什么，不能是一个光秃秃的 ImportError。"""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setitem(sys.modules, "fastembed", None)  # import 时抛 ImportError

    with pytest.raises(RuntimeError, match="pip install fastembed"):
        embed._get_local_model()
