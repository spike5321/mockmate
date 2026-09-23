# -*- coding: utf-8 -*-
"""供应商注册表 —— 模型名、端点、Key 从哪个环境变量取，都收在这一张表里。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么要单独一层？

改造前，`base_url` 和 `model` 是 `llm.py` 顶部的两个常量，想换供应商得改代码；
而 `LLMClient.__init__` 又硬要求 `ZHIPU_API_KEY` —— 于是"换一家"这件事
在代码里根本没有表达方式，用户只能去翻源码。

现在「模型名 → 供应商 → 端点 + Key 环境变量」的对应关系都在这里。
上层只说"我要用哪个模型"，不用关心它属于哪家、Key 存在哪个变量里。

★ Key 的纪律（这条不能破，破了就是事故）：
    Key 只从环境变量读（或由调用方临时传进来）、只活在内存里，
    **绝不落盘、绝不进 trace、绝不打进日志**。
    因为 trace 和报告是要提交进仓库、还要贴给别人看的。
    本模块只有读，没有任何写入接口 —— 临时凭据也不例外。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ProviderError(RuntimeError):
    """供应商配置有问题 —— 名称不认识、Key 没配、模型名没给。

    和 LLMError 分开：那个是"请求发出去了、失败了"，
    这个是"还没出发就发现配置不对"。两者该给的提示、该走的流程都不一样。
    """


@dataclass(frozen=True)
class Provider:
    """一家供应商的静态信息。"""

    name: str
    base_url: str
    api_key_env: str
    models: tuple[str, ...] = ()
    supports_tools: bool = True
    key_optional: bool = False   # 本地模型（Ollama）不需要 Key
    note: str = ""


# ---------------------------------------------------------------------------
# 注册表
#
# 只收录验证过的。想接别的 OpenAI 兼容端点，不用改这里 ——
# 设 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 三个环境变量就能覆盖（见 resolve）。
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, Provider] = {
    "zhipu": Provider(
        name="zhipu",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="ZHIPU_API_KEY",
        models=("glm-4.5-flash", "glm-4.5-air", "glm-4-flash", "glm-4-flash-250414"),
        note="默认。国内直连，有免费额度（高峰期会被平台限流）。",
    ),
    "deepseek": Provider(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        models=("deepseek-flash", "deepseek-chat"),
        note="OpenAI 兼容端点。",
    ),
    "qwen": Provider(
        name="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        models=("qwen3.5-flash",),
        note="阿里云百炼华北2（北京）OpenAI 兼容端点；免费额度与计费以控制台为准。",
    ),
    "ollama": Provider(
        name="ollama",
        base_url="http://localhost:11434/v1",
        api_key_env="OLLAMA_API_KEY",
        models=("qwen2.5:7b", "llama3.1:8b"),
        key_optional=True,
        note="本地模型，不用花钱也不用联网。需要自己先装 Ollama 并拉好模型。",
    ),
}

DEFAULT_PROVIDER = "zhipu"

# 通用覆盖项：任何 OpenAI 兼容端点都能用这三个变量接进来
ENV_BASE_URL = "LLM_BASE_URL"
ENV_API_KEY = "LLM_API_KEY"
ENV_MODEL = "LLM_MODEL"
ENV_PROVIDER = "LLM_PROVIDER"


@dataclass(frozen=True)
class Endpoint:
    """一次调用真正需要的东西（Key 在里面，所以**不要**把它塞进 trace）。"""

    provider: str
    base_url: str
    api_key: str
    model: str
    supports_tools: bool

    def safe_repr(self) -> str:
        """能安全打印/落盘的描述 —— 没有 Key。"""
        return f"{self.provider} / {self.model} @ {self.base_url}"


def get(name: str) -> Provider:
    key = (name or "").strip().lower()
    if key not in PROVIDERS:
        raise ProviderError(
            f"不认识的供应商 {name!r}。可选：{', '.join(sorted(PROVIDERS))}"
            f"（也可以用 {ENV_BASE_URL} 直接接一个 OpenAI 兼容端点）"
        )
    return PROVIDERS[key]


def guess_provider(model: str | None) -> str:
    """按模型名反查它属于哪家；查不到就用默认的。

    这样 `--model deepseek-flash` 能自己找到端点，不用每次都写 --provider。
    """
    if model:
        for provider in PROVIDERS.values():
            if model in provider.models:
                return provider.name
    return DEFAULT_PROVIDER


def resolve(
    model: str | None = None,
    provider: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Endpoint:
    """把「模型名 / 供应商名」解析成一次调用真正需要的东西。

    优先级：显式参数 > 环境变量 > 注册表默认值。

    `base_url` / `api_key` 两个显式参数是给**临时凭据**用的（Web 界面里那个输入框）。
    ★ 它们和从环境变量读到的 Key 是同一种东西：**只活在内存里**。
      本模块只读不写 —— 不落盘、不进 trace、不进断点，也不进日志。
      （端点要打印时用 `Endpoint.safe_repr()`，那个方法不含 Key。）
    """
    env = os.environ
    name = (provider or "").strip().lower() or env.get(ENV_PROVIDER, "").strip().lower()
    target = get(name) if name else get(guess_provider(model))

    # 模型名：显式 > 环境变量 > 该供应商列表里的第一个
    resolved_model = (model or "").strip() or env.get(ENV_MODEL, "").strip()
    if not resolved_model:
        if not target.models:
            raise ProviderError(
                f"没给模型名，且 {target.name} 的默认列表是空的 —— 请用 --model 指定"
            )
        resolved_model = target.models[0]

    # 端点：显式 > 通用环境变量 > 该供应商的默认端点
    resolved_base = (
        (base_url or "").strip()
        or env.get(ENV_BASE_URL, "")
        or target.base_url
    ).rstrip("/")
    if not resolved_base:
        raise ProviderError(f"{target.name} 没有配置 base_url（可以设 {ENV_BASE_URL}）")

    # Key：显式 > 通用环境变量 > 该供应商专属变量
    resolved_key = (
        (api_key or "").strip()
        or env.get(ENV_API_KEY, "")
        or env.get(target.api_key_env, "")
    )
    if not resolved_key:
        if not target.key_optional:
            # 建议里必须**排除当前这家** —— 第一版写死了 "deepseek / ollama"，
            # 结果在 deepseek 上失败时提示"或者换一家：--provider deepseek"，
            # 等于没说，还让人以为程序没搞清状况。
            others = " / ".join(
                f"--provider {name}" for name in sorted(PROVIDERS) if name != target.name
            )
            raise ProviderError(
                f"缺少 {target.api_key_env} —— 想用 {target.name} 就得先配上它。"
                f"或者换一家：{others}"
            )
        # 本地端点也会校验 Authorization 头非空，随便填一个占位符
        resolved_key = "local-no-key-needed"

    return Endpoint(
        provider=target.name,
        base_url=resolved_base,
        api_key=resolved_key,
        model=resolved_model,
        supports_tools=target.supports_tools,
    )


def describe_all() -> str:
    """给命令行用的表格：有哪些供应商、Key 配了没有。**不打印 Key 本身。**"""
    lines = []
    for provider in PROVIDERS.values():
        configured = bool(
            os.environ.get(ENV_API_KEY) or os.environ.get(provider.api_key_env)
        )
        if provider.key_optional:
            state = "不需要 Key"
        elif configured:
            state = "已配置"
        else:
            state = f"未配置（需要 {provider.api_key_env}）"
        lines.append(f"  {provider.name:<10} {state}")
        lines.append(f"             {provider.note}")
        if provider.models:
            lines.append(f"             典型模型：{', '.join(provider.models)}")
    return "\n".join(lines)
