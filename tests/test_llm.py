# -*- coding: utf-8 -*-
"""llm.py 单测：失败分类与重试。全部离线，不发真实请求。

重点在**失败分类**：它是上层「失败升级阶梯」唯一的判断依据。
分类错了，上层就会拿错策略 —— 把"Key 过期"当成"网络抖动"，
就会一直重试到天荒地老。
"""

from __future__ import annotations

import pytest
import requests

from agent import llm as llm_mod
from agent.llm import ERROR_KINDS, LLMClient, LLMError, classify_error


def _client(**kw) -> LLMClient:
    kw.setdefault("verbose", False)
    return LLMClient(api_key="sk-test", **kw)


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", payload: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {"ok": True}

    def json(self):
        return self._payload


@pytest.fixture
def no_sleep(monkeypatch):
    """把退避睡��换成空操作 —— 测重试逻辑不该真的等 10 秒。"""
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _seconds: None)


# ===========================================================================
# 分类规则
# ===========================================================================


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, "rate_limit"),
        (401, "auth"),
        (403, "auth"),
        (404, "model_missing"),
        (500, "server"),
        (502, "server"),
        (503, "server"),
        (504, "server"),
        (400, "other"),
        (422, "other"),
    ],
)
def test_classify_by_status(status, expected):
    assert classify_error(status, "") == expected


def test_classify_falls_back_to_narrow_keywords():
    """状态码判不出来时，只认很窄的关键词，不做宽泛的语义猜测。"""
    assert classify_error(400, '{"error":"Invalid API key provided"}') == "auth"
    assert classify_error(400, '{"error":"model not found: glm-9"}') == "model_missing"


def test_classify_does_not_guess_from_a_bare_mention_of_model():
    """★ 光出现 "model" 三个字母不算证据。

    错误体里几乎每条都会提到 model 字段，靠这个判 model_missing 会大面积误判 ——
    而误判的代价是上层拿错策略，比不分类更糟。
    """
    assert classify_error(400, '{"error":"invalid parameter: model.temperature"}') == "other"


def test_every_returned_kind_is_declared():
    """返回值必须在 ERROR_KINDS 里 —— 防止手滑写错字符串。"""
    for status in (429, 401, 403, 404, 400, 500, 503):
        assert classify_error(status, "") in ERROR_KINDS


# ---------------------------------------------------------------------------
# 下面几条的响应体是**实测抓下来的原文**，不是编的。
# 起先只按状态码 + 英文关键词判，结果"模型名写错"被判成了 other ——
# 探一次真实端点就把这个漏洞暴露了。
# ---------------------------------------------------------------------------


def test_platform_error_code_wins_over_status():
    """★ 模型名写错时智谱返回 HTTP 400 + code 1211。

    只看状态码会判成 other（400 看着像"参数写错了"），
    但它的含义很明确：模型不存在 —— 重试没有意义，得换模型名。
    """
    body = '{"error":{"code":"1211","message":"模型不存在，请检查模型代码。"}}'
    assert classify_error(400, body) == "model_missing"


def test_rate_limit_code_is_recognized():
    """限流的错误码 1305（实测出现在 HTTP 429 里）。"""
    body = '{"error":{"code":"1305","message":"该模型当前访问量过大"}}'
    assert classify_error(429, body) == "rate_limit"
    # 就算平台把它塞进别的状态码，也该按错误码判对
    assert classify_error(400, body) == "rate_limit"


def test_real_auth_response_is_classified():
    """实测抓到的真实响应：HTTP 401 + 中文文案。"""
    body = '{"error":{"code":"401","message":"令牌已过期或验证不正确"}}'
    assert classify_error(401, body) == "auth"


def test_unknown_platform_code_falls_through_to_status():
    """表里没有的错误码要平滑落到状态码判断，不能卡在"认识 code"这一步。"""
    assert classify_error(429, '{"error":{"code":"9999","message":"?"}}') == "rate_limit"
    assert classify_error(500, '{"error":{"code":"9999","message":"?"}}') == "server"


def test_body_that_is_not_json_does_not_blow_up():
    assert classify_error(400, "plain text, not json at all") == "other"


def test_chinese_keywords_work_when_code_is_absent():
    """没有错误码时的中文兜底 —— 平台的文案不一定带 code。"""
    assert classify_error(400, '{"message":"模型不存在"}') == "model_missing"


# ===========================================================================
# LLMError 本身
# ===========================================================================


def test_llm_error_defaults_to_other():
    exc = LLMError("boom")
    assert exc.kind == "other"
    assert exc.status is None


def test_llm_error_still_is_a_runtime_error():
    """老代码里有 except RuntimeError / except Exception，不能被新字段破坏。"""
    exc = LLMError("boom", kind="rate_limit", status=429)
    assert isinstance(exc, RuntimeError)
    assert exc.kind == "rate_limit"
    assert exc.status == 429


def test_missing_key_is_an_auth_error():
    """「没配 Key」和「Key 过期」对用户是同一件事：去改配置。

    所以它们该是同一个 kind，而不是一种 ValueError、一种 LLMError。
    """
    with pytest.raises(LLMError) as ei:
        LLMClient(api_key="")
    assert ei.value.kind == "auth"


# ===========================================================================
# 重试路径
# ===========================================================================


def test_non_retryable_status_raises_at_once_with_kind(monkeypatch):
    """401 重试没有意义 —— 必须只试一次就抛，并带上 kind。"""
    client = _client()
    calls: list[int] = []

    def fake_post(path, payload):
        calls.append(1)
        return _FakeResponse(401, '{"error":"invalid api key"}')

    monkeypatch.setattr(client, "_post", fake_post)

    with pytest.raises(LLMError) as ei:
        client._call("/chat/completions", {})
    assert ei.value.kind == "auth"
    assert ei.value.status == 401
    assert len(calls) == 1


def test_exhausted_retries_keep_the_last_reason(monkeypatch, no_sleep):
    """★ 最要紧的一条。

    重试耗尽是一个**跨多次调用**的结论，上层必须知道"最后一次到底为什么失败" ——
    否则它没法决定是切备选模型、还是让用户换 Key。
    """
    client = _client(max_retries=3)
    seq = [500, 500, 429]
    seen: list[int] = []

    def fake_post(path, payload):
        status = seq[len(seen)]
        seen.append(status)
        return _FakeResponse(status, "boom")

    monkeypatch.setattr(client, "_post", fake_post)

    with pytest.raises(LLMError) as ei:
        client._call("/chat/completions", {})

    assert seen == [500, 500, 429]
    assert ei.value.kind == "rate_limit"    # 最后一次是限流，不是第一次的 500
    assert ei.value.status == 429


def test_connection_failure_is_network(monkeypatch, no_sleep):
    """连接失败 = 压根没收到响应，所以没有状态码。"""
    client = _client(max_retries=2)

    def fake_post(path, payload):
        raise requests.ConnectionError("connection reset by peer")

    monkeypatch.setattr(client, "_post", fake_post)

    with pytest.raises(LLMError) as ei:
        client._call("/chat/completions", {})
    assert ei.value.kind == "network"
    assert ei.value.status is None


def test_retry_then_success_returns_normally(monkeypatch, no_sleep):
    """抖一下就好了 —— 重试要真的能救回来（别把成功路径改坏了）。"""
    client = _client(max_retries=3)
    seq = [500, 200]
    seen: list[int] = []

    def fake_post(path, payload):
        status = seq[len(seen)]
        seen.append(status)
        if status == 200:
            return _FakeResponse(
                200, "", {"choices": [{"message": {"content": "hi"}}], "usage": {}}
            )
        return _FakeResponse(status, "boom")

    monkeypatch.setattr(client, "_post", fake_post)

    reply = client.chat([{"role": "user", "content": "x"}])
    assert reply.content == "hi"
    assert seen == [500, 200]


def test_error_body_inside_http_200_is_classified(monkeypatch):
    """HTTP 200 却塞了 error 体 —— 平台偶发。没有状态码可依据，只能看文案。"""
    client = _client()
    with pytest.raises(LLMError) as ei:
        client._parse({"error": {"message": "Invalid API key"}})
    assert ei.value.kind == "auth"


def test_error_body_without_hints_is_other(monkeypatch):
    client = _client()
    with pytest.raises(LLMError) as ei:
        client._parse({"error": {"message": "something odd happened"}})
    assert ei.value.kind == "other"


# ===========================================================================
# 本地端点不走代理
# ===========================================================================


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://127.0.0.1/v1", True),
        ("http://0.0.0.0:11434/v1", True),
        ("http://[::1]:11434/v1", True),
        ("https://open.bigmodel.cn/api/paas/v4", False),
        ("https://api.deepseek.com/v1", False),
        # 域名里带 localhost 但其实是外网地址 —— 不能误判
        ("https://localhost.evil.example.com/v1", False),
    ],
)
def test_is_local_url(url, expected):
    assert llm_mod.is_local_url(url) is expected


def test_local_url_disables_proxies():
    """★ 实测踩到的：本机设了 HTTP_PROXY 时，连本地 Ollama 的请求会被发给代理，
    代理连不上就回 HTTP 502 —— 看着像服务端故障，其实本地服务压根没起来。"""
    assert llm_mod.proxy_config_for("http://localhost:11434/v1") == {
        "http": None,
        "https": None,
    }
    assert llm_mod.proxy_config_for("https://api.deepseek.com/v1") is None


def test_proxy_choice_really_reaches_requests(monkeypatch):
    """光有判断函数不算数 —— 得确认它真的传进了 requests.post。"""
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured.clear()
        captured.update(kwargs)
        return _FakeResponse(
            200, "", {"choices": [{"message": {"content": "hi"}}], "usage": {}}
        )

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)

    local = LLMClient(
        api_key="k", model="m", base_url="http://localhost:11434/v1", verbose=False
    )
    local.chat([{"role": "user", "content": "x"}])
    assert captured["proxies"] == {"http": None, "https": None}

    remote = LLMClient(
        api_key="k", model="m", base_url="https://api.deepseek.com/v1", verbose=False
    )
    remote.chat([{"role": "user", "content": "x"}])
    assert captured["proxies"] is None
