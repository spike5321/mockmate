# -*- coding: utf-8 -*-
"""知识库构建入口（离线跑一次，不参与面试运行时）。

用法：
    python -m kb.build                 # 入库 knowledge/ 下的全部文档
    python -m kb.build --rebuild       # 清空向量库后重建
    python -m kb.build some/doc.md     # 只入库指定文件
    python -m kb.build --show          # 只看向量库现状，不入库

为什么要单独一个入口？
    建库要调 embedding 接口、要花时间和 token，属于「离线预处理」；
    检索发生在面试运行过程中。把两者分开，运行面试时就不用担心
    知识库还没准备好 —— 库没建好时检索会返回空，面试照常进行。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from agent.llm import DEFAULT_EMBEDDING_MODEL, LLMClient  # noqa: E402
from kb.search import kb_status  # noqa: E402
from kb.store import DOCS_DIR, KB_DIR, collect_files, ingest  # noqa: E402

MARK = {"added": "✓", "empty": "-", "error": "!"}


def show_status() -> int:
    status = kb_status()
    print(f"向量库目录 : {KB_DIR}")
    print(f"片段总数   : {status['chunks']}")
    if status["sources"]:
        print("来源明细   :")
        for name, n in sorted(status["sources"].items()):
            print(f"    {name:<36} {n:>4} 片段")
    else:
        print("（库是空的，先跑一次 python -m kb.build 入库）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 MockMate 知识库向量索引")
    parser.add_argument("paths", nargs="*", help="要入库的文件或目录，默认 knowledge/")
    parser.add_argument("--rebuild", action="store_true", help="清空向量库后重建")
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL, help="向量化模型")
    parser.add_argument("--show", action="store_true", help="只查看向量库现状")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if args.show:
        return show_status()

    api_key = os.environ.get("ZHIPU_API_KEY", "")
    if not api_key:
        print("缺少 ZHIPU_API_KEY。请把 .env.example 复制成 .env 并填入你的智谱 Key。")
        return 2

    targets = [Path(p) for p in args.paths] or [DOCS_DIR]
    files = collect_files(targets)
    if not files:
        print(f"没找到可入库的文档（支持 {sorted(['.md', '.txt', '.pdf'])}）：{[str(t) for t in targets]}")
        return 2

    llm = LLMClient(api_key=api_key, verbose=False)
    print(f"向量库目录 : {KB_DIR}")
    print(f"语料文件   : {len(files)} 个")
    print(f"向量化模型 : {args.model}")
    print("-" * 62)

    results = ingest(
        files,
        embed_fn=lambda texts: llm.embed(texts, embedding_model=args.model),
        reset=args.rebuild,
    )

    total = 0
    for r in results:
        mark = MARK.get(r["status"], "?")
        note = f"  ← {r.get('error', '')[:60]}" if r.get("error") else ""
        print(f"  {mark} {r['source']:<34} {r['chunks']:>4} 片段  {r['status']}{note}")
        if r["status"] == "added":
            total += r["chunks"]

    print("-" * 62)
    print(f"本次入库 {total} 个片段")
    return show_status()


if __name__ == "__main__":
    raise SystemExit(main())
