# -*- coding: utf-8 -*-
"""断点续跑 —— 把"这场面试进行到哪儿了"存下来，挂了能从那儿接着跑。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么要做这个？

run12 的教训：跑到第 17 轮撞上限流，主循环 break，那 17 轮对话白跑了。
后来补了 `submit_partial_report()` 兜底 —— **但那只是"保产物"，不是"保进程"**：
报告出来了，可它是不完整的，而且下一轮你只能从第一轮重新开始。

这一层补的是后者：把对话历史和工具箱状态落盘，
下次 `--resume` 从第 18 轮接着往下问。

★ 一个特别容易漏的点：**messages 里的 tool_calls 必须原样保留**。
   模型看到的是一串"我说要调 X → 工具返回 Y"的记录。如果恢复时把 tool_calls
   的 id 弄丢或者重新编一个，下一轮请求会因为"tool 消息对不上"被接口直接拒绝。
   所以这里对 messages 是**原样存取**，不做任何加工、不裁剪、不重排。

存放位置：`runs/<run_id>.checkpoint.json`（`runs/` 已在 .gitignore 里）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"

# 断点文件的格式版本。换了结构就加一 —— 读到对不上的版本宁可明确报错，
# 也不要猜着解析：断点文件里的东西（对话历史）猜错了，恢复出来的面试是坏的，
# 而且是那种"看着能跑"的坏。
VERSION = 1

_SUFFIX = ".checkpoint.json"


def new_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def path_for(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}{_SUFFIX}"


def save(run_id: str, state: dict) -> Path:
    """原子写入：先写临时文件，再 rename 覆盖。

    ★ 为什么不能直接 write_text：断点文件的写入时机**恰恰是出故障的时候**，
    写到一半被打断就会留下一个坏 JSON，下次 resume 直接读不出来 ——
    那这个功能等于白做。同一分区上的 rename 是原子操作。
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    target = path_for(run_id)
    tmp = target.with_name(target.name + ".tmp")

    payload = dict(state)
    payload["version"] = VERSION
    payload["run_id"] = run_id
    payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return target


def load(run_id: str) -> dict:
    path = path_for(run_id)
    if not path.exists():
        raise FileNotFoundError(f"找不到断点文件：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version")
    if version != VERSION:
        raise ValueError(
            f"断点文件的格式版本是 {version}，当前程序认的是 {VERSION} —— 请重新开始一场"
        )
    return data


def mark_completed(run_id: str, state: dict) -> Path:
    """正常跑完之后标一下 —— 这样 `--resume latest` 不会挑到已经跑完的场次。"""
    updated = dict(state)
    updated["completed"] = True
    return save(run_id, updated)


def latest_unfinished() -> str | None:
    """最近一个没跑完的 run_id；没有就返回 None。"""
    if not RUNS_DIR.exists():
        return None
    candidates: list[tuple[str, str]] = []
    for path in RUNS_DIR.glob(f"*{_SUFFIX}"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue          # 坏文件直接跳过，不能因为它挡着别的场次
        if not data.get("completed"):
            candidates.append((data.get("updated_at", ""), path.name[: -len(_SUFFIX)]))
    if not candidates:
        return None
    return max(candidates)[1]


def describe(run_id: str) -> str:
    """给命令行看的一行摘要。"""
    try:
        data = load(run_id)
    except (FileNotFoundError, ValueError) as exc:
        return f"  {run_id}: 读不出来（{exc}）"
    flag = "已完成" if data.get("completed") else "未完成"
    interrupted = data.get("interrupted") or {}
    extra = f"，中断于「{interrupted.get('reason', '?')}」" if interrupted else ""
    return (
        f"  {run_id}  {data.get('scenario_id', '?')}  "
        f"第 {data.get('turn', 0)} 轮  {flag}{extra}  （{data.get('updated_at', '?')}）"
    )
