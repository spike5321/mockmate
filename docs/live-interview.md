# 真人面试模式：运行与验收

## 两种入口

- `streamlit run live_app.py`：真人文字面试。上传/粘贴简历和 JD，自己提供 Key；服务器不写简历、回答、Key、报告或轨迹。页面可下载报告。关闭/清除会话后不支持历史回看。
- `streamlit run app.py` 或 `python -u orchestrator.py --scenario backend_intern`：原有脚本候选人演示，保留本地断点、轨迹和可复现的回放样例。

真人模式的核心是 `agent/live.py` 中的 `LiveInterview`：`create()` 创建独立会话，`advance()` 推进至待答题，`submit_answer()` 保存用户原话并继续，`report()` 在结束后输出结构化报告。固定五个考察领域，每题最多两次追问。提问与追问仍使用模型工具调用；模型不参与录入考生答案，也不计算总分。评分模型失败的题目标为“未计分”，不会用按字数规则凑分。

```mermaid
flowchart LR
  U[访客浏览器] --> UI[Streamlit 交互页]
  UI --> P[内存中解析 PDF / DOCX / TXT]
  P --> S[独立 LiveInterview 会话]
  S --> Q[面试官模型：出题与追问]
  Q --> U
  U -->|原话| S
  S --> J[评分模型：固定维度评分]
  S --> R[程序复算总分与报告]
  J --> R
  R -->|Markdown / JSON 下载| U
```

真人模式不使用旧版脚本候选人、Chroma 知识库或磁盘断点；旧版仍保留供 Agent 工具链演示。整场最多两次追问，以限制真实用户的等待时间和模型成本。评分失败留下 `unscored` 与中断标记，缺题分时不显示总体评分。

## 本地验证

```bash
python -m pytest tests -q
python scripts/evaluate_live.py
```

第二条命令会用 `.env` 中的 `ZHIPU_API_KEY` 和 `CHAT_MODEL` 对三份**合成简历**完成真实模型面试，输出匿名问题、逐题分、评分来源、调用量和耗时。它会产生模型调用费用；没有 Key 时明确失败。可用 `--case rag_newgrad` 单独复测一个样例。人工复核需要逐题检查问题是否指向简历/JD、追问是否重复、证据是否来自回答，以及报告分数能否复算。未完成真实模型验证前，不应在简历中声称相关指标已达标。

一轮真实模型基线与人工复核结果见 [评测记录](evaluation-results.md)。它只证明合成用例可跑通和证据可逐字核对，未证明评分与真人一致；出题边界修改后尚待复测。

## 在线部署

首选 Streamlit Community Cloud：GitHub 仓库选择 `public/app.py` 作为入口，Python 3.12，部署工具会优先使用 `public/requirements.txt`。该入口只安装真人模式需要的轻量依赖，避免把原演示的 Chroma/FastEmbed 部署到公开实例。访客在页面填写自己的 Key；服务器不配置模型 Key。上线后从新浏览器验收“上传 → 确认 → 多轮回答 → 报告下载”，并用两个独立浏览器验证会话不串话。平台内存与休眠限制可能影响可用性，部署后需实际验证。
