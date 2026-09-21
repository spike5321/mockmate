# -*- coding: utf-8 -*-
"""知识库构建入口（离线跑一次，不参与面试运行时）。

用法：
    python -m kb.build                     # 入库 knowledge/ 下的全部文档
    python -m kb.build --rebuild           # 清空向量库后重建
    python -m kb.build --provider local    # 强制用本地向量模型（免 Key、免网络）
    python -m kb.build some/doc.md         # 只入库指定文件
    python -m kb.build --show              # 只看向量库现状，不入库

为什么要单独一个入口？
    建库要调 embedding 接口、要花时间和 token，属于「离线预处理」；
    检索发生在面试运行过程中。把两者分开，运行面试时就不用担心
    知识库还没准备好 —— 库没建好时检索会返回空，面试照常进行。

关于 Key：
    **建库不再强制要求 ZHIPU_API_KEY。** 没配 Key 时自动改用本地向量模型
    （fastembed，首次会下载约 91MB）。这样评审 clone 下来不填任何配置
    也能把知识库建起来 —— 向量检索这一层不再是"必须联网"的。
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

from kb.embed import PROVIDERS, embed_texts, provider_info  # noqa: E402
from kb.search import kb_status  # noqa: E402
from kb.store import (  # noqa: E402
    DOCS_DIR,
    KB_DIR,
    collect_files,
    get_embed_sig,
    ingest,
    set_embed_sig,
)

MARK = {"added": "✓", "empty": "-", "error": "!"}


def show_status() -> int:
    status = kb_status()
    print(f"向量库目录 : {KB_DIR}")
    print(f"片段总数   : {status['chunks']}")
    print(f"库用什么建 : {status['built_with'] or '（老库，没记录）'}")
    print(f"当前配置是 : {status['current']}")
    if status["chunks"] and status["built_with"] and status["built_with"] != status["current"]:
        print("             ↑ 两者不一致，检索会失败。请 python -m kb.build --rebuild 重建")
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
    parser.add_argument(
        "--provider",
        choices=list(PROVIDERS),
        default=None,
        help="向量化走哪家：auto(默认，有 Key 用智谱否则本地) / zhipu / local",
    )
    parser.add_argument("--model", default=None, help="向量化模型（默认按 provider 取）")
    parser.add_argument("--show", action="store_true", help="只查看向量库现状")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if args.provider:
        os.environ["EMBEDDING_PROVIDER"] = args.provider

    if args.show:
        return show_status()

    info = provider_info(args.model)

    # ★ 建库前先拦一道：库里已有的向量和这次要写进去的必须是同一套。
    #   不拦的话 Chroma 会在写入时才发现维度对不上，报错晦涩，
    #   而且那时候可能已经写进去一部分片段了，库处于半新半旧的状态。
    built = get_embed_sig()
    if built and built != info["signature"] and not args.rebuild:
        print(f"现有向量库是用 {built} 建的，本次要用 {info['signature']}。")
        print("两种向量不能混在一个库里，请加 --rebuild 重建。")
        return 2

    targets = [Path(p) for p in args.paths] or [DOCS_DIR]
    files = collect_files(targets)
    if not files:
        print(f"没找到可入库的文档（支持 {sorted(['.md', '.txt', '.pdf'])}）：{[str(t) for t in targets]}")
        return 2

    print(f"向量库目录 : {KB_DIR}")
    print(f"语料文件   : {len(files)} 个")
    print(f"向量化     : {info['provider']} / {info['model']}")
    print("-" * 62)

    results = ingest(
        files,
        embed_fn=lambda texts: embed_texts(texts, model=args.model),
        reset=args.rebuild,
    )

    total = 0
    for r in results:
        mark = MARK.get(r["status"], "?")
        note = f"  ← {r.get('error', '')[:60]}" if r.get("error") else ""
        print(f"  {mark} {r['source']:<34} {r['chunks']:>4} 片段  {r['status']}{note}")
        if r["status"] == "added":
            total += r["chunks"]

    # 有片段真的写进去了才更新标记 —— 全部失败时不该覆盖库的原有身份
    if total:
        set_embed_sig(info["signature"])

    print("-" * 62)
    print(f"本次入库 {total} 个片段")
    return show_status()


if __name__ == "__main__":
    raise SystemExit(main())
