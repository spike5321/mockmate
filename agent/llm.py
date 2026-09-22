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
from urllib.parse import urlparse

import requests

from agent.providers import DEFAULT_PROVIDER as _DEFAULT_PROVIDER_NAME
from agent.providers import PROVIDERS

# 默认端点与模型。**这两个值来自供应商注册表**，不在这里手写一份 ——
# 否则同一个 base_url 会在两个文件里各躺一遍，迟早对不上。
# 想换供应商不用改代码：用 LLMClient.from_provider()，或设 LLM_PROVIDER 环境变量。
_DEFAULT = PROVIDERS[_DEFAULT_PROVIDER_NAME]
DEFAULT_BASE_URL = _DEFAULT.base_url
DEFAULT_MODEL = _DEFAULT.models[0]

# 向量化模型。知识库检索用它把文本和问题转成同维度的向量。
# embedding-3 输出 2048 维；换模型必须重建向量库（维度不同不能混用）。
DEFAULT_EMBEDDING_MODEL = "embedding-3"

# 这些状态码是"值得重试"的：限流 + 服务端临时故障
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 指向本机的地址一律绕过系统代理。
#
# ★ 实测踩到的：本机设了 HTTP_PROXY 时，连 http://localhost:11434（本地 Ollama）
#   的请求会被发给代理，代理连不上就回一个 **HTTP 502** ——
#   界面上看着像"服务端故障"，让人以为是模型那边的问题，
#   其实只是本地服务没起来。本地端点绕过代理才是对的。
_LOCAL_HOSTS = {"localhost", "0.0.0.0", "::1"}


def is_local_url(url: str) -> bool:
    """这个地址是不是指向本机？"""
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.startswith("127.")


def proxy_config_for(url: str) -> dict | None:
    """本地地址返回「禁用代理」，其余返回 None（交给 requests 按环境变量决定）。"""
    if is_local_url(url):
        return {"http": None, "https": None}
    return None

# 每类错误的重试基数（秒），退避时长 = 基数 × 2^(已重试次数)。
#
# ★ 429 必须单独给一个大基数，不能和别的错误共用一套退避。
#   服务端的限流窗口通常按**分钟**计，而 1s/2s/4s 这种"礼貌性重试"
#   根本等不到窗口放开 —— 只会白白烧掉重试次数，然后报错退出。
#   实测连着跑了几轮面试后就是这样崩的：
#
#       [重试 1/2] HTTP 429: 您的账户已达到速率限制 —— 1s 后再试
#       [重试 2/2] HTTP 429: 您的账户已达到速率限制 —— 2s 后再试
#       !! LLM 调用失败，循环中止
#
#   整场面试（36 轮 ≈ 36 次调用）跑到第 5 轮就废了，而其实只需要多等一会儿。
#   这是"失败恢复"里最容易被忽略的一环：**退避时长要和故障的恢复周期匹配**，
#   重试得够勤但等得不够久，等于没重试。
RETRY_BASE = {
    429: 10,   # 限流：10s → 20s → 40s（配合 max_retries=4 总等待 70s）
    500: 3,
    502: 3,
    503: 3,
    504: 3,
}
DEFAULT_RETRY_BASE = 3


# ---------------------------------------------------------------------------
# 失败分类
#
# ★ 这一层只回答「为什么失败」，**不决定「怎么办」**。
#
# 为什么值得单独分一层：不同原因的应对方式完全不一样 ——
# 限流等一会儿就好；Key 错了等多久都没用；模型名不存在更是重试到死也白搭。
# 三者现在被压成同一句"调用失败"，上层就只能一刀切（目前正是一刀切：一律放弃）。
#
# 分类规则只有这一份（这里），策略在上层（orchestrator 的失败升级阶梯），
# 两边可以各自独立地改：加一个种类不用动策略，改策略也不用回来动分类。
# ---------------------------------------------------------------------------

ERROR_KINDS = ("rate_limit", "auth", "model_missing", "network", "server", "other")

# 状态码 → 种类。有明确对应关系的先按状态码判。
_KIND_BY_STATUS = {
    429: "rate_limit",   # 智谱的限流就是 429（响应体里是 code=1305「该模型访问量过大」）
    401: "auth",
    403: "auth",
    404: "model_missing",
}


# 平台自己的错误码（响应体里的 error.code）。
#
# ★ 实测校准过：模型名写错时智谱返回的是
#       HTTP 400 {"error":{"code":"1211","message":"模型不存在，请检查模型代码。"}}
#   —— 状态码是 400（看着像"参数写错了"，其实含义明确得多），文案还是中文。
#   光靠状态码 + 英文关键词会把它判成 other。
#   **按数字判比按文案判可靠：文案会变、会翻译，错误码不会。**
_KIND_BY_PLATFORM_CODE = {
    "1211": "model_missing",   # 模型不存在，请检查模型代码
    "1305": "rate_limit",      # 该模型当前访问量过大（实测出现在 HTTP 429 里）
}


def _platform_code(body: str) -> str | None:
    """从响应体里抠出平台错误码，抠不到返回 None。"""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, dict) and err.get("code") is not None:
        return str(err["code"])
    if data.get("code") is not None:
        return str(data["code"])
    return None


def _classify_text(body: str) -> str:
    """最后一道兜底：只认**很窄**的几个关键词（中英都认）。

    刻意不做文本语义猜测 —— 把任意文案当分类依据太容易误判，
    而拿错策略比不分类更糟：把"Key 过期"当成"网络抖动"，
    就会一直重试到天荒地老。
    """
    low = (body or "").lower()
    if any(
        h in low
        for h in ("invalid api key", "unauthorized", "authentication failed", "令牌", "验证不正确")
    ):
        return "auth"
    if any(
        h in low
        for h in ("model not found", "model_not_found", "no such model", "模型不存在")
    ):
        return "model_missing"
    if any(h in low for h in ("rate limit", "too many requests", "访问量过大", "速率限制")):
        return "rate_limit"
    return "other"


def classify_error(status: int, body: str = "") -> str:
    """把一个**带 HTTP 状态码**的失败响应归类到 ERROR_KINDS。

    三级判断，从最可靠往下走：
      ① 平台错误码  —— 最准，不受状态码语义和文案语言影响
      ② HTTP 状态码 —— 通用规则（429 限流 / 401·403 认证 / 404 / 5xx）
      ③ 文案关键词  —— 兜底，中英都认

    连接失败（压根没收到响应）不走这里 —— 那种情况调用方直接判 network，
    因为没有状态码可依据。
    """
    code = _platform_code(body)
    if code is not None and code in _KIND_BY_PLATFORM_CODE:
        return _KIND_BY_PLATFORM_CODE[code]

    if status in _KIND_BY_STATUS:
        return _KIND_BY_STATUS[status]
    if 500 <= status < 600:
        return "server"
    return _classify_text(body)


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
    """一次调用最终失败了。

    kind 是给上层做决策用的（取值见 ERROR_KINDS）——
    限流可以等、Key 错了只能换、模型名不存在则重试没有意义。
    底层只负责标清楚是哪一类，**不替上层决定怎么办**。
    """

    def __init__(
        self,
        message: str,
        kind: str = "other",
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status   # HTTP 状态码；连接失败时为 None


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
        # 4 次 = 3 次重试。配合 RETRY_BASE[429]=10，撞限流时总等待 10+20+40=70s，
        # 刚好能覆盖一次分钟级的限流窗口。设成 3 次（总等待 30s）实测不够。
        max_retries: int = 4,
        verbose: bool = True,
    ) -> None:
        if not api_key:
            # 用 LLMError 而不是 ValueError：这本质上就是"认证失败"。
            # 对上层来说，「没配 Key」和「Key 过期了」是同一件事 —— 都得让用户去改配置，
            # 所以它们该是同一个 kind，而不是两种异常类型。
            #
            # ★ 文案里不写死某一家：这个类现在能接任何 OpenAI 兼容端点，
            #   对一个只有 DeepSeek Key 的人说"请填入 ZHIPU_API_KEY"是纯粹的误导。
            #   （正常路径走 from_provider()，那边会给出带供应商名的具体提示；
            #    能走到这里的是直接构造的场景，所以说通用一点。）
            raise LLMError(
                "缺少 API Key —— 请在 .env 里配好对应供应商的 Key"
                "（ZHIPU_API_KEY / DEEPSEEK_API_KEY / OLLAMA_API_KEY……），"
                "或者用 LLM_API_KEY 指定。",
                kind="auth",
            )
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

    @classmethod
    def from_provider(
        cls,
        model: str | None = None,
        provider: str | None = None,
        **kwargs,
    ) -> LLMClient:
        """按供应商注册表解析出端点与 Key，再建客户端。

        上层只说"我要用哪个模型"，不必知道它属于哪家、Key 存在哪个环境变量里。
        providers 在函数里导入：依赖方向（llm → providers，反向不成立）
        这样在文件里一眼可见。
        """
        from agent.providers import resolve

        endpoint = resolve(model=model, provider=provider)
        return cls(
            api_key=endpoint.api_key,
            model=endpoint.model,
            base_url=endpoint.base_url,
            **kwargs,
        )

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
            # 本地端点（Ollama 之类）不走代理，原因见 _LOCAL_HOSTS 上面那段
            proxies=proxy_config_for(self.base_url),
        )

    def _call(self, path: str, payload: dict) -> dict:
        """带指数退避的请求，返回解析后的 JSON。

        对话和向量化共用这一套重试逻辑 —— 两个接口都会遇到限流和服务端抖动，
        没必要写两遍。
        """
        last_err = ""
        last_kind = "other"
        last_status: int | None = None

        for attempt in range(1, self.max_retries + 1):
            retry_base = DEFAULT_RETRY_BASE
            try:
                resp = self._post(path, payload)
            except requests.RequestException as exc:
                # 连接失败 = 压根没收到响应，没有状态码可依据，直接判 network
                last_err = f"网络异常: {exc}"
                last_kind, last_status = "network", None
            else:
                if resp.status_code == 200:
                    return resp.json()
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                last_kind = classify_error(resp.status_code, resp.text)
                last_status = resp.status_code
                if resp.status_code not in RETRYABLE_STATUS:
                    # 4xx 里除了限流，都是我们自己的问题，重试没意义
                    raise LLMError(last_err, kind=last_kind, status=last_status)
                # 限流这类故障恢复得慢，退避要长一点（见 RETRY_BASE 的注释）
                retry_base = RETRY_BASE.get(resp.status_code, DEFAULT_RETRY_BASE)

            if attempt < self.max_retries:
                wait = retry_base * (2 ** (attempt - 1))
                if self.verbose:
                    print(f"    [重试 {attempt}/{self.max_retries - 1}] {last_err} —— {wait}s 后再试")
                time.sleep(wait)

        # ★ 重试耗尽时，kind 必须保留**最后一次失败的原因**，不能丢。
        #   上层的失败升级阶梯就靠它决定下一步：切备选模型、让用户换 Key、
        #   还是直接放弃出报告。丢掉它，上层就只剩"失败了"这一条信息。
        raise LLMError(
            f"连续 {self.max_retries} 次失败，最后一次: {last_err}",
            kind=last_kind,
            status=last_status,
        )

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
            # HTTP 200 却塞了个 error 体：少见，但平台偶发。
            # 此时没有状态码可依据，只能看文案，判不出来就是 other。
            text = json.dumps(data["error"], ensure_ascii=False)
            raise LLMError(text, kind=_classify_text(text))

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
