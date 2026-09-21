# -*- coding: utf-8 -*-
"""模拟候选人 —— 陪练对象。

现在真人是坐在屏幕前的你，但面试要能自动跑起来、能回归测试，
就必须有个"假候选人"来回答。它的逻辑很简单：

  **面试官问什么类型，就回什么类型的答案。**

注意这里的设计：脚本不是「按顺序取第 1、2、3 条」，
而是**按题目去查表**。

为什么？因为 Agent 自己决定问什么、什么顺序。如果脚本是定序数组，
一旦模型这次先问了 HR 面，答案就会全错位 ——
这是"把控制权交给模型"之后必须付出的代价，也是它和写死管线的本质区别。

★ 第二版修正（第一次跑挂了之后改的）：
  第一版只用题目类型（track）当 key，结果是——面试官问「岛屿数量」，
  候选人答「LRU 缓存」，整场答非所问。
  原因：题库的 coding/medium 里躺着 3 道题（LRU、K个一组翻转链表、
  岛屿数量），而 `mock_question_bank_pick` 是 **random.choice** 随机挑一道。
  按 track 索引只能写一份答案，出到哪道全凭运气，必然对不上。

  所以查询优先级改成：**题目 id > track:stage > track**。
  精确的 id 匹配兜住随机性，track 作为模糊兜底。
"""

from __future__ import annotations

from typing import Any


class CandidateSim:
    # ★ 池子抽干之后的"万能应答"。
    #
    #   第 4 次运行就是死在这里：面试官开始自由追问（项目深挖本来就不走题库），
    #   每追问一次就消耗一条 fallback，4 条耗尽后候选人永久返回
    #   "我暂时没有更多要补充的了" —— 面试官再也接不下去，19 轮就草草收尾，
    #   只出了 1 道题、评了 2 次分。
    #
    #   教训：**把主动权交给模型，就必须给它的"自由发挥"准备好兜底资源。**
    #   真人不会因为被多问两句就彻底哑巴，所以这里也不能返回空 ——
    #   改成一组可轮转的含糊应答：既不重复同一句，也永远接得住话。
    _GENERIC = [
        "嗯……这一块我主要是靠实践在做，要说得很系统可能还差点，回去我再整理一下。",
        "我的理解大概是这样，不过更细节的部分我记得不是很清楚了。",
        "这个我确实没有深入想过，平时更多是把功能做出来，原理层面补得不够。",
    ]

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.used_keys: set[str] = set()
        self.fallback: list[str] = list(answers.get("_fallback") or [])
        self.generic_idx = 0

    # -- 内部 ---------------------------------------------------------------

    @staticmethod
    def _keys(question: dict | None) -> list[str]:
        """把一道题映射成脚本里可能的 key，**按精确度从高到低排列**。"""
        if not question:
            return []

        keys: list[str] = []

        # ① 最精确：题目 id。题库随机出题时只有它能对上
        if question.get("id"):
            keys.append(str(question["id"]))

        # ② 次之：HR 面的 stage
        track = question.get("track")
        if track == "hr" and question.get("stage"):
            keys.append(f"hr:{question['stage']}")

        # ③ 兜底：题目类型
        if track:
            keys.append(str(track))

        return keys

    # -- 对外 ---------------------------------------------------------------

    def answer_for(self, question: dict | None) -> str:
        """根据最近一道题，返回候选人的回答。"""
        for key in self._keys(question):
            if key in self.answers and key not in self.used_keys:
                self.used_keys.add(key)
                return str(self.answers[key])

        # 题库外的自由提问（项目深挖、追问）：按顺序取备用回答
        if self.fallback:
            return self.fallback.pop(0)

        # 备用回答也用完了 —— 改用可轮转的万能应答，绝不让对话断在这里
        reply = self._GENERIC[self.generic_idx % len(self._GENERIC)]
        self.generic_idx += 1
        return reply
