# -*- coding: utf-8 -*-
"""模拟候选人 —— 陪练对象。

现在真人是坐在屏幕前的你，但面试要能自动跑起来、能回归测试，
就必须有个"假候选人"来回答。它的逻辑很简单：

  **面试官问什么，就回什么。**

但"什么"这两个字，是三版才想明白的。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三版演进（每一版都是被真实故障逼出来的）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

★ 第一版：按题型（track）查表
  结果是——面试官问「岛屿数量」，候选人答「LRU 缓存」，整场答非所问。
  原因：题库的 coding/medium 里躺着 3 道题，而 `mock_question_bank_pick`
  是 **random.choice** 随机挑一道。按 track 索引只能写一份答案，
  出到哪道全凭运气，必然对不上。

★ 第二版：按题目 id 精确匹配（id > track:stage > track）
  随机性被兜住了。但新的窟窿马上露出来：

    面试官：请说说 LRU 的双向链表节点怎么设计？
    候选人：我用了 Redis 做缓存，QPS 大概 2000 左右。

  因为**追问没有 question_id** —— 项目深挖、追问本来就不走 pick_question，
  `consume_pending()` 返回 None，于是所有追问都掉进同一个 `_fallback` 池，
  池子里装的是"为项目深挖准备的回答"，被用在算法题追问上，驴唇不对马嘴。

  更糟的是那个池子还是**一次性消耗**的：追问四次就抽干，
  候选人从此永久沉默，面试官接不下去，19 轮就草草收尾。

★ 第三版：追问按「话题」取池
    ① 追问池分 coding / system_design / project / hr 四组，取完循环复用；
    ② 话题靠两个线索判断：**面试官的原话** + **上一道题的类型**。
       因为自由追问可能换话题（上一题问算法，这一句突然说"聊聊你的项目"），
       只靠"上一题类型"会一路答错，只靠关键词又会误判，所以两个一起用。

  这版解决了"答非所属话题"，但跑完一轮发现**结果比之前更差**：
  36 轮全耗在一道题上，撞上限强制结束，连报告都没交出来。两个毛病：

    ① **池子内容没对准面试官真会问什么**。
       面试官问「请详细说明短链系统的数据表结构设计」，
       而 system_design 池里装的是"容量估算 / 降级 / 缓存一致性 / 分布式锁"——
       五条没有一条接得住，因为那全是我凭想象写的"高级话题"，
       而面试官问的是最基础的表字段。修法：补上表结构、短码生成算法、
       跳转用 301 还是 302、缓存 key 怎么设计这类具体实现应答。

    ② **池子用完就复读** —— 这个更致命。
       上一版的处理是"加一句衔接语继续复读"，于是候选人一轮一轮重复同样的话，
       面试官以为对方还在认真作答，把同一句话换着花样问了 8 遍。
       修法：池子轮完一圈就切换成**认输应答**
       （"这块我确实答不上来，要不我们换个方向聊？"）。

★ 第四版（当前）：补内容 + 学会认输 + 话题判定收窄
  三条改动，前两条是"池子的问题"，第三条是"判定方式的问题"：

  ① 补内容 —— 池子没对准面试官真会问什么（见上）。
  ② 学会认输 —— 池子用完一圈改说"我答不上来"。
     这是最值得记的一条经验：**模拟候选人必须会"讲不下去"。**
     前两版都在努力让它"永远接得住话"（别沉默、别答错话题），
     但没人想过它也该有"我答不上来"的表现。结果是面试官永远拿不到
     "该换题了"的信号，只能一遍遍重复提问，整场僵在那里。
     真人不会这样 —— 被追问到知识边界时会主动认输、给对面台阶。
  ③ 话题判定收窄 —— 只认"换环节"信号，其余继承上一题。
     第三版的关键词匹配被"缓存"这个词坑了：面试官问 LRU **缓存**（算法题），
     被误判成系统设计，候选人开始背短链系统。领域词跨话题复用，
     靠关键词判话题必然误判，而且词加得越多、撞得越狠。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

两条通用的 Agent 工程经验：

1. **把主动权交给模型，就必须给它"自由发挥"的部分准备好资源。**
   模型可以自由追问（这是自主性），但下游的模拟候选人必须接得住 ——
   否则自主性会变成"说着说着就没人应答了"的僵局。

2. **兜底资源不能只解决"有话可说"，还要能发出"该结束了"的信号。**
   一个永远有答案的对话方，会让循环失去退出条件 ——
   这是 Agent 死循环的一类常见成因，而且它藏在"我给得越多越好"的直觉背后。
"""

from __future__ import annotations

from typing import Any


class CandidateSim:
    # ── 追问话题判定 ────────────────────────────────────────────────────
    #
    # ★ 默认继承上一题的话题；关键词**只用来判一件事**：是不是换到项目环节了。
    #
    #   这块前后错了两次，两次都是"关键词撞车"，值得完整记下来：
    #
    #   第一次：把 coding / system_design 的关键词也放进来（复杂度、缓存、数据库…），
    #           结果面试官追问 LRU **缓存**（算法题）被判成系统设计，
    #           候选人开始背短链系统。
    #
    #   第二次：给 hr 加了"为什么选择"，结果面试官在项目追问里问
    #           "**为什么选择 Redis 而不是 Memcached**"，被判成 HR 话题，
    #           候选人开始讲"我看过大厂技术博客，想去真实环境看看"。
    #
    #   两次的根因是同一个：**同一个说法在不同环节里长得一模一样**。
    #   "为什么选择 Redis" 和 "为什么选择后端方向" 字面上毫无区别；
    #   领域词更是跨话题复用（缓存、数据库、并发，算法题和系统设计题都会提）。
    #   所以关键词判定的可靠性，取决于"这个词会不会在别的话题里出现"，
    #   而技术领域的热门词几乎都会。
    #
    #   ★ 结论：把判据换成**确定的事实** ——
    #     "最近一道正式题目属于哪个环节"是出题工具写下来的状态，不是猜的。
    #     算法题追问永远继承 coding，系统设计题追问永远继承 system_design，
    #     HR 面的题（都走题库，track=hr）追问永远继承 hr —— 全部准确。
    #
    #     唯一需要原话帮忙的是"项目环节"，因为它有两种来源：
    #     ① log_custom_question(track="project") 登记 → 已经显式了，不需要猜；
    #     ② 面试官没登记就直接问 —— 这时"项目 / 简历 / 实习"是安全信号，
    #        因为这些词几乎不会出现在算法题和系统设计的追问里。
    #
    #     （注意 project 和 hr 的区别：项目词是"专属"的，HR 词不是。
    #       所以只留 project，不留 hr。）
    #
    #     而 project 自己的词也要挑 —— "实习"就被删掉了：
    #       HR 面问「希望在这个**实习**中收获什么」，候选人答成了项目内容。
    #       教训同上，判断一个词能不能用作信号，标准是
    #       **"它会不会在别的话题里同样自然地出现"**，而不是"它和这个话题相关"。
    SWITCH_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("project", ("项目", "简历", "校园", "分工")),
    )

    #: 追问池里存在的话题（用来判断"继承来的 track 能不能用"）
    KNOWN_TOPICS = {"coding", "system_design", "project", "hr"}

    #: 话题完全判不出来时的落点。
    #: 选 project 的理由：题库外的自由提问里，项目深挖占比最高。
    DEFAULT_TOPIC = "project"

    #: ★ 追问池轮完一圈之后的"收尾应答"（JSON 里没有 _repeat 时的兜底）。
    #:
    #:   这里是 run7 那次失败的直接修法。
    #:   上一版池子取完之后**加一句衔接语继续复读**，结果是灾难性的：
    #:   面试官问「请详细说明短链系统的数据表结构设计」，
    #:   候选人一轮一轮重复"容量估算 / 缓存一致性 / 分布式锁"，
    #:   面试官以为对方还在认真作答，于是把同一句话换着花样问了 8 遍，
    #:   36 轮全耗在一道题上，最后撞上限强制结束、连报告都没交。
    #:
    #:   问题不在"答案不够多"，而在**候选人不肯认输**。
    #:   真人被追问到答不上来时，会说"这块我确实不熟，要不换个方向"——
    #:   这句话才是面试官等的**换题信号**。模拟候选人没有这个信号，
    #:   面试官就永远卡在原地。所以池子用完一圈，必须切换成认输模式。
    FALLBACK_REPEAT: tuple[str, ...] = (
        "这个点我可能确实讲得比较泛。您问的是具体怎么落地，我确实没有想得那么细，只能说到这个程度了。",
        "抱歉，我可能没抓住您问的重点。这方面我的经验主要停留在「能跑通」的层面，再往细里挖我真的答不上来了。",
        "这一块我确实了解得不够深入，再问下去我大概只能重复刚才说过的话。要不我们换个方向聊？",
        "嗯……我发现自己好像一直在同一个层面上绕。这个问题我确实没有更好的回答了，您看要不要换下一题？",
    )

    #: 连话题池都是空的时的最后兜底（正常情况下不该走到这里）
    FALLBACK_GENERIC: tuple[str, ...] = (
        "嗯……这一块我主要是靠实践在做，要说得很系统可能还差点，回去我再整理一下。",
        "我的理解大概是这样，不过更细节的部分我记得不是很清楚了。",
        "这个我确实没有深入想过，平时更多是把功能做出来，原理层面补得还不够。",
    )

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers

        # 题库题的"用过就不再复用"标记（追问不适用，追问靠计数器轮转）
        self.used_keys: set[str] = set()

        # 追问池：{话题: [应答, ...]}
        # 过滤掉以 "_" 开头的键 —— JSON 不支持注释，我们约定用 "_comment"
        # 这类键写说明，读取时必须显式跳过，否则会当成一个话题去取。
        raw = answers.get("_followups") or {}
        self.followups: dict[str, list[str]] = {
            k: [str(x) for x in v]
            for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, list) and v
        }

        # 追问计数器：{话题: 已取次数}。用计数而不是 pop ——
        # 池子因此永不枯竭（这是第二版"永久沉默"的修法）。
        self.fu_count: dict[str, int] = {}

        # 池子轮完一圈之后改用这个（"我答不上来了"），见 FALLBACK_REPEAT 的注释
        self.repeat_pool: list[str] = [str(x) for x in (answers.get("_repeat") or [])] \
            or list(self.FALLBACK_REPEAT)

        self.generic: list[str] = [str(x) for x in (answers.get("_generic") or [])] \
            or list(self.FALLBACK_GENERIC)
        self.generic_idx = 0

    # -- 断点续跑（阶段 5）--------------------------------------------------

    def dump_state(self) -> dict:
        """导出「取到哪儿了」的进度。

        只存**进度**：答案池、追问池、兜底池本身都能从 answers JSON 重建，
        真正会变的是"用过的题""每个话题的追问取到第几条""兜底池轮到第几条"。
        """
        return {
            "used_keys": sorted(self.used_keys),
            "fu_count": self.fu_count,
            "generic_idx": self.generic_idx,
        }

    def load_state(self, state: dict) -> None:
        if "used_keys" in state:
            self.used_keys = set(state["used_keys"])
        if "fu_count" in state:
            self.fu_count = {str(k): int(v) for k, v in state["fu_count"].items()}
        if "generic_idx" in state:
            self.generic_idx = int(state["generic_idx"])

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

    @classmethod
    def _topic_of(cls, spoken: str, question: dict | None) -> str | None:
        """判断"这一句该按什么话题回答"。

        优先级从高到低：

          1. **换环节信号** —— 原话提到项目 / 简历 / 实习，或 HR 类话题，
             说明面试已经换到别的环节了，切到对应池子。
          2. **继承上一题的类型** —— 追问按定义就是顺着当前话题往深里问，
             所以这才是绝大多数情况的答案，也是最稳的一条。
          3. 都判不出来 → 返回 None，由调用方落到 DEFAULT_TOPIC。
        """
        text = spoken or ""

        for topic, words in cls.SWITCH_SIGNALS:
            if any(w in text for w in words):
                return topic

        track = (question or {}).get("track")
        if track in cls.KNOWN_TOPICS:
            return str(track)

        return None

    def _pick_followup(self, topic: str | None) -> str | None:
        """从话题对应的池子里取一条应答。

        两段式：
          第一圈 —— 按顺序给出该话题下的常规应答，每条角度不同；
          第二圈起 —— 不再复读，换成"这块我确实答不上来"的收尾应答。
        """
        key = topic or self.DEFAULT_TOPIC
        pool = self.followups.get(key) or self.followups.get(self.DEFAULT_TOPIC) or []
        if not pool:
            return None

        i = self.fu_count.get(key, 0)
        self.fu_count[key] = i + 1

        # 第一圈：常规应答
        if i < len(pool):
            return pool[i]

        # 第二圈起：认输。**这是给面试官准备的换题信号**，
        # 复读只会让它以为还能继续追问下去，整场就卡死了。
        j = i - len(pool)
        if self.repeat_pool:
            return self.repeat_pool[j % len(self.repeat_pool)]
        return pool[j % len(pool)]

    # -- 对外 ---------------------------------------------------------------

    def answer_for(self, question: dict | None, spoken: str = "") -> str:
        """返回候选人的回答。

        question —— 最近一道题（可能是 None，表示这是题库外的自由追问）
        spoken   —— 面试官这一轮的原话，用来判断追问是不是换了话题
        """
        # ── ① 题库里的题：id > hr:stage > track，命中即用，且只用一次 ──
        for key in self._keys(question):
            if key in self.answers and key not in self.used_keys:
                self.used_keys.add(key)
                return str(self.answers[key])

        # ── ② 追问：按话题取对应池子 ──
        reply = self._pick_followup(self._topic_of(spoken, question))
        if reply:
            return reply

        # ── ③ 连话题池都是空的：轮转万能应答，绝不让对话断在这里 ──
        reply = self.generic[self.generic_idx % len(self.generic)]
        self.generic_idx += 1
        return reply
