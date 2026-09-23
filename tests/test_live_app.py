"""The hosted entrypoint must load without an API key or an existing scenario."""

from pathlib import Path
import json

from streamlit.testing.v1 import AppTest

from agent.live import LiveInterview
from agent.llm import LLMReply


def test_public_app_loads_and_requests_private_inputs():
    entry = Path(__file__).resolve().parents[1] / "public" / "app.py"
    app = AppTest.from_file(str(entry), default_timeout=30).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert any("上传简历" in w.label for w in app.get("file_uploader"))
    assert any(w.label == "解析并预览简历" for w in app.button)


def test_pasted_resume_can_be_previewed_before_model_call():
    entry = Path(__file__).resolve().parents[1] / "public" / "app.py"
    app = AppTest.from_file(str(entry), default_timeout=30).run()
    next(w for w in app.text_area if w.label == "或者粘贴简历文字").set_value("项目甲：RAG 系统").run()
    next(w for w in app.button if w.label == "解析并预览简历").click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    preview = next(w for w in app.text_area if w.label == "解析结果（请检查并修正）")
    assert "项目甲" in preview.value
    assert any(w.label == "目标岗位 JD（AI 应用开发）" for w in app.text_area)


def test_start_and_submit_answer_through_page(monkeypatch):
    class FakeLLM:
        total_calls = 0

        def chat(self, messages, tools=None):
            self.total_calls += 1
            names = {tool["function"]["name"] for tool in tools}
            if "ask_candidate" in names:
                name, args = "ask_candidate", {"question": "请结合项目甲介绍设计方案和权衡？", "focus": "设计"}
            else:
                name, args = "finish_question", {}
            return LLMReply(None, [{"function": {"name": name, "arguments": json.dumps(args)}}])

    class FakeEvaluator:
        llm = None

        def score(self, question, answer):
            return {"score": 7, "dimensions": {}, "comment": "具体", "evidence": [], "source": "llm"}

    def create(cls, resume, jd, api_key, model, provider):
        assert resume == "项目甲：RAG 系统" and jd == "AI 应用开发岗位" and api_key == "test-key"
        assert model == "glm-4.5-flash" and provider == "zhipu"
        return LiveInterview(resume, jd, FakeLLM(), FakeEvaluator())

    monkeypatch.setattr(LiveInterview, "create", classmethod(create))
    entry = Path(__file__).resolve().parents[1] / "public" / "app.py"
    app = AppTest.from_file(str(entry), default_timeout=30).run()
    next(w for w in app.text_area if w.label == "或者粘贴简历文字").set_value("项目甲：RAG 系统").run()
    next(w for w in app.button if w.label == "解析并预览简历").click().run()
    next(w for w in app.text_area if w.label == "目标岗位 JD（AI 应用开发）").set_value("AI 应用开发岗位").run()
    next(w for w in app.text_input if w.label == "你的模型 API Key").set_value("test-key").run()
    next(w for w in app.button if w.label == "开始面试").click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert "第 1 / 5 题" in [w.value for w in app.subheader][0]
    next(w for w in app.text_area if w.label.startswith("你的回答")).set_value("这是我的真实回答").run()
    next(w for w in app.button if w.label == "提交回答").click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert "第 2 / 5 题" in [w.value for w in app.subheader][0]
    next(w for w in app.button if w.label == "清除本次数据").click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert "live_session" not in app.session_state
    assert app.session_state["upload_epoch"] == 1


def test_public_provider_switch_uses_its_own_key_and_model(monkeypatch):
    captured = {}

    def create(cls, resume, jd, api_key, model, provider):
        captured.update(api_key=api_key, model=model, provider=provider)
        raise ValueError("stopped before network")

    monkeypatch.setattr(LiveInterview, "create", classmethod(create))
    entry = Path(__file__).resolve().parents[1] / "public" / "app.py"
    app = AppTest.from_file(str(entry), default_timeout=30).run()
    next(w for w in app.text_area if w.label == "或者粘贴简历文字").set_value("项目甲：RAG 系统").run()
    next(w for w in app.button if w.label == "解析并预览简历").click().run()
    assert "本机 Ollama" not in next(w for w in app.selectbox if w.label == "模型服务商").options
    next(w for w in app.text_area if w.label == "目标岗位 JD（AI 应用开发）").set_value("AI 应用开发岗位").run()
    next(w for w in app.text_input if w.label == "你的模型 API Key").set_value("zhipu-key").run()
    next(w for w in app.selectbox if w.label == "模型服务商").set_value("阿里云百炼 Qwen").run()
    assert next(w for w in app.text_input if w.label == "你的模型 API Key").value == ""
    next(w for w in app.text_input if w.label == "你的模型 API Key").set_value("qwen-key").run()
    next(w for w in app.button if w.label == "开始面试").click().run()
    assert captured == {"api_key": "qwen-key", "model": "qwen3.5-flash", "provider": "qwen"}
    assert not app.exception


def test_local_ui_offers_keyless_ollama(monkeypatch):
    captured = {}

    def create(cls, resume, jd, api_key, model, provider):
        captured.update(api_key=api_key, model=model, provider=provider)
        raise ValueError("stopped before network")

    monkeypatch.setattr(LiveInterview, "create", classmethod(create))
    entry = Path(__file__).resolve().parents[1] / "live_app.py"
    app = AppTest.from_file(str(entry), default_timeout=30).run()
    next(w for w in app.text_area if w.label == "或者粘贴简历文字").set_value("项目甲：RAG 系统").run()
    next(w for w in app.button if w.label == "解析并预览简历").click().run()
    next(w for w in app.text_area if w.label == "目标岗位 JD（AI 应用开发）").set_value("AI 应用开发岗位").run()
    next(w for w in app.selectbox if w.label == "模型服务商").set_value("本机 Ollama").run()
    assert not any(w.label == "你的模型 API Key" for w in app.text_input)
    next(w for w in app.button if w.label == "开始面试").click().run()
    assert captured == {"api_key": "", "model": "qwen2.5:7b", "provider": "ollama"}
    assert not app.exception
