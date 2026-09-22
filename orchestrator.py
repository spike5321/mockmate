# -*- coding: utf-8 -*-
"""MockMate 自研 Agent 调度循环（阶段 1 —— 这个项目的核心）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
读完这个文件，你就理解了绝大多数 Agent 框架内部在做的事。

整个 Agent 的本质就是下面这 4 步，转圈转到底：

    ① 把当前对话历史 + 工具说明书 发给大模型
    ② 模型要么「说话」，要么「要求调用某个工具」
    ③ 如果它要调工具 → 我们执行 → 把结果塞回对话历史 → 回到 ①
    ④ 如果它只是说话 → 那就是在跟用户交互 → 我们把用户的话接上 → 回到 ①

转圈什么时候停？由模型自己决定（它调用 end_interview 工具时）。
这就是所谓「自主性」：**停止条件不是我们写死的，是模型判断的。**

再加上两道保险：
  · max_turns —— 防止模型陷进死循环，把 API 额度烧光
  · 工具失败不抛异常 —— 把错误信息当结果交回模型，让它自己改参数重试
    这两条就是 JD 里常写的「失败恢复」。

运行方式：
    python orchestrator.py --scenario backend_intern
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from agent import checkpoint  # noqa: E402
from agent.candidate import CandidateSim  # noqa: E402
from agent.evaluator import AnswerEvaluator  # noqa: E402
from agent.llm import DEFAULT_MODEL, LLMClient, LLMError  # noqa: E402
from agent.providers import ProviderError, describe_all  # noqa: E402
from agent.prompts import build_system_prompt  # noqa: E402
from agent.tools import TOOL_SCHEMAS, ToolBox  # noqa: E402

LINE = "─" * 72


# ---------------------------------------------------------------------------
# 输出辅助（纯粹为了好看，跟 Agent 逻辑无关）
# ---------------------------------------------------------------------------


def banner(text: str) -> None:
    print(f"\n{LINE}\n  {text}\n{LINE}")


def clip(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + " …"


def log(turn: int, icon: str, text: str) -> None:
    print(f"[{turn:02d}] {icon} {text}")


def score_hint(payload: dict) -> str:
    """评分工具的结果里带分数时，把它缀在日志行尾。

    没有这个的话，日志上只有「调用 score_answer(...) → OK」，
    分数要等报告落盘才知道 —— 而「这一分是怎么来的」恰恰是这一阶段
    最需要盯的东西。顺带把 judge 也标出来（LLM 还是规则降级）。
    """
    if not isinstance(payload, dict) or "score" not in payload:
        return ""
    who = "LLM" if payload.get("source") == "llm" else "规则降级"
    return f" [{who} {payload['score']}/10]"



# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 失败升级阶梯（阶段 5）
#
# 模型罢工时，原来只有一条路：重试 4 次 → 放弃 → 出一份残缺报告。
# 现在往中间补两级：
#   ② 自动换备选模型（配了 FALLBACK_MODEL 才生效，不用人守着）
#   ③ 停下来问用户：等一会儿 / 换模型 / 改 Key / 放弃
# 而且无论走哪条，都已经有断点兜着（agent/checkpoint.py）——
# 所以"放弃"不再等于"白跑"，这正是把断点排在问人前面的原因。
# ---------------------------------------------------------------------------

#: 这些原因换模型也没用 —— Key 错了，换哪家都是同一个 Key。
_NO_AUTO_SWITCH = {"auth"}

#: 把 kind 翻译成一句人话。菜单里显示的是这句，不是那个英文单词。
_KIND_HINTS = {
    "rate_limit": "被平台限流了（该模型访问量过大）",
    "auth": "API Key 有问题（没配 / 写错了 / 过期了）",
    "model_missing": "模型名不存在，或者这个模型你没开通",
    "network": "连不上（本地服务没起 / 网络断了 / 被代理拦了）",
    "server": "对面服务端故障",
    "other": "没看出具体原因",
}

#: 「等一会儿再试」等多久。限流窗口通常按分钟计，等太短等于没等。
RETRY_WAIT_SEC = 60


def _alternative_models(current_model: str, limit: int = 3) -> list[str]:
    """同一家供应商里还能换哪些模型。

    只列**同一家**的 —— 模型名跨供应商不通用，把别家的名字列出来是害人：
    用户选了它，下一轮只会再收到一个"模型不存在"。

    ★ 模型名不在注册表里时返回空，**不退回默认供应商的模型列表**。
      那种情况要么是他自建了端点（列出来的名字在那边根本不存在），
      要么是名字拼错了 —— 不管哪种，"给你列一堆别的模型"都不是好建议。
      （`providers.resolve()` 里也有一处按名字猜供应商，但那是为了**建连接**，
        猜错了顶多是连不上、语义明确；这里是**给人做推荐**，猜错的代价是被误导。）
    """
    from agent.providers import PROVIDERS

    provider = next((p for p in PROVIDERS.values() if current_model in p.models), None)
    if provider is None:
        return []
    return [m for m in provider.models if m != current_model][:limit]


def should_auto_switch(kind: str, fallback_model: str | None, current_model: str) -> bool:
    """这个失败值不值得「悄悄换一个模型接着跑」。

    自动切换是不问人的，所以门槛要高一点：
      - Key 类问题换模型没用（同一个 Key，换谁都一样）
      - 没配备选、或者备选就是当前这个，那也没得换
    """
    if kind in _NO_AUTO_SWITCH:
        return False
    if not fallback_model:
        return False
    return fallback_model != current_model


def ask_what_to_do(
    kind: str,
    error: str,
    current_model: str,
    alternatives: list[str],
    ask: Callable[[str], str] | None = None,
) -> str:
    """失败升级的第三级：把选择权交给用户。

    返回 "retry" / "model:<名字>" / "fix_key" / "give_up"。

    ★ 读不到输入时（管道里跑、CI 里跑、后台跑）一律按「放弃」处理 ——
      一个给人评审用的项目，绝不能因为"在等人敲键盘"就永久挂在那儿。

    `ask` 默认在**运行时**取内置 input（而不是写成 `ask=input`）——
      写成默认参数的话，它在函数定义那一刻就绑死了，
      脚本想替换输入源（自动验证、测试）就换不掉。
    """
    ask = ask or input
    print()
    print(LINE)
    print(f"  面试卡住了 —— {_KIND_HINTS.get(kind, kind)}")
    print(f"  {clip(error, 200)}")
    print(LINE)

    options: list[tuple[str, str]] = [("1", "retry")]
    for index, name in enumerate(alternatives, start=2):
        options.append((str(index), f"model:{name}"))
    base = 2 + len(alternatives)
    options.append((str(base), "fix_key"))
    options.append((str(base + 1), "give_up"))
    give_up_key = str(base + 1)

    print("  怎么办？")
    for key, action in options:
        if action == "retry":
            print(f"    {key}) 等 {RETRY_WAIT_SEC} 秒再试一次")
        elif action == "fix_key":
            print(f"    {key}) 我去改 .env 里的 Key，改完回来重试")
        elif action == "give_up":
            print(f"    {key}) 放弃，用已完成的记录出一份不完整的报告")
        else:
            print(f"    {key}) 换成 {action.split(':', 1)[1]} 继续")
    print()

    try:
        raw = ask(f"  选择（直接回车 = {give_up_key} 放弃）: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  （读不到输入 —— 按「放弃」处理）")
        return "give_up"

    for key, action in options:
        if raw == key:
            return action
    return "give_up"


def _restore_from_checkpoint(
    state: dict,
    toolbox: ToolBox,
    candidate: CandidateSim,
    messages: list[dict],
    trace: list[dict],
) -> None:
    """把断点里的状态灌回各个对象。

    ★ messages 是**原样**灌回去的：每条的 tool_calls 和 tool_call_id 都不能动。
      模型看到的是一串"我说要调 X → 工具返回 Y"的记录，恢复时要是把 id
      弄丢或者重新编一个，下一轮请求会因为"tool 消息对不上"被接口直接拒绝。
      所以这里只做搬运，不裁剪、不重排、不补字段。
    """
    toolbox.load_state(state.get("toolbox") or {})
    candidate.load_state(state.get("candidate") or {})

    saved_messages = state.get("messages")
    if saved_messages:
        messages.clear()
        messages.extend(saved_messages)

    trace.clear()
    trace.extend(state.get("trace") or [])


def run_interview(
    scenario_id: str,
    answers_path: Path,
    max_turns: int,
    model: str,
    verbose: bool = True,
    use_llm_score: bool = True,
    score_model: str | None = None,
    provider: str | None = None,
    resume_state: dict | None = None,
    fallback_model: str | None = None,
    interactive: bool = True,
) -> dict:
    # 端点和 Key 都交给供应商注册表解析 —— 这一层不该知道
    # "Key 存在 ZHIPU_API_KEY 里"这种细节，那是 providers.py 的知识。
    llm = LLMClient.from_provider(model=model, provider=provider, verbose=verbose)

    # 换过模型之后，老客户端的用量要结转过来 —— 否则统计里只看得见"最后那个模型"
    # 烧了多少，前面几次调用凭空消失。而这个数字是要写进报告的，不能偏。
    usage = {"calls": 0, "prompt": 0, "completion": 0}

    # 评分器是一个**独立的客户端**，不是复用面试官那个。两个理由：
    #
    # ① **重试策略该不一样。** 面试官的重试是"必须成功"（整场对话不能断），
    #    而评分失败可以降级成规则打分 —— 让它跟着面试官一起重试 4 次
    #    （429 时总计 70 秒），等于拿整场面试去赌一道题的分。
    #    run12 就是这么废掉的：一次评分限流，白卡 70 秒，后面整场跟着崩。
    # ② **模型可以不同。** SCORE_MODEL 允许评分单独换模型 ——
    #    既能错开限流（智谱的 429 是按"模型"报的：「**该模型**访问量过大」），
    #    也让「出题的」和「判卷的」不再是同一个模型，评分视角更独立。
    judge: LLMClient | None = None
    if use_llm_score:
        # 评分客户端也走注册表，但**不继承主 provider** ——
        # SCORE_MODEL 可能属于另一家，让它按模型名自己判断更准。
        judge = LLMClient.from_provider(
            model=score_model or model,
            verbose=verbose,
            max_retries=2,   # 10s + 20s 之后就放弃，快速降级
        )

    evaluator = AnswerEvaluator(
        llm=judge, verbose=verbose, use_llm=use_llm_score, scenario_id=scenario_id
    )
    toolbox = ToolBox(scenario_id, evaluator=evaluator)
    candidate = CandidateSim(json.loads(answers_path.read_text(encoding="utf-8")))

    # --- 对话历史。这是 Agent 唯一的"记忆"，每一轮都整份发回给模型 ---
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(scenario_id)},
        {
            "role": "user",
            "content": (
                f"开始面试。scenario_id={scenario_id}。"
                "候选人已经就座，请按流程推进：先看简历和岗位要求，然后依次进行技术面和 HR 面。"
            ),
        },
    ]

    trace: list[dict] = []
    started = time.time()
    turn = 0
    error: str | None = None
    nod_streak = 0   # 连续几轮没能给出答案（防死循环保险丝，详见分支 B 的注释）
    nudged = False   # 是否已经提醒过模型"该交报告了"

    # --- 断点：这场面试的身份证，以及「从哪儿接着跑」---
    run_id = checkpoint.new_run_id()
    elapsed_before = 0.0                      # 中断前已经花掉的时间，统计时要加上
    interrupted_record: dict | None = None    # 本次中断的原因，会写进断点

    if resume_state:
        run_id = resume_state.get("run_id") or run_id
        elapsed_before = float(resume_state.get("elapsed") or 0.0)
        _restore_from_checkpoint(resume_state, toolbox, candidate, messages, trace)
        turn = int(resume_state.get("turn") or 0)

        previous = resume_state.get("interrupted") or {}
        if previous:
            # ★ 这件事必须写进报告。一场跑得磕磕绊绊的面试，如果报告里不标出来，
            #   读的人会以为它是一口气跑完的 —— 那这份报告的可信度就说不清了。
            toolbox.notes.append(
                f"第 {previous.get('turn')} 轮中断（{previous.get('reason')}），"
                f"之后从断点续跑，第 {turn} 轮起继续"
            )

        previous_model = resume_state.get("model")
        if previous_model and previous_model != model:
            # 换模型本身没问题，**悄悄换了**才有问题：不同模型遵守 function calling
            # 的程度差很远（run13 的教训），不标出来这份报告就没人敢信。
            toolbox.notes.append(
                f"第 {turn} 轮起，面试官模型从 {previous_model} 换成了 {model}"
            )
        if verbose:
            print(f"  ↻ 从断点续跑：{run_id}，已完成 {turn} 轮，接着往下问\n")

    def _state() -> dict:
        """当前进度的完整快照。"""
        return {
            "scenario_id": scenario_id,
            "answers_file": answers_path.name,
            "turn": turn,
            "messages": messages,
            "trace": trace,
            "toolbox": toolbox.dump_state(),
            "candidate": candidate.dump_state(),
            "model": model,
            "provider": provider,
            "elapsed": round(elapsed_before + (time.time() - started), 1),
            "interrupted": interrupted_record,
        }

    def _snapshot(reason: str | None = None) -> None:
        """把进度落盘。传了 reason 就表示"这是一次中断"。

        ★ 只在正常路径上存是不够的 —— 断点文件最该被写出来的时刻，
          恰恰是出故障的那一刻。所以循环里每个出口都得调一次。
        """
        nonlocal interrupted_record
        if reason:
            interrupted_record = {"turn": turn, "reason": clip(reason, 160)}
        checkpoint.save(run_id, _state())

    def _rebuild_client(note: str, new_model: str | None = None) -> None:
        """换模型 / 换完 Key 之后重建客户端，并把用量结转过去。"""
        nonlocal llm, model
        usage["calls"] += llm.total_calls
        usage["prompt"] += llm.total_prompt_tokens
        usage["completion"] += llm.total_completion_tokens

        if new_model:
            model = new_model
        llm = LLMClient.from_provider(model=model, provider=provider, verbose=verbose)

        toolbox.notes.append(note)
        if verbose:
            print(f"  ↻ {note}")

    def _clear_interrupt() -> None:
        """升级成功之后把"这是一次中断"的标记撤掉 —— 它已经不是中断了。"""
        nonlocal interrupted_record
        interrupted_record = None
        checkpoint.save(run_id, _state())

    def _escalate(exc: LLMError) -> bool:
        """失败升级阶梯。返回 True = 这一轮已经处理好了，可以接着跑。

        注意每一级处理的末尾都是 `turn -= 1`：**这一轮不算数**。
        模型换了、等了一会儿，对话本身并没有往前走过 —— 白占一轮预算不说，
        还会让"剩余轮数"提前缩水，反而把模型的节奏打乱。
        """
        nonlocal turn

        # ---- 第二级：自动换备选模型 ----
        if should_auto_switch(exc.kind, fallback_model, model):
            previous = model
            _rebuild_client(
                f"第 {turn} 轮遇到 {exc.kind}，自动把面试官从 {previous} "
                f"换成了 {fallback_model}",
                new_model=fallback_model,
            )
            turn -= 1
            return True

        # ---- 第三级：问人 ----
        if not interactive:
            print("  （--no-interactive：不询问，直接用已有记录出报告）")
            return False

        choice = ask_what_to_do(exc.kind, str(exc), model, _alternative_models(model))

        if choice == "retry":
            print(f"  等 {RETRY_WAIT_SEC} 秒再试……")
            time.sleep(RETRY_WAIT_SEC)
            turn -= 1
            return True

        if choice.startswith("model:"):
            picked = choice.split(":", 1)[1]
            _rebuild_client(
                f"第 {turn} 轮失败后，按你的选择把面试官换成了 {picked}",
                new_model=picked,
            )
            turn -= 1
            return True

        if choice == "fix_key":
            print("  改完 .env 后按回车继续（不用重启程序，Key 会重新读一遍）")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                return False
            # ★ Key 是建客户端时从环境变量读的，所以这里必须真的重新 load 一遍。
            #   不重新读的话，用户改完 .env 以为生效了，跑起来用的还是老值 ——
            #   那种"我明明改了"的困惑最难排查。
            load_dotenv(ROOT / ".env", override=True)
            _rebuild_client("按你的要求重新读取了 .env 里的 Key")
            turn -= 1
            return True

        return False   # give_up

    if verbose:
        banner(f"MockMate 自研调度循环 · 场景 {scenario_id} · 模型 {model}")
        print("  规则：模型自主决定下一步做什么，循环由它来终止")
        if not resume_state:
            print(f"  断点：中途出故障可以用 --resume {run_id} 接着跑")
        print()

    # =======================================================================
    # ★★★ 主循环 ★★★
    # =======================================================================
    while turn < max_turns and not toolbox.finished:
        turn += 1

        # ---- ⓪ 预算提醒：快聊完了还没交报告，就推它一把 ----
        # 模型没有"我已经聊了多少轮"的概念 —— 在它的视角里，对话就是一条
        # 一直往下延伸的历史，没有长度。前两次运行就是一路聊到撞上限，
        # 报告栏是空的（而报告才是这个产品真正的交付物）。
        # 所以由我们这一层告诉它剩余预算。这也算"失败恢复"的一种：
        # 与其等它撞墙，不如在墙前面提醒一次。
        remaining = max_turns - turn
        if 0 < remaining <= 3 and toolbox.report_path is None and not nudged:
            nudged = True
            messages.append(
                {
                    "role": "user",
                    "content": "（面试时间快到了）请立刻调用 submit_report 提交复盘报告，"
                               "然后调用 end_interview 结束面试。",
                }
            )
            if verbose:
                log(turn, "⏰", f"剩余 {remaining} 轮，模型还没交报告 —— 已提醒")

        # ---- ① 让模型做一次决策 ----
        try:
            reply = llm.chat(messages, tools=TOOL_SCHEMAS)
        except LLMError as exc:
            error = str(exc)
            print(f"\n!! 第 {turn} 轮 LLM 调用失败（{exc.kind}）：{clip(error, 200)}")

            # 先落盘、再升级：万一升级过程中程序被关掉，进度也不会丢
            _snapshot(f"LLM 调用失败（{exc.kind}）：{error}")

            if _escalate(exc):
                # 升级成功 —— 那就不是中断了，标记要撤掉，否则最后会误判成"没跑完"
                error = None
                _clear_interrupt()
                continue
            break

        # 思维链只用于本地展示，不能回传给 API
        if verbose and reply.reasoning:
            log(turn, "🧠", clip(reply.reasoning, 200))

        # 模型这一轮的发言写回历史（工具调用也必须原样带上，否则下一轮它会失去上下文）
        messages.append(reply.as_message())
        trace.append(
            {
                "turn": turn,
                "thinking": clip(reply.reasoning, 500),
                "content": clip(reply.content, 500),
                "tool_calls": [tc["function"]["name"] for tc in reply.tool_calls],
            }
        )

        # ---- ② 分支 A：模型要求调用工具 ----
        if reply.wants_tools:
            for call in reply.tool_calls:
                name = call["function"]["name"]
                raw_args = call["function"].get("arguments") or "{}"
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}

                ok, payload = toolbox.dispatch(name, args)

                flag = "OK " if ok else "ERR"
                arg_hint = ",".join(f"{k}={v}" for k, v in list(args.items())[:3])
                if verbose:
                    suffix = score_hint(payload) if name == "score_answer" else ""
                    log(turn, "🔧", f"调用 {name}({clip(arg_hint, 80)}) → {flag}{suffix}")

                # 工具结果塞回历史。失败也一样塞 —— 让模型知道发生了什么，
                # 它下一轮会自己决定要不要换个参数再来一次。
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                )
            # 调完工具直接进入下一轮，让模型看着结果继续决策
            _snapshot()
            continue

        # ---- ③ 分支 B：模型只是在说话 ----
        spoken = (reply.content or "").strip()
        if verbose and spoken:
            print(f"       💬 面试官：{clip(spoken, 300)}")

        if toolbox.finished:
            _snapshot()
            break

        # ────────────────────────────────────────────────────────────────
        # 判断它到底是在"对候选人提问"还是在"自言自语"。
        #
        # 第一版这里是「句子里带问号就算提问」，结果整场面试卡死了：
        # 面试官出题用的是"请实现……请说明……"这种祈使句，**一个问号都没有**，
        # 于是被判成自言自语 → 注入"候选人点了点头" → 面试官以为题没问出去
        # → 再问一遍 → 还是没问号 → 30 轮全在空转。
        #
        # 教训：**边界判断不能靠猜字符串，要靠状态。**
        # 现在改成三级判定，任何一级命中就给候选人回答的机会：
        #   1) 台上有待答题（pick_question 出过题）→ 必然是在提问
        #   2) 句子里有问号                        → 自由提问（项目深挖用）
        #   3) 连着两轮都没给出答案                 → 强制给，这是防死循环的保险丝
        # ────────────────────────────────────────────────────────────────
        looks_like_question = ("？" in spoken) or ("?" in spoken)
        should_answer = (
            toolbox.pending_question is not None   # ① 有题在台上
            or looks_like_question                 # ② 自由提问
            or nod_streak >= 1                     # ③ 第二轮还没答上 → 强制
        )

        if should_answer:
            # 台上有题就把题取走；台上没题说明这是**自由追问**（项目深挖之类），
            # 那就沿用上一道题的语境 —— 追问确实没有 question_id，
            # 但"刚刚问的是哪一类"这个上下文还在，候选人靠它选对应的话题池。
            question = toolbox.consume_pending() or toolbox.last_question
            # spoken 也要给它：自由追问有可能换话题（上一题问算法，
            # 这一句突然说"聊聊你的项目"），只有读到原话才判得出来。
            answer = candidate.answer_for(question, spoken=spoken)
            nod_streak = 0
            if verbose:
                print(f"       🙋 候选人：{clip(answer, 300)}")
            # ★ 前缀 [候选人回答] 不是装饰 —— 它是给模型看的角色路标。
            #   第一版直接把答案裸着塞进去，模型分不清"这是别人说的"还是
            #   "该我接着说了"，于是出现面试官替候选人做自我介绍的荒唐场面。
            #   加上明确标记后，模型才知道该自己说话还是等对方。
            messages.append({"role": "user", "content": f"[候选人回答] {answer}"})
        else:
            # 开场白、过渡语之类 —— 不要浪费脚本里的答案，轻轻推一下就好。
            # 但最多只推一次：下一轮如果模型还是不说话到点子上，
            # 上面第 ③ 条会强制给出答案，循环不会卡死。
            nod_streak += 1
            messages.append({"role": "user", "content": "（候选人点了点头，等你提问。）"})

    # =======================================================================
    # 循环结束，汇总
    # =======================================================================
    elapsed = time.time() - started

    if turn >= max_turns and not toolbox.finished:
        print(f"\n!! 达到最大轮数 {max_turns}，强制结束（模型没能自己收尾）")

    # 断点收尾：没有中断 = 跑完了，标一下，这样 --resume latest 不会挑到它。
    # 中断的情况故意不标 —— 断点得留着给用户续跑。
    if error is None:
        checkpoint.mark_completed(run_id, _state())
    else:
        print(f"\n  断点已保留：{checkpoint.path_for(run_id)}")
        print("  方便的时候可以接着跑 ——")
        print(f"      python -u orchestrator.py --scenario {scenario_id} --resume {run_id}")

    # ★ 兜底交付：循环因 API 故障中止时，用已有记录出一份「不完整但真实」的报告。
    #   run12 的经历：跑到第 17 轮撞限流，主循环 break，结果是 EXIT=1 + 报告为空，
    #   前面 7 分钟、3 道题的真实评分全丢了 —— 而它们恰恰是这场运行最有价值的产物。
    #   所以这里补一层：**宁可交一份残缺但真实的，也不要交一份空白。**
    if error is not None and toolbox.report_path is None:
        partial = toolbox.submit_partial_report(f"LLM 调用失败：{clip(error, 90)}")
        if partial:
            print(f"\n!! 面试中断，已用已完成的 {partial['graded']} 题生成部分报告：")
            print(f"   {partial['report_path']}")

    summary = toolbox.summary()
    judge_calls = judge.total_calls if judge else 0
    summary.update(
        {
            "turns": turn,
            "run_id": run_id,
            # 续跑时把中断前花掉的时间也算进来，否则"耗时"会只显示最后一段
            "elapsed_sec": round(elapsed_before + elapsed, 1),
            # usage 是"换过模型之前那些客户端"的累计 —— 不加它的话，
            # 中途换过模型的运行，统计里只看得见最后那个模型的调用次数。
            "llm_calls": usage["calls"] + llm.total_calls + judge_calls,
            "judge_calls": judge_calls,          # 其中评分调用占了几次
            "prompt_tokens": usage["prompt"]
            + llm.total_prompt_tokens
            + (judge.total_prompt_tokens if judge else 0),
            "completion_tokens": usage["completion"]
            + llm.total_completion_tokens
            + (judge.total_completion_tokens if judge else 0),
            "error": error,
        }
    )

    # 轨迹落盘，方便事后复盘"模型当时为什么这么决策"
    traces_dir = ROOT / "traces"
    traces_dir.mkdir(exist_ok=True)
    trace_file = traces_dir / f"{scenario_id}_{datetime.now():%Y%m%d_%H%M%S}.json"
    trace_file.write_text(
        json.dumps({"summary": summary, "trace": trace}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if verbose:
        banner("面试结束 · 运行统计")
        print(f"  轮数            : {summary['turns']}")
        print(f"  工具调用次数    : {summary['tool_calls']}")
        print(f"  出题数 / 评分数 : {summary['questions_asked']} / {summary['answers_scored']}")
        print(f"  平均分          : {summary['avg_score']}")
        llm_scored = summary.get("scored_by_llm", 0)
        rule_scored = summary.get("scored_by_rule", 0)
        print(f"  评分来源        : LLM {llm_scored} 题 / 规则降级 {rule_scored} 题")
        print(f"  结束原因        : {summary['finish_reason']}")
        print(f"  报告            : {summary['report_path']}")
        print(f"  耗时            : {summary['elapsed_sec']}s")
        print(f"  LLM 调用 / token: {summary['llm_calls']} 次"
              f"（其中评分 {summary.get('judge_calls', 0)} 次）, "
              f"{summary['prompt_tokens']} in + {summary['completion_tokens']} out")
        print(f"  决策轨迹        : {trace_file}")

        # 运行质量提示：一题都没通过 pick_question 出，说明模型没有走工具约定的路径
        # （run13 就是这样：全程自己编题、编 id，最后批量补交 13 个评分全部被拦）。
        # 这种运行**看起来是跑完了**（有轮数、有报告），但评分链路完全没生效 ——
        # 不提示的话很容易被当成一次成功，是最危险的那种失败。
        # 注意只说现象，不猜原因（也可能是提前中断导致根本没到出题环节）。
        if summary["questions_asked"] == 0:
            print("\n  ⚠️  整场面试没有通过 pick_question 出题，评分链路未生效")

        if not toolbox.report_path:
            print("\n  ⚠️  模型结束了面试但没有提交报告（没调 submit_report）")

    return summary


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MockMate 自研 Agent 调度循环",
        epilog="不确定有哪些供应商可用？加 --list-providers 看一眼。",
    )
    parser.add_argument("--scenario", default="backend_intern", help="场景 ID")
    parser.add_argument("--max-turns", type=int, default=30, help="最大轮数（保险丝）")
    parser.add_argument(
        "--provider",
        default=None,
        help="供应商：zhipu / deepseek / ollama。默认按模型名自动判断",
    )
    parser.add_argument("--model", default=None, help="模型名，默认取 .env 里的 CHAT_MODEL")
    parser.add_argument(
        "--score-model",
        default=None,
        help="评分模型，默认与面试官相同。可用来错开限流，或换更强的模型判分",
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="看看有哪些供应商、Key 配没配（不发起面试）",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="latest",
        default=None,
        metavar="RUN_ID",
        help="从断点续跑；不给值就接最近一个没跑完的",
    )
    parser.add_argument("--list-runs", action="store_true", help="列出本地的断点文件")
    parser.add_argument(
        "--fallback-model",
        default=None,
        help="模型罢工时自动换过去接着跑（默认取 .env 里的 FALLBACK_MODEL）",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="出故障时不问人，直接用已有记录出报告（无人值守时用）",
    )
    parser.add_argument("--quiet", action="store_true", help="只输出统计，不打过程")
    parser.add_argument(
        "--no-llm-score",
        action="store_true",
        help="用规则打分替代 LLM 评分（不额外调模型，适合调试流程时省额度）",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if args.list_providers:
        print("可用的供应商（Key 只读不打印）：")
        print(describe_all())
        return 0

    if args.list_runs:
        files = (
            sorted(checkpoint.RUNS_DIR.glob("*.checkpoint.json"))
            if checkpoint.RUNS_DIR.exists()
            else []
        )
        if not files:
            print(f"还没有断点文件（会放在 {checkpoint.RUNS_DIR}）。")
            return 0
        print(f"断点文件（{checkpoint.RUNS_DIR}）：")
        for path in files:
            print(checkpoint.describe(path.name[: -len(".checkpoint.json")]))
        return 0

    # --- 从断点续跑 ---
    resume_state: dict | None = None
    if args.resume:
        target = args.resume
        if target == "latest":
            target = checkpoint.latest_unfinished()
            if not target:
                print("没有找到没跑完的断点。用 --list-runs 可以看有哪些。")
                return 2
        try:
            resume_state = checkpoint.load(target)
        except (FileNotFoundError, ValueError) as exc:
            print(f"!! 读断点失败：{exc}")
            return 2

        saved_scenario = resume_state.get("scenario_id")
        if saved_scenario != args.scenario:
            # 场景对不上就别硬跑 —— 断点里的简历、题库、候选人脚本都是另一个场景的，
            # 混着跑出来的报告没法看；而且不报错的话用户根本不知道混了。
            print(
                f"!! 这个断点属于场景 {saved_scenario!r}，和 --scenario {args.scenario!r} 对不上。\n"
                f"   要么改用 --scenario {saved_scenario}，要么换一个断点。"
            )
            return 2

    model = args.model or os.environ.get("CHAT_MODEL") or DEFAULT_MODEL
    if resume_state and args.model is None and resume_state.get("model"):
        # 没显式指定就沿用上次那个模型。换模型本身没问题，
        # 但"悄悄换了"会让这份报告说不清 —— 所以要么不改，要么改了就写进报告。
        model = resume_state["model"]
    answers_path = ROOT / "scenarios" / f"{args.scenario}.answers.json"
    if not answers_path.exists():
        print(f"找不到回答脚本：{answers_path}")
        return 2

    try:
        summary = run_interview(
            scenario_id=args.scenario,
            answers_path=answers_path,
            max_turns=args.max_turns,
            model=model,
            verbose=not args.quiet,
            use_llm_score=not args.no_llm_score,
            score_model=args.score_model or os.environ.get("SCORE_MODEL") or None,
            provider=args.provider,
            resume_state=resume_state,
            fallback_model=args.fallback_model or os.environ.get("FALLBACK_MODEL") or None,
            interactive=not args.no_interactive,
        )
    except ProviderError as exc:
        # 配置期的问题（名字不认识 / Key 没配）要在开跑前拦下来。
        # 拖到面试中途才炸，用户已经白等一会儿了，而且那会儿报错更难懂。
        print(f"\n!! 供应商配置有问题：{exc}")
        print("   加 --list-providers 可以看当前有哪些可用。")
        return 2

    return 0 if summary.get("report_path") else 1


if __name__ == "__main__":
    raise SystemExit(main())
