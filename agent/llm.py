# -*- coding: utf-8 -*-
"""LLM 客户端 —— 只干一件事：把 messages 发出去，把回复拿回来。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么不用现成的 SDK？（这是本项目的第一个设计决定）

1. 智谱官方的 `zhipuai` SDK 有一个没写进依赖清单的隐形依赖 `sniffio`，
   装完 README 里的依赖直接 import 就崩（rag 项目已经踩过这个坑）。
2. 这一层总共几十行，用 requests 直接发 HTTP，你能亲眼看到
   "function calling" 在网络上到底长什么样子 —— 这是 Agent 开发的地基，
   盖在 SDK 后面的地基是学不到的。
3. 想换模型只改 base_url + model 两个值。DeepSeek、通义、本地 Ollama
   走的都是同一套 OpenAI 兼容协议，代码不用动。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

# 智谱的 OpenAI 兼容端点。换供应商就改这里。
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.5-flash"

# 向量化模型。知识库检索用它把文本和问题转成同维度的向量。
# embedding-3 输出 2048 维；换模型必须重建向量库（维度不同不能混用）。
DEFAULT_EMBEDDING_MODEL = "embedding-3"

# 这些状态码是"值得重试"的：限流 + 服务端临时故障
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 模型偶尔会把思维链的结束标签漏在正文里，长这样：
#   "好的，请开始你的回答。</think></think> 好的，请开始你的回答。……"
# 这是推理框架的产物，不该出现在对话正文中（会污染上下文、也难看）。
# 实测第一次跑就撞上了，所以在这里统一清掉。
_THINK_TAG = re.compile(r"</?(?:think|thinking|reasoning)\s*>", re.IGNORECASE)


def _clean_text(text: str | None) -> str | None:
    """去掉正文里混进来的思维链标签，并整理空白。"""
    if not text:
        return text
    cleaned = _THINK_TAG.sub("", text).strip()
    return cleaned or None


class LLMError(RuntimeError):
    """重试完仍然失败。"""


# ---------------------------------------------------------------------------
# 一次回复长什么样
# ---------------------------------------------------------------------------


@dataclass
class LLMReply:
    """模型的一次回复。

    这里最值得注意的是 as_message()：**不是所有字段都能回传给 API**。
    模型可能返回 reasoning_content（思考过程）之类的东西，
    把它们原样塞回 messages 会被接口拒绝 —— 这是新手最容易踩的坑之一。
    """

    content: str | None                 # 模型说的话（可能为空，比如纯工具调用）
    tool_calls: list[dict] = field(default_factory=list)   # 它想调哪些工具
    reasoning: str | None = None        # 思维链（如果有），只用于本地展示
    usage: dict = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)

    def as_message(self) -> dict:
        """整理成可以写回 messages 的 assistant 消息（只保留合法字段）。"""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 180,
        max_retries: int = 3,
        verbose: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("缺少 API Key。请把 .env.example 复制成 .env 并填入 ZHIPU_API_KEY")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.verbose = verbose

        # 累计用量，最后可以算这轮面试烧了多少 token
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0

    # -- 内部 ---------------------------------------------------------------

    def _post(self, path: str, payload: dict):
        return requests.post(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )

    def _call(self, path: str, payload: dict) -> dict:
        """带指数退避的请求，返回解析后的 JSON。

        对话和向量化共用这一套重试逻辑 —— 两个接口都会遇到限流和服务端抖动，
        没必要写两遍。
        """
        last_err = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._post(path, payload)
            except requests.RequestException as exc:
                last_err = f"网络异常: {exc}"
            else:
                if resp.status_code == 200:
                    return resp.json()
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in RETRYABLE_STATUS:
                    # 4xx 里除了限流，都是我们自己的问题，重试没意义
                    raise LLMError(last_err)

            if attempt < self.max_retries:
                wait = 2 ** (attempt - 1)          # 1s, 2s, 4s
                if self.verbose:
                    print(f"    [重试 {attempt}/{self.max_retries - 1}] {last_err} —— {wait}s 后再试")
                time.sleep(wait)

        raise LLMError(f"连续 {self.max_retries} 次失败，最后一次: {last_err}")

    # -- 对外 ---------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.3,
    ) -> LLMReply:
        """发一次对话请求。失败会按指数退避重试，重试完还不行才抛错。

        temperature 设得比较低（0.3）：面试流程需要稳定，
        不然同一个场景每次跑的题目和判断会飘得很厉害。
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"   # 让模型自己决定调不调工具

        return self._parse(self._call("/chat/completions", payload))

    def embed(
        self,
        texts: list[str],
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        batch_size: int = 32,
    ) -> list[list[float]]:
        """把文本批量转成向量 —— 知识库检索的地基。

        这里有个最容易漏的细节：**返回的向量顺序不保证和输入一致**，
        必须按返回体里的 index 字段排回来。抄示例代码时漏掉这一步，
        就会出现"第 3 段的向量被安到第 1 段上"——检索结果看着像随机命中，
        而且极难排查。

        batch_size 是因为接口对单次 input 数组长度有限制，一次塞太多会被拒。
        """
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            data = self._call("/embeddings", {"model": embedding_model, "input": batch})
            items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
            if len(items) != len(batch):
                raise LLMError(
                    f"向量化返回条数不匹配：请求 {len(batch)} 条，返回 {len(items)} 条"
                )
            vectors.extend(item["embedding"] for item in items)
        return vectors

    def _parse(self, data: dict) -> LLMReply:
        if "error" in data:
            raise LLMError(json.dumps(data["error"], ensure_ascii=False))

        choice = data["choices"][0]
        msg = choice["message"]

        usage = data.get("usage") or {}
        self.total_calls += 1
        self.total_prompt_tokens += usage.get("prompt_tokens", 0)
        self.total_completion_tokens += usage.get("completion_tokens", 0)

        return LLMReply(
            content=_clean_text(msg.get("content")),
            tool_calls=msg.get("tool_calls") or [],
            reasoning=msg.get("reasoning_content"),
            usage=usage,
        )
