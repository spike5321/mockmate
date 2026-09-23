"""Private-by-default public text interview. Run: streamlit run live_app.py."""

from __future__ import annotations

import json

import streamlit as st

from agent.live import LiveInterview, render_markdown
from agent.llm import LLMError
from agent.providers import PROVIDERS, ProviderError
from agent.resume import parse_resume, validate_resume_text

st.set_page_config(page_title="MockMate · AI 应用开发模拟面试", layout="centered")

PROVIDER_LABELS = {
    "zhipu": "智谱 GLM",
    "deepseek": "DeepSeek",
    "qwen": "阿里云百炼 Qwen",
    "ollama": "本机 Ollama",
}


def clear_credentials() -> None:
    for provider in PROVIDER_LABELS:
        st.session_state.pop(f"live_key_{provider}", None)


def clear_session() -> None:
    session = st.session_state.pop("live_session", None)
    if session is not None:
        session.clear()
    for key in ("resume_preview", "resume_paste", "jd_input", "answer_input"):
        st.session_state.pop(key, None)
    clear_credentials()
    st.session_state["upload_epoch"] = st.session_state.get("upload_epoch", 0) + 1


def show_error(exc: Exception) -> None:
    if isinstance(exc, LLMError):
        if exc.kind == "rate_limit":
            st.error("模型服务商限流或额度已用尽。请查看该账户的用量，稍后重试或切换供应商。")
        elif exc.kind == "auth":
            st.error("模型服务商鉴权失败。请确认 Key 属于所选供应商，且仍然有效。")
        else:
            st.error(f"模型调用失败（{exc.kind}）。请检查模型和网络后重试。")
    elif isinstance(exc, ValueError):
        st.error(str(exc))
    elif isinstance(exc, ProviderError):
        st.error("模型或供应商配置无法识别，请检查模型名称与 Key。")
    else:
        st.error("操作失败。请重试；如果持续失败，请重新开始一场面试。")


session: LiveInterview | None = st.session_state.get("live_session")
if session is not None and session.expired():
    clear_session()
    session = None
    st.warning("本次面试已过期，简历与回答已从会话中清除。")

st.title("MockMate · AI 应用开发模拟面试")
st.caption("上传简历，粘贴岗位 JD，逐题用文字回答，最后获取可下载的复盘报告。")
st.info("简历、回答和 API Key 仅保存在当前网页会话内存中；会发送给你选用的模型服务商。关闭或清除会话后，本站无法恢复记录。")

if session is None:
    st.subheader("1 · 准备资料")
    uploaded = st.file_uploader(
        "上传简历（PDF / DOCX / TXT，最多 5 MB）", type=["pdf", "docx", "txt"],
        max_upload_size=5, key=f"resume_upload_{st.session_state.get('upload_epoch', 0)}",
    )
    pasted = st.text_area("或者粘贴简历文字", key="resume_paste", height=120)
    if st.button("解析并预览简历"):
        try:
            preview = parse_resume(uploaded.name, uploaded.getvalue()) if uploaded else validate_resume_text(pasted)
            st.session_state["resume_preview"] = preview
            st.rerun()
        except Exception as exc:
            show_error(exc)

    if "resume_preview" in st.session_state:
        st.text_area("解析结果（请检查并修正）", key="resume_preview", height=220)
        st.subheader("2 · 岗位与模型")
        st.text_area("目标岗位 JD（AI 应用开发）", key="jd_input", height=150)
        options = ["zhipu", "deepseek", "qwen"]
        if not st.session_state.get("_mockmate_public_mode", False):
            options.append("ollama")
        provider = st.selectbox("模型服务商", options, format_func=lambda item: PROVIDER_LABELS[item])
        models = PROVIDERS[provider].models
        if provider == "deepseek":
            models = ("deepseek-flash",)  # 旧的 deepseek-chat 只留作历史兼容
        model = st.selectbox("面试模型", models, key=f"live_model_{provider}")
        if provider == "ollama":
            api_key = ""
            st.caption("仅本机可用：先启动 Ollama 并下载所选模型；无需 API Key。")
        else:
            api_key = st.text_input("你的模型 API Key", type="password", key=f"live_key_{provider}")
            st.caption(f"请使用 {PROVIDER_LABELS[provider]} 的 API Key；不同服务商的 Key 不能通用。")
        st.caption("合成样例一场约 12 次模型调用；实际用量因模型和回答而异，报告会显示 token 用量。")
        if st.button("开始面试", type="primary"):
            try:
                session = LiveInterview.create(
                    st.session_state["resume_preview"], st.session_state.get("jd_input", ""),
                    api_key, model=model, provider=provider,
                )
                session.advance()
                st.session_state["live_session"] = session
                st.session_state.pop("resume_preview", None)
                st.session_state.pop("resume_paste", None)
                st.session_state.pop("jd_input", None)
                clear_credentials()
                st.rerun()
            except Exception as exc:
                if session is not None:
                    session.clear()
                show_error(exc)
else:
    if st.button("清除本次数据"):
        clear_session()
        st.rerun()

    judge = getattr(session.evaluator, "llm", None)
    calls = getattr(session.interviewer, "total_calls", 0) + getattr(judge, "total_calls", 0)
    prompt_tokens = getattr(session.interviewer, "total_prompt_tokens", 0) + getattr(judge, "total_prompt_tokens", 0)
    completion_tokens = getattr(session.interviewer, "total_completion_tokens", 0) + getattr(judge, "total_completion_tokens", 0)
    st.caption(
        f"本场已调用模型 {calls} 次；输入 {prompt_tokens}、输出 {completion_tokens} tokens。"
        "服务商按其实际规则计费。"
    )

    if session.phase == "awaiting":
        pending = session.pending_question()
        assert pending is not None
        st.progress((pending["number"] - 1) / pending["total"])
        st.subheader(f"第 {pending['number']} / {pending['total']} 题 · {pending['label']}")
        if pending["followup"]:
            st.caption("追问")
        st.write(pending["question"])
        answer = st.text_area("你的回答（可以留空表示不会）", key="answer_input", height=180)
        if st.button("提交回答", type="primary"):
            try:
                with st.spinner("面试官思考中……"):
                    session.submit_answer(answer)
                st.session_state.pop("answer_input", None)
                st.rerun()
            except Exception as exc:
                show_error(exc)
                st.info("回答已保留在本次会话；点击下方按钮重试，不会重复提交。")

    if session.phase in ("ready", "deciding"):
        st.warning("模型调用中断，本次会话仍在内存中。")
        if st.button("重试继续"):
            try:
                with st.spinner("继续面试中……"):
                    session.advance()
                st.rerun()
            except Exception as exc:
                show_error(exc)

    if session.phase == "complete":
        report = session.report()
        markdown = render_markdown(report)
        st.success("面试已完成")
        st.metric("总体评分", f"{report['overall_score']} / 100" if report["overall_score"] is not None else "评分不完整")
        st.markdown(markdown)
        st.download_button("下载 Markdown 报告", markdown, file_name="mockmate-report.md", mime="text/markdown")
        st.download_button(
            "下载 JSON 明细", json.dumps(report, ensure_ascii=False, indent=2),
            file_name="mockmate-report.json", mime="application/json",
        )
