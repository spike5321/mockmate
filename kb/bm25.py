# -*- coding: utf-8 -*-
"""BM25 关键词检索 —— 给向量检索补上「专有名词」这一路。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么需要它？

向量检索比的是**语义**：问「缓存击穿怎么答」，它能命中写着「热点 key 失效」
的段落 —— 这是它的长处。但它对**专有名词**很弱：「LRU」「三次握手」「B+ 树」
这类词在向量空间里和周边概念挤成一团，反而不如老老实实的关键词匹配可靠。

BM25 正好补这一路：它只看词有没有出现、出现几次、这个词在语料里有多稀有。
两路各有所长，合起来才是完整的召回。

★ 中文怎么切词：用**字符二元组（bigram）**，不引分词器。

  中文没有空格，正经做法是上 jieba 之类 —— 可那要带一个几十 MB 的词典，
  和这个项目「clone 下来就能跑」的目标相冲。二元组是中文检索里的成熟做法：
  「缓存击穿」→ 缓存 / 存击 / 击穿，对「专有名词精确命中」这件事足够用，且零依赖。

  代价是它不懂词边界（"穿击"这种不存在的词也会贡献一点分），
  但 BM25 的 IDF 会自然把那些到处乱出现的组合压低 —— 这也是用它而不是
  简单计数的原因。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import math
import re
from collections import Counter

# BM25 的两个经典经验参数（Robertson 那套取值）
K1 = 1.5   # 词频饱和：一个词出现 20 次，不该比出现 5 次重要 4 倍
B = 0.75   # 长度归一化：长片段天然容易命中更多词，得压一压

# 中文段 / 英文数字段。B+ 里的 +、C++ 里的 ++、.NET 里的 . 都算词内字符，
# 不然「B+树」会被切成 "b" 和 "树"，专有名词就散了。
_CHUNK = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9+#.]+")
_IS_CJK = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """切词：中文走二元组，英文数字整词保留（转小写）。"""
    tokens: list[str] = []
    for chunk in _CHUNK.findall(text or ""):
        if _IS_CJK.match(chunk):
            if len(chunk) == 1:
                tokens.append(chunk)
            else:
                tokens.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
        else:
            tokens.append(chunk.lower())
    return tokens


class BM25:
    """一个小而够用的 BM25。

    语料只有几十个片段时，直接暴力打分比费劲建倒排索引更快、也更好读 ——
    别为了"看起来专业"把三十行能说清的事写成三百行。
    """

    def __init__(self, docs: list[str]) -> None:
        self.size = len(docs)
        self.doc_tokens = [tokenize(doc) for doc in docs]
        self.doc_len = [len(tokens) for tokens in self.doc_tokens]
        self.avg_len = (sum(self.doc_len) / self.size) if self.size else 0.0

        self.term_freq: list[Counter] = [Counter(tokens) for tokens in self.doc_tokens]

        # 文档频率：每个词出现在多少个片段里
        doc_freq: Counter = Counter()
        for counter in self.term_freq:
            doc_freq.update(counter.keys())

        # IDF：出现得越少越值钱。带 +0.5 平滑，既避免除零也避免出现负值
        # （负 IDF 会让"命中更多词反而分数更低"，那就荒唐了）。
        self.idf = {
            term: math.log(1 + (self.size - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def scores(self, query: str) -> list[float]:
        """给每个片段打一个分。分数没有上界，只用来排名次。"""
        terms = tokenize(query)
        if not terms or not self.size:
            return [0.0] * self.size

        out: list[float] = []
        for index, counter in enumerate(self.term_freq):
            length = self.doc_len[index] or 1
            total = 0.0
            for term in terms:
                freq = counter.get(term)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                denominator = freq + K1 * (1 - B + B * length / (self.avg_len or 1))
                total += idf * freq * (K1 + 1) / denominator
            out.append(total)
        return out

    def top_k(self, query: str, k: int) -> list[tuple[int, float]]:
        """返回 [(片段下标, 分数)]，按分数降序。

        同分时按下标排 —— 结果必须稳定：同一句话问两次给出不同的顺序，
        调试的人会以为见了鬼。分数为 0 的（一个词都没命中）直接不要。
        """
        scored = list(enumerate(self.scores(query)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [pair for pair in scored[:k] if pair[1] > 0]
