# -*- coding: utf-8 -*-
"""检索质量对照：向量单路 / 关键词单路 / 混合，在三组查询上比命中率。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么要有这个脚本？

"混合检索更准"是一句很容易写进 README 的话，但**它得有数字撑着**。
脚本留在仓库里，"这些数字是不是编的"这个问题才能被回答 ——
任何人跑一遍就能核对。

★ 基线是从 git 历史里**原样抄**的，不是凭印象重写的近似版本。
  旧实现（commit 53431a9 时的 kb/search.py）只走向量一路，
  这里叫 old_retrieve()。脚本开头会做一次自检：
  旧的 old_retrieve() 和新实现的 retrieve(mode="vector") 排名必须一致 ——
  不一致就说明"基线"是个假基线，后面的对比全都不作数。

用法：
    python scripts/compare_retrieval.py            # 用当前配置的向量库
    python scripts/compare_retrieval.py -v         # 连每个查询的 Top-3 一起打

注意：切换 embedding 供应商后必须先重建库，否则这里比的是噪声。
      MOCKMATE_KB_DIR 可以指向另一份库，方便换模型做对照。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from kb.embed import embed_texts, provider_info  # noqa: E402
from kb.search import retrieve  # noqa: E402
from kb.store import get_collection, get_embed_sig  # noqa: E402


# ---------------------------------------------------------------- 旧实现（基线）
def old_retrieve(query: str, k: int = 3) -> list[dict]:
    """commit 53431a9 时的 retrieve()，原样抄自 `git show HEAD:kb/search.py`。

    只有向量一路。作为"加了关键词路之后到底有没有变好"的对照。
    """
    col = get_collection()
    count = col.count()
    if count == 0:
        return []

    vector = embed_texts([query])[0]
    res = col.query(query_embeddings=[vector], n_results=min(k, count))

    hits: list[dict] = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        hits.append(
            {
                "text": doc,
                "source": meta.get("source", "?"),
                "chunk": meta.get("chunk"),
                "score": round(1 - dist, 4),
            }
        )
    return hits


# ---------------------------------------------------------------- 查询集（带标注）
# 每条：(查询, 目标文件, 目标片段序号, 族)
#
# 族只有两种，规则很实在：
#   literal  —— 查询里**写了**目标小节的关键术语（"雪崩""RDB""幂等"），
#               关键词路按字面就该命中
#   paraphrase —— 查询换了说法，同一个术语一次都没出现，只能靠语义对上
# 分开统计的理由：两路的擅长面本来就不同，混在一起算总分，
# 会把"各补各的"这件事平均掉。
QUERIES: list[tuple[str, str, int, str]] = [
    # ---- 专有名词型：查询里带着目标术语 ----
    ("ZSet 在排行榜里怎么用", "redis_points.md", 6, "literal"),
    ("RDB 和 AOF 怎么选", "redis_points.md", 5, "literal"),
    ("Redlock 到底有没有必要", "redis_points.md", 7, "literal"),
    ("HTTP/2 的多路复用解决什么问题", "http_network_points.md", 5, "literal"),
    ("TIME_WAIT 状态要等多久", "http_network_points.md", 4, "literal"),
    ("雪花算法遇到时钟回拨怎么办", "system_design_points.md", 5, "literal"),
    ("hash tag 怎么控制 key 的分布", "redis_points.md", 8, "literal"),
    ("短链接为什么用 302 而不是 301", "system_design_points.md", 2, "literal"),
    ("Cache Aside 为什么删缓存而不是更新", "redis_points.md", 4, "literal"),
    ("布隆过滤器怎么拦住不存在的 key", "redis_points.md", 1, "literal"),
    # ---- 换说法型：目标术语一个都没出现 ----
    ("怎么防止一大批数据同一时间全部失效", "redis_points.md", 3, "paraphrase"),
    ("刚过期的热点数据被并发请求打到数据库上", "redis_points.md", 2, "paraphrase"),
    ("面试官会怎么顺着我的回答继续往下问", "interview_process.md", 5, "paraphrase"),
    ("设计一个发号器怎么保证全局不重复", "system_design_points.md", 5, "paraphrase"),
    ("流量瞬间涌进来怎么保证不超卖", "system_design_points.md", 3, "paraphrase"),
    ("怎么保证用户重复提交不会重复扣钱", "http_network_points.md", 6, "paraphrase"),
    ("传输过程为什么不全程用非对称加密", "http_network_points.md", 2, "paraphrase"),
    ("时间不够的话项目该怎么取舍", "interview_process.md", 6, "paraphrase"),
    ("系统设计题一上来先干什么", "system_design_points.md", 1, "paraphrase"),
    ("候选人只会说方案，问他为什么就卡住", "system_design_points.md", 8, "paraphrase"),
]

MODES = ("old", "vector", "bm25", "hybrid", "hybrid-rrf")


def run(query: str, mode: str, k: int = 3) -> list[dict]:
    """按模式跑一次检索。old 是改动前的向量单路实现。"""
    if mode == "old":
        return old_retrieve(query, k)
    if mode == "hybrid-rrf":
        # 等权 RRF：已经被换下默认位，但留着能量 —— 换语料/换向量模型后要重比
        return retrieve(query, k, mode="hybrid", fusion="rrf")
    return retrieve(query, k, mode=mode)


def norm(hits: list[dict]) -> list[tuple[str, int]]:
    """检索结果 → [(文件, 片段号)]，用来和目标比对。"""
    return [(h["source"], h["chunk"]) for h in hits]


def rank_of(target, ranked) -> int:
    """目标排在几位（1 起）。没进榜返回 0。"""
    return ranked.index(target) + 1 if target in ranked else 0


def main() -> int:
    verbose = "-v" in sys.argv
    col = get_collection()
    if col.count() == 0:
        print("向量库是空的，先跑：python -m kb.build")
        return 1

    print(f"语料库     : {col.count()} 个片段")
    print(f"库用什么建 : {get_embed_sig()}")
    print(f"当前配置   : {provider_info()['signature']}")

    # ---- 基线自检：旧实现必须等于新实现的向量单路 ----
    probes = [q for q, _, _, _ in QUERIES[:5]]
    mismatch = [
        q for q in probes if norm(old_retrieve(q, 3)) != norm(retrieve(q, 3, mode="vector"))
    ]
    if mismatch:
        print(f"\n❌ 基线自检失败：{len(mismatch)}/{len(probes)} 个查询的排名对不上，")
        print("   说明 old_retrieve() 已经不能代表改动前的行为了，下面的对比不作数。")
        for q in mismatch:
            print(f"     {q}")
            print(f"       旧 : {norm(old_retrieve(q, 3))}")
            print(f"       新 : {norm(retrieve(q, 3, mode='vector'))}")
        return 2
    print(f"基线自检   : ✅ 旧实现 == 新实现的 vector 模式（抽查 {len(probes)} 个查询）")

    # ---- 逐条跑 ----
    rows = []
    for query, source, chunk, family in QUERIES:
        target = (source, chunk)
        got = {}
        for mode in MODES:
            got[mode] = run(query, mode)
        rows.append({"query": query, "target": target, "family": family, "got": got})

        if verbose:
            head = next(
                (h["text"].split("\n")[0].strip() for h in got["hybrid"] if (h["source"], h["chunk"]) == target),
                "—",
            )
            print(f"\n【{family}】{query}")
            print(f"  目标 : {source} #{chunk} {head[:30]}")
            for mode in MODES:
                r = rank_of(target, norm(got[mode]))
                top = got[mode][0]["text"].split("\n")[0].strip() if got[mode] else "（无命中）"
                flag = f"✓ 第{r}位" if r else "✗ 未进前3"
                print(f"  {mode:<7} {flag:<9} 首条：{top[:26]}")

    # ---- 汇总 ----
    def summarize(subset: list[dict]) -> dict[str, tuple[float, float, float]]:
        out = {}
        for mode in MODES:
            hit1 = hit3 = 0
            rr = 0.0
            for row in subset:
                r = rank_of(row["target"], norm(row["got"][mode]))
                hit3 += 1 if r else 0
                hit1 += 1 if r == 1 else 0
                rr += (1.0 / r) if r else 0.0
            n = len(subset) or 1
            out[mode] = (hit1 / n, hit3 / n, rr / n)
        return out

    def block(title: str, subset: list[dict]) -> None:
        print(f"\n{title}（{len(subset)} 个查询）")
        print(f"  {'模式':<8}{'Hit@1':>8}{'Hit@3':>8}{'MRR':>8}")
        stats = summarize(subset)
        for mode in MODES:
            h1, h3, mrr = stats[mode]
            print(f"  {mode:<8}{h1:>7.0%}{h3:>8.0%}{mrr:>8.3f}")

    print("\n" + "=" * 62)
    block("全部", rows)
    block("专有名词型（查询写了目标术语）", [r for r in rows if r["family"] == "literal"])
    block("换说法型（目标术语没出现）", [r for r in rows if r["family"] == "paraphrase"])

    # ---- 混合路是怎么凑出来的 ----
    print("\n混合路的构成（只看 Top-3）")
    for row in rows:
        via = [h.get("via", "?") for h in row["got"]["hybrid"][:3]]
        print(f"  {row['query'][:22]:<24} {' '.join(f'{v:<7}' for v in via)}")

    # ---- 差异案例 ----
    diff = [
        row
        for row in rows
        if len({rank_of(row["target"], norm(row["got"][m])) for m in ("vector", "bm25", "hybrid")}) > 1
    ]
    print(f"\n三种模式结果不同的查询：{len(diff)} / {len(rows)}")
    for row in diff:
        target = row["target"]
        line = "  ".join(
            f"{m}:{'第%d位' % rank_of(target, norm(row['got'][m])) if rank_of(target, norm(row['got'][m])) else '未中'}"
            for m in ("vector", "bm25", "hybrid")
        )
        print(f"  {row['query'][:24]:<26} {line}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
