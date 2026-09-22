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
) -> dict:
    # 端点和 Key 都交给供应商注册表解析 —— 这一层不该知道
    # "Key 存在 ZHIPU_API_KEY 里"这种细节，那是 providers.py 的知识。
    llm = LLMClient.from_provider(model=model, provider=provider, verbose=verbose)

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
            print(f"\n!! LLM 调用失败，循环中止：{error}")
            # 中断时也要留断点 —— 这正是最该把进度写下来的时刻。
            # 记上 kind，用户 --resume 之前能一眼看出上次是栽在哪一类问题上。
            _snapshot(f"LLM 调用失败（{exc.kind}）：{error}")
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
            "llm_calls": llm.total_calls + judge_calls,
            "judge_calls": judge_calls,          # 其中评分调用占了几次
            "prompt_tokens": llm.total_prompt_tokens
            + (judge.total_prompt_tokens if judge else 0),
            "completion_tokens": llm.total_completion_tokens
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
