# -*- coding: utf-8 -*-
"""MockMate Web 界面（阶段 6）。

启动：
    streamlit run app.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
这个页面为什么能"实时"看到面试过程？

    因为主循环的所有输出都走 `orchestrator.emit()` —— 这里把输出目标换成
    一个队列，页面从队列里取着往屏幕上刷。**不需要去重定向 sys.stdout。**

★ 两条纪律，都写在这里免得以后被人改掉：

  ① **Key 只在内存里。** 界面上填的临时 Key 不写 .env、不进断点、不进 trace。
     这条有回归测试钉着（tests/test_orchestrator.py::test_temp_key_never_reaches_disk）。

  ② **一律 interactive=False。** 网页里没有终端能敲键盘，主循环那套
     "停下来问用户怎么办"在这里会永久卡住。所以出故障时它直接出一份
     「不完整但真实」的报告，想接着跑就用下面的续跑按钮 ——
     这也正是断点（阶段 5 ③）在这里的用处。

★ 已知限制（不是 bug，是这一轮的范围）：同一时刻只支持一个人跑。
  `set_sink` 是模块级的，两个人同时点"开始"会互相抢输出。
  自己用的演示工具，先不引入会话隔离。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import orchestrator
from agent import checkpoint
from agent.llm import DEFAULT_MODEL
from agent.providers import PROVIDERS, describe_all, guess_provider
from tools.mock_tools import SCENARIOS_DIR

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

st.set_page_config(page_title="MockMate · 模拟面试", layout="wide")


# ---------------------------------------------------------------------------
# 环境探测（都是只读的，不碰任何东西）
# ---------------------------------------------------------------------------


def scenario_ids() -> list[str]:
    """scenarios/ 下有哪些场景。回答脚本和报告不算场景。"""
    return [
        path.stem
        for path in sorted(SCENARIOS_DIR.glob("*.json"))
        if not path.name.endswith((".answers.json", ".report.json"))
    ]


def all_models() -> list[str]:
    return [model for provider in PROVIDERS.values() for model in provider.models]


def unfinished_runs() -> list[str]:
    """本地有哪些没跑完的断点，新的排前面。"""
    if not checkpoint.RUNS_DIR.exists():
        return []
    names = [p.name[: -len(".checkpoint.json")] for p in checkpoint.RUNS_DIR.glob("*.checkpoint.json")]
    return sorted(names, reverse=True)


def kb_line() -> str:
    """向量库现状。没建库/没装依赖都不该让页面崩。"""
    try:
        from kb.search import kb_status

        info = kb_status()
        if not info["chunks"]:
            return "向量库是空的（检索会回退到场景自带的少量情报，不影响面试）"
        return f"{info['chunks']} 个片段 · 向量化 {info['current']}"
    except Exception as exc:  # noqa: BLE001
        return f"读不到向量库状态（{type(exc).__name__}: {exc}）"


# ---------------------------------------------------------------------------
# 把输出接进页面
# ---------------------------------------------------------------------------


def stream_run(**kwargs) -> dict:
    """跑一场面试，把 emit 的输出实时刷在页面上。

    返回 {"summary": ...} 或 {"error": ...}。

    做法：输出目标换成一个队列 → 后台线程跑面试 → 主线程边取边刷。
    面试跑在**后台线程**里是有意的：万一它卡住，页面至少还能响应一下。
    """
    box = st.empty()
    lines: list[str] = []
    pipe: queue.Queue[str | None] = queue.Queue()
    outcome: dict = {}

    orchestrator.set_sink(pipe.put)

    def worker() -> None:
        try:
            outcome["summary"] = orchestrator.run_interview(**kwargs)
        except BaseException as exc:  # noqa: BLE001
            # 连 BaseException 一起收：页面绝不能因为一个异常就整片白掉，
            # 那样用户看到的是"点了没反应"，比一条错误信息糟糕得多。
            outcome["error"] = exc
        finally:
            pipe.put(None)          # 结束信号

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    try:
        while True:
            item = pipe.get()
            if item is None:
                break
            lines.append(item)
            box.code("\n".join(lines), language=None)
    finally:
        # 无论怎么退出，都要把输出目标还给终端 —— 否则下一次跑（或命令行里跑）
        # 会静默地把输出丢进一个没人看的队列。
        orchestrator.set_sink(None)

    thread.join(timeout=5)
    return outcome


def show_summary(summary: dict) -> None:
    """运行统计。字段名和命令行那份报告是同一套（toolbox.summary()）。"""
    columns = st.columns(4)
    columns[0].metric("轮数", summary.get("turns", 0))
    columns[1].metric("工具调用", summary.get("tool_calls", 0))
    columns[2].metric("出题 / 评分", f"{summary.get('questions_asked', 0)} / {summary.get('answers_scored', 0)}")
    columns[3].metric("耗时", f"{summary.get('elapsed_sec', 0)}s")

    st.caption(
        f"模型 {summary.get('model', '?')} · "
        f"LLM 调用 {summary.get('llm_calls', 0)} 次"
        f"（其中评分 {summary.get('judge_calls', 0)} 次）· "
        f"{summary.get('prompt_tokens', 0)} in + {summary.get('completion_tokens', 0)} out"
    )

    if not summary.get("questions_asked"):
        st.warning(
            "整场面试没有通过 pick_question 出题，评分链路没有生效。"
            "常见原因是模型不支持 function calling（它会一直说话，但从不调工具）。"
        )


def show_report(summary: dict) -> None:
    """把报告渲染出来。没有报告就给出接下来能做什么。"""
    report_path = summary.get("report_path")
    if not report_path:
        st.info(
            "这场没有生成报告。两种情况：模型没有自己收尾（达到轮次上限），"
            "或者中途出了故障。**都还没白跑** —— 断点留着，下面可以直接接着跑。"
        )
        return

    path = Path(report_path)
    if not path.exists():
        st.info(f"报告路径是 {report_path}，但文件不在。")
        return

    st.subheader("复盘报告")
    st.caption(report_path)
    st.markdown(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 侧栏：这一次要怎么跑
# ---------------------------------------------------------------------------

scenarios = scenario_ids()
if not scenarios:
    st.error(f"{SCENARIOS_DIR} 里一个场景都没有，没法开始。")
    st.stop()

with st.sidebar:
    st.subheader("场景")
    scenario_id = st.selectbox("面试场景", scenarios, label_visibility="collapsed")

    st.subheader("模型")
    default_model = os.environ.get("CHAT_MODEL") or DEFAULT_MODEL
    model_field = st.text_input("面试官模型", value=default_model)
    score_field = st.text_input("评分模型", value=os.environ.get("SCORE_MODEL") or "")
    st.caption("评分模型留空 = 跟面试官同一个。分开能错开限流，判分视角也更独立。")

    provider_field = st.selectbox(
        "供应商", ["自动（按模型名判断）", *sorted(PROVIDERS)], index=0
    )

    with st.expander("用自己的凭据（可选）"):
        st.caption(
            "填了就优先用你这份，覆盖环境变量。"
            "**只存在内存里** —— 不写 .env、不进断点、不进 trace。"
        )
        api_key_field = st.text_input("API Key", type="password")
        base_url_field = st.text_input("API 端点（可选）")
        st.caption("端点留空 = 用该供应商的默认端点。向量化不受这里影响。")

    with st.expander("高级"):
        max_turns_field = st.slider("最大轮数", 4, 40, int(os.environ.get("MAX_TURNS") or 30))
        fallback_field = st.text_input("备选模型（限流时自动切）", value=os.environ.get("FALLBACK_MODEL") or "")
        use_llm_score_field = st.checkbox("用 LLM 评分", value=True)
        st.caption("关掉就退化成规则打分，调试流程时省额度。")

    st.divider()
    st.caption(f"向量库：{kb_line()}")
    with st.expander("供应商与 Key 的状态"):
        st.code(describe_all(), language=None)
        st.caption("这里看的是**环境变量**的配置情况；上面临时填的 Key 不在其中。")


# ---------------------------------------------------------------------------
# 主区
# ---------------------------------------------------------------------------

st.title("MockMate")
st.caption(
    "一个能自己决定「下一句问什么」的模拟面试官。"
    "面试官是模型，候选人按脚本作答 —— 所以每场都可复现。"
)

provider_arg = None if provider_field.startswith("自动") else provider_field
score_model_arg = score_field.strip() or None
api_key_arg = api_key_field.strip() or None
base_url_arg = base_url_field.strip() or None
fallback_arg = fallback_field.strip() or None

tab_new, tab_resume = st.tabs(["开始一场新的", "接着跑没跑完的"])

# ---- 跑一场新的 ----
with tab_new:
    st.write("")
    st.write(f"场景 **{scenario_id}** · 面试官 **{model_field or default_model}**")
    if api_key_arg:
        st.caption("这一场会用你在侧栏填的那份 Key（只在内存里）。")
    elif not os.environ.get("ZHIPU_API_KEY"):
        st.caption("没填 Key、环境里也没配 —— 如果模型属于需要 Key 的供应商，会直接报错。")

    if st.button("开始面试", type="primary"):
        answers_path = SCENARIOS_DIR / f"{scenario_id}.answers.json"
        if not answers_path.exists():
            st.error(f"找不到候选人回答脚本：{answers_path}")
        else:
            with st.spinner("面试进行中……"):
                outcome = stream_run(
                    scenario_id=scenario_id,
                    answers_path=answers_path,
                    max_turns=max_turns_field,
                    model=model_field or default_model,
                    verbose=True,
                    use_llm_score=use_llm_score_field,
                    score_model=score_model_arg,
                    provider=provider_arg,
                    fallback_model=fallback_arg,
                    interactive=False,          # ★ 网页里没有终端可以敲键盘，见文件开头
                    api_key=api_key_arg,
                    base_url=base_url_arg,
                )
            st.session_state["outcome"] = outcome

    outcome = st.session_state.get("outcome")
    if outcome:
        if outcome.get("error") is not None:
            st.error(f"这一场没能跑完：{type(outcome['error']).__name__}: {outcome['error']}")
        summary = outcome.get("summary")
        if summary:
            st.divider()
            show_summary(summary)
            show_report(summary)

# ---- 续跑 ----
with tab_resume:
    st.write("")
    runs = unfinished_runs()
    if not runs:
        st.info(
            "本地没有断点文件。断点是在面试过程中每轮落一次盘的，"
            "所以只有跑过（并且没跑完）的场次才会出现在这里。"
        )
    else:
        st.caption("下面是本地保留的断点。挑一个接着跑 —— 已经问过的轮次不会重来。")
        run_id = st.selectbox("断点", runs, format_func=checkpoint.describe)

        saved = checkpoint.load(run_id)
        saved_model = saved.get("model") or "?"
        st.caption(
            f"断点里的模型是 **{saved_model}**，已完成 {saved.get('turn', 0)} 轮。"
        )
        if model_field and model_field != saved_model:
            st.warning(
                f"侧栏里选的是 {model_field}，和断点里的 {saved_model} 不一样。"
                "换模型本身没问题，但会被记进报告 —— 读报告的人应该知道中途换过。"
            )

        if st.button("从断点继续"):
            # 没动过模型输入框就沿用断点里的那个（和命令行 --resume 的规则一致）；
            # 动过了就按用户填的来。
            model_arg = None if model_field == default_model else model_field
            with st.spinner(f"从第 {saved.get('turn', 0)} 轮接着跑……"):
                outcome = stream_run(
                    scenario_id=saved.get("scenario_id") or scenario_id,
                    answers_path=SCENARIOS_DIR / (saved.get("answers_file") or f"{scenario_id}.answers.json"),
                    max_turns=max_turns_field,
                    model=model_arg or saved_model,
                    verbose=True,
                    use_llm_score=use_llm_score_field,
                    score_model=score_model_arg,
                    provider=provider_arg,
                    fallback_model=fallback_arg,
                    resume_state=saved,
                    interactive=False,
                    api_key=api_key_arg,
                    base_url=base_url_arg,
                )
            st.session_state["outcome"] = outcome
            st.rerun()
