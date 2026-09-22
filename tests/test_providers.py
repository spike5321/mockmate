# -*- coding: utf-8 -*-
"""供应商注册表单测。全部离线。

两个重点：
  ① 解析优先级（显式参数 > 环境变量 > 注册表默认）
  ② **Key 不能出现在任何会被打印或落盘的地方** ——
     trace 和报告是要提交进仓库、贴给别人看的，泄一次就是事故。
"""

from __future__ import annotations

import pytest

from agent import providers
from agent.providers import ProviderError

_ENV_KEYS = (
    "ZHIPU_API_KEY",
    "DEEPSEEK_API_KEY",
    "OLLAMA_API_KEY",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_PROVIDER",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ===========================================================================
# 解析
# ===========================================================================


def test_unknown_provider_is_rejected():
    with pytest.raises(ProviderError, match="不认识的供应商"):
        providers.resolve(provider="openai")


def test_missing_key_names_the_variable(monkeypatch):
    """报错必须说清配哪个变量 —— 只说"没配 Key"等于没说。"""
    with pytest.raises(ProviderError, match="ZHIPU_API_KEY"):
        providers.resolve(model="glm-4.5-flash")


def test_key_and_endpoint_come_from_the_registry(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-z")
    ep = providers.resolve(model="glm-4.5-flash")
    assert ep.provider == "zhipu"
    assert ep.api_key == "sk-z"
    assert ep.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert ep.model == "glm-4.5-flash"
    assert ep.supports_tools is True


def test_model_name_guesses_the_provider(monkeypatch):
    """--model deepseek-chat 该自己找到 deepseek 的端点，不用每次写 --provider。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-d")
    ep = providers.resolve(model="deepseek-chat")
    assert ep.provider == "deepseek"
    assert ep.base_url == "https://api.deepseek.com/v1"


def test_explicit_provider_wins_over_guessing(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-z")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-d")
    ep = providers.resolve(model="deepseek-chat", provider="zhipu")
    assert ep.provider == "zhipu"


def test_unknown_model_falls_back_to_the_default_provider(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-z")
    ep = providers.resolve(model="some-model-nobody-registered")
    assert ep.provider == providers.DEFAULT_PROVIDER


def test_default_model_comes_from_the_registry(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-z")
    assert providers.resolve().model == providers.PROVIDERS["zhipu"].models[0]


def test_provider_env_var_selects_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert providers.resolve().provider == "ollama"


def test_ollama_needs_no_key():
    """本地模型不该因为"没配 Key"被拦下 —— 它本来就不需要。"""
    ep = providers.resolve(model="qwen2.5:7b")
    assert ep.provider == "ollama"
    assert ep.api_key                      # 非空：端点会校验 Authorization 头
    assert "local" in ep.api_key


def test_generic_env_vars_can_override_everything(monkeypatch):
    """LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 三个变量能接任何 OpenAI 兼容端点。"""
    monkeypatch.setenv("LLM_BASE_URL", "https://my-gateway.example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-custom")
    monkeypatch.setenv("LLM_MODEL", "my-model")
    ep = providers.resolve()
    assert ep.base_url == "https://my-gateway.example.com/v1"
    assert ep.api_key == "sk-custom"
    assert ep.model == "my-model"


def test_base_url_trailing_slash_is_trimmed(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://x.example.com/v1/")
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    assert providers.resolve().base_url == "https://x.example.com/v1"


# ===========================================================================
# Key 的纪律
# ===========================================================================


def test_safe_repr_never_contains_the_key(monkeypatch):
    """★ Endpoint 会被打印进日志、可能进 trace，所以它必须能安全地描述自己。"""
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-super-secret-value")
    ep = providers.resolve(model="glm-4.5-flash")
    assert "sk-super-secret-value" not in ep.safe_repr()
    assert ep.model in ep.safe_repr()


def test_describe_all_never_prints_the_key(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-super-secret-value")
    text = providers.describe_all()
    assert "sk-super-secret-value" not in text
    assert "zhipu" in text
    assert "已配置" in text
    assert "未配置" in text          # deepseek 没配


def test_describe_all_marks_local_providers_as_key_free():
    assert "不需要 Key" in providers.describe_all()


# ===========================================================================
# 上层入口
# ===========================================================================


def test_client_from_provider_uses_the_registry(monkeypatch):
    """from_provider 是上层唯一的建客户端入口 —— 它得真的吃注册表。"""
    from agent.llm import LLMClient

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-d")
    client = LLMClient.from_provider(model="deepseek-chat", verbose=False)
    assert client.model == "deepseek-chat"
    assert client.base_url == "https://api.deepseek.com/v1"
    assert client.api_key == "sk-d"


def test_client_from_provider_propagates_provider_errors(monkeypatch):
    from agent.llm import LLMClient

    with pytest.raises(ProviderError):
        LLMClient.from_provider(model="glm-4.5-flash")   # 没配 Key
