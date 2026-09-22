# -*- coding: utf-8 -*-
"""融合 —— 把多路召回的结果合成一个排名。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 这里有两种算法，默认用 normalized_sum。这不是拍脑袋选的，是实测出来的。

实测（4 篇语料 / 33 片段 / 20 个带标注的查询 / 本地 bge-small-zh 向量模型）：

    策略            Hit@1   Hit@3    MRR     换说法型 Hit@1
    向量单路         50%     75%    0.617        50%
    关键词单路       70%     85%    0.767        60%
    等权 RRF         60%     80%    0.700        50%   ← 原来的实现
    归一化加权求和   70%     85%    0.767        70%   ← 现在默认
    复现：python scripts/compare_retrieval.py

  等权 RRF **比两个单路都差**。原因不是"RRF 不好"，而是它和这种小列表不匹配：

    RRF 把每路的第 1 名都记 1/(k+1) 分 ——
    两路的第一名**必然同分**，于是"两路对第一名意见不一致"时，
    只能按 id 排序碰运气。想靠调小 k 让名次起作用？k=1~60 扫了一遍，
    Hit@1 全是 60%，纹丝不动。名次敏感度调高了，第一名打平的问题就更突出；
    调低了，8 条列表里第 1 名和第 8 名的差距只剩 11%（1/61 vs 1/68），
    融合退化成"看这条在几个列表里出现过"。

    归一化加权求和没有这个死结：每路内部先 min-max 拉到 0~1，
    自己的第 1 名记 1.0、第 2 名记 0.8……名次差异是保留的，
    同时因为各路都归到了同一个尺度，分数可以相加。

★ 老实交代两件事：
  1. 70% 和 60% 的差别是 **20 个查询里的 2 个**，算不上"更准"的统计证据。
     真正站得住的是那条**结构性**区别（第一名必然打平），它有单测钉住。
  2. 全部数字来自**本地向量模型**。换智谱 embedding 后两路的强弱关系可能变化，
     结论要重跑 —— 这也是为什么 rrf_fuse 留着没删，它还能量。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

DEFAULT_K = 60
FUSIONS = ("norm", "rrf")
DEFAULT_FUSION = "norm"


def rrf_fuse(
    ranked_lists: list[list[str]],
    k: int = DEFAULT_K,
) -> list[tuple[str, float]]:
    """RRF（Reciprocal Rank Fusion）：只看名次，不看分数。

        score(片段) = Σ 1 / (k + 名次)

    优点是与分数尺度无关 —— 向量分是 0~1 的余弦、BM25 分没有上界，
    两者本来不可比，RRF 直接绕开了这件事。

    缺点在**候选列表很短**时会暴露：各路的第 1 名得分完全相同，
    谁排前面只能靠 id 排序决定（见上面模块开头的实测）。

    参数：每路是「按名次从前往后的 id 列表」。
    返回：[(id, 融合分)]，按分数降序；同分时按 id 排，保证结果稳定。
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def _minmax(scores: list[float]) -> list[float]:
    """把一路的分数线性拉到 0~1。

    全相等时（只有一条、或分数一模一样）第一条记 1.0 ——
    它毕竟是这一路的第一名。这是个简化，不追求绝对公平，
    只要求"同一路内部名次越前分越高"这件事成立。
    """
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return [1.0] + [0.0] * (len(scores) - 1)
    return [(s - lo) / (hi - lo) for s in scores]


def normalized_sum(
    scored_lists: list[list[tuple[str, float]]],
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """各路分数各自归一化后加权求和。

    参数：每路是 [(id, 分数)]，按名次从前往后。
          weights 缺省为等权 —— **刻意不偏袒任何一路**。
          给某一路更高权重能把这批查询的分数刷得更好看（实测关键词路给 0.7
          能让 Hit@3 到 90%），但那个假设（"关键词路更强"）换个语料就不成立，
          是过拟合到这份语料上，所以不做。

    返回：[(id, 融合分)]，按分数降序；同分时按 id 排。
    """
    if weights is None:
        weights = [1.0] * len(scored_lists)
    if len(weights) != len(scored_lists):
        raise ValueError(f"权重个数（{len(weights)}）要和路数（{len(scored_lists)}）一致")

    totals: dict[str, float] = {}
    for entries, weight in zip(scored_lists, weights):
        if not entries:
            continue
        for (doc_id, _), value in zip(entries, _minmax([s for _, s in entries])):
            totals[doc_id] = totals.get(doc_id, 0.0) + weight * value
    return sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))


def fuse(
    scored_lists: list[list[tuple[str, float]]],
    method: str = DEFAULT_FUSION,
    *,
    weights: list[float] | None = None,
    k: int = DEFAULT_K,
) -> list[tuple[str, float]]:
    """按 method 选择融合算法。

    入参统一是 [(id, 分数)]，因为 RRF 只用得到名次、归一化那套要用分数，
    让调用方多传一份"只有名次的版本"是没必要的重复。
    """
    if method not in FUSIONS:
        raise ValueError(f"method 只能是 {FUSIONS} 之一，收到 {method!r}")
    if method == "rrf":
        return rrf_fuse([[doc_id for doc_id, _ in entries] for entries in scored_lists], k=k)
    return normalized_sum(scored_lists, weights)
