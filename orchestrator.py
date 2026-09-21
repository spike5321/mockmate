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

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from agent.candidate import CandidateSim  # noqa: E402
from agent.llm import DEFAULT_MODEL, LLMClient, LLMError  # noqa: E402
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


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run_interview(
    scenario_id: str,
    answers_path: Path,
    max_turns: int,
    model: str,
    verbose: bool = True,
) -> dict:
    api_key = os.environ.get("ZHIPU_API_KEY", "")
    llm = LLMClient(api_key=api_key, model=model, verbose=verbose)
    toolbox = ToolBox(scenario_id)
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

    if verbose:
        banner(f"MockMate 自研调度循环 · 场景 {scenario_id} · 模型 {model}")
        print("  规则：模型自主决定下一步做什么，循环由它来终止\n")

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
            print(f"\n!! LLM 调用失败，循环中止：{error}")
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
                    log(turn, "🔧", f"调用 {name}({clip(arg_hint, 80)}) → {flag}")

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
            continue

        # ---- ③ 分支 B：模型只是在说话 ----
        spoken = (reply.content or "").strip()
        if verbose and spoken:
            print(f"       💬 面试官：{clip(spoken, 300)}")

        if toolbox.finished:
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

    summary = toolbox.summary()
    summary.update(
        {
            "turns": turn,
            "elapsed_sec": round(elapsed, 1),
            "llm_calls": llm.total_calls,
            "prompt_tokens": llm.total_prompt_tokens,
            "completion_tokens": llm.total_completion_tokens,
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
        print(f"  结束原因        : {summary['finish_reason']}")
        print(f"  报告            : {summary['report_path']}")
        print(f"  耗时            : {summary['elapsed_sec']}s")
        print(f"  LLM 调用 / token: {summary['llm_calls']} 次, "
              f"{summary['prompt_tokens']} in + {summary['completion_tokens']} out")
        print(f"  决策轨迹        : {trace_file}")
        if not toolbox.report_path:
            print("\n  ⚠️  模型结束了面试但没有提交报告（没调 submit_report）")

    return summary


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="MockMate 自研 Agent 调度循环")
    parser.add_argument("--scenario", default="backend_intern", help="场景 ID")
    parser.add_argument("--max-turns", type=int, default=30, help="最大轮数（保险丝）")
    parser.add_argument("--model", default=None, help="模型名，默认取 .env 里的 CHAT_MODEL")
    parser.add_argument("--quiet", action="store_true", help="只输出统计，不打过程")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    model = args.model or os.environ.get("CHAT_MODEL") or DEFAULT_MODEL
    answers_path = ROOT / "scenarios" / f"{args.scenario}.answers.json"
    if not answers_path.exists():
        print(f"找不到回答脚本：{answers_path}")
        return 2

    summary = run_interview(
        scenario_id=args.scenario,
        answers_path=answers_path,
        max_turns=args.max_turns,
        model=model,
        verbose=not args.quiet,
    )
    return 0 if summary.get("report_path") else 1


if __name__ == "__main__":
    raise SystemExit(main())
