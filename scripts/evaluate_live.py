"""Run three synthetic, real-model interviews; never log an API key or real resume.

Usage: python scripts/evaluate_live.py
The output is JSON on stdout. Only synthetic profiles are included.
"""

from __future__ import annotations

import json
import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.live import LiveInterview  # noqa: E402
from agent.llm import DEFAULT_MODEL  # noqa: E402


JD = (
    "AI 应用开发工程师：负责基于大模型构建知识库问答与智能助手，"
    "设计 RAG 检索、Agent 工具调用、效果评测，关注可靠性、延迟、成本与用户体验。"
)
CASES = [
    {
        "id": "rag_newgrad",
        "resume": "脱敏样例 A：计算机应届生。项目：校园知识库问答，使用 Markdown 切分、Chroma 向量检索、BM25 混合召回；用 20 条标注问题测 Hit@3。",
        "answers": {
            "project": "我负责知识库切分与召回。用 Markdown 标题分段，比较了向量检索和 BM25，在 20 条标注问题上计算 Hit@3。样本还小，后续会扩到更多真实提问。",
            "rag": "我会按标题切块并保留来源，向量和关键词分别召回再融合。回答必须给出引用；无证据时明确说不知道。用 Hit@3 和人工检查衡量检索与生成。",
            "agent": "我会给工具定义严格参数和返回错误，保存当前会话状态，限制调用次数。工具失败时把错误交给模型并设置重试上限。",
            "evaluation": "先建小规模带标签的问题集，测检索命中、引用准确率和端到端完成率，同时记录 P95 延迟、token 用量和失败率。",
            "behavioral": "我曾与同学对检索方案有分歧。我先定义共同的标注集，双方方案都跑同一组问题，再根据命中率和延迟决定。",
        },
    },
    {
        "id": "backend_transition",
        "resume": "脱敏样例 B：后端开发实习生。项目：Spring Boot 订单服务，使用 Redis 缓存与 MySQL；负责接口与故障排查。尚无独立 RAG 项目，正在学习大模型 API。",
        "answers": {
            "project": "我在订单服务做过 Redis 缓存和接口开发。高峰时出现缓存穿透，我增加了空值缓存和短过期时间；没有正式压测数据，不能声称性能提升了多少。",
            "rag": "我没有独立上线过 RAG。思路是先按文档结构切分，做向量和关键词召回，再用有标注的问题验证是否找到了正确片段。",
            "agent": "我会把外部 API 包成有类型约束的工具，工具调用失败分清网络错误与参数错误，并设置超时。会话状态要跟用户隔离。",
            "evaluation": "我会先收集典型任务，制定成功与失败标准，然后比较改动前后的完成率、延迟和 token 成本。",
            "behavioral": "遇到不熟悉的模型问题，我会说明已验证的范围，列出不确定点，再做小实验确认，不会把猜测当结果。",
        },
    },
    {
        "id": "agent_evaluator",
        "resume": "脱敏样例 C：软件工程毕业生。项目：客服 Agent，设计工具调用和人工接管；写了 30 条场景回归用例，对比模型升级前后的任务完成率。",
        "answers": {
            "project": "客服 Agent 有查询订单和创建工单两个工具。我负责参数校验和人工接管条件；用 30 条场景做回归，但还没有长期线上指标。",
            "rag": "客服知识库会先做文档去重和版本管理，检索结果保留出处。未命中时不应编答案，而要转人工。",
            "agent": "工具调用要校验参数并限制权限；创建工单属于写操作，需要明确确认。模型循环要限制次数，状态里记录当前任务和已执行操作。",
            "evaluation": "我把任务分成查单、解释政策、创建工单三类，各收集成功、异常和边界案例，比较完成率、错误写入率与人工接管比例。",
            "behavioral": "一次模型升级让创建工单误触发增加。我先回滚，再补充误触发用例，与产品确认何时必须人工接管。",
        },
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--case", choices=[case["id"] for case in CASES])
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("ZHIPU_API_KEY") or ""
    if not api_key:
        print("缺少 ZHIPU_API_KEY，无法执行真实模型评测。", file=sys.stderr)
        return 2
    model = os.getenv("CHAT_MODEL") or DEFAULT_MODEL
    output = []
    selected = [case for case in CASES if case["id"] == args.case] if args.case else CASES[:args.limit]
    for case in selected:
        print(f"开始评测 {case['id']}", file=sys.stderr, flush=True)
        started = time.monotonic()
        interview = LiveInterview.create(case["resume"], JD, api_key, model=model)
        try:
            pending = interview.advance()
            questions = []
            while pending is not None:
                print(f"  {pending['track']} {'追问' if pending['followup'] else '主问题'}", file=sys.stderr, flush=True)
                questions.append({
                    "track": pending["track"], "question": pending["question"],
                    "followup": pending["followup"],
                })
                pending = interview.submit_answer(case["answers"][pending["track"]])
            report = interview.report()
            output.append({
                "id": case["id"], "complete": report["scoring_complete"],
                "score": report["overall_score"], "questions": questions,
                "round_scores": [r["score"] for r in report["rounds"]],
                "source": [r["source"] for r in report["rounds"]],
                "evidence": [r["evidence"] for r in report["rounds"]],
                "evidence_all_verbatim": all(
                    evidence in record["answer"]
                    for record in report["rounds"] for evidence in record["evidence"]
                ),
                "calls": report["llm_calls"], "prompt_tokens": report["prompt_tokens"],
                "completion_tokens": report["completion_tokens"],
                "elapsed_sec": round(time.monotonic() - started, 1),
            })
        except Exception as exc:
            print(f"  失败：{type(exc).__name__}：{exc}，阶段 {interview.phase}", file=sys.stderr, flush=True)
            output.append({"id": case["id"], "complete": False, "error_type": type(exc).__name__,
                           "phase": interview.phase, "scored": len(interview.records)})
        finally:
            interview.clear()
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if all(item.get("complete") for item in output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
