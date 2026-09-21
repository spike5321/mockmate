# -*- coding: utf-8 -*-
"""把一次真实运行的轨迹生成一个可交互的「运行回放页」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么要有这个东西？

  面试项目的 Demo 通常是一段终端录屏 GIF。GIF 有三个问题：
  1. 要装 ffmpeg、要人工录、要剪辑压缩，成本高且容易拖延
  2. 缩到 README 宽度后字号小到看不清，只能看出"在滚"
  3. **信息量最低的那部分** —— 终端一闪而过的，恰恰是模型为什么这么决策

  而 traces/ 里本来就存着每一轮的 `thinking`（模型决定下一步做什么的理由）。
  这一页就是把它摆出来：一轮一轮看模型的推理 → 工具调用 → 面试官发言，
  最后接上真实的复盘报告。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
两个设计上的讲究：

 ① **页面是构建产物，不是手写的。**
    这一页里的每一个数字、每一句话都来自 docs/examples/ 里的两个真实文件。
    任何人可以 `python tools/build_replay.py` 重新生成一份、逐字节核对。
    如果页面是手写的 HTML，"这些数据是不是编的"就永远说不清。

 ② **数据内联进 HTML，不用 fetch。**
    浏览器对本地文件（file://）的 fetch 有跨域限制，双击打开会白屏。
    内联之后这一页是**单文件**：能双击打开、能邮件发、能托管到任何静态服务，
    不依赖同目录的其它文件。
    代价是数据被复制了一份 —— 但生成脚本保证了它与源文件同步。

用法：
    python tools/build_replay.py                      # 用默认的 run14
    python tools/build_replay.py --trace traces/x.json --report scenarios/y.report.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRACE = ROOT / "docs" / "examples" / "run14_trace.json"
DEFAULT_REPORT = ROOT / "docs" / "examples" / "run14_report.json"
OUT_PATH = ROOT / "docs" / "replay" / "index.html"

#: 工具的「人话」注释 —— 回放页里给每个工具调用配一句解释，
#: 让不懂这个项目的人也知道这一步在干什么。
TOOL_NOTES = {
    "read_resume": "读候选人简历",
    "fetch_jd": "读目标岗位 JD",
    "search_jd_kb": "检索岗位知识库（向量检索）",
    "pick_question": "从题库取一道题",
    "log_custom_question": "登记自拟题（比如项目深挖）",
    "score_answer": "给这一题的回答打分",
    "submit_report": "提交并落盘复盘报告",
    "end_interview": "结束整场面试",
}

#: 雷达维度中文名
RADAR_LABELS = {
    "tech_depth": "技术深度",
    "system_design": "系统设计",
    "project_pitch": "项目表达",
    "coding": "算法编码",
    "behavioral": "行为面",
    "motivation_fit": "动机匹配",
}

TRACK_LABELS = {
    "coding": "算法题",
    "system_design": "系统设计",
    "project": "项目深挖",
    "hr": "HR 行为面",
}

DIM_LABELS = {
    "data_structure_choice": "结构选型",
    "time_complexity": "复杂度",
    "edge_cases": "边界条件",
    "code_clarity": "代码清晰度",
    "correctness": "思路正确",
    "complexity": "复杂度",
    "data_model": "数据模型",
    "api_design": "接口设计",
    "scalability": "可扩展性",
    "consistency": "一致性",
    "tradeoff_analysis": "权衡取舍",
    "completeness": "方案完整度",
    "specificity": "具体程度",
    "technical_depth": "技术深度",
    "impact": "结果说明",
    "reflection": "反思意识",
    "structure": "条理性",
    "highlight_match": "亮点匹配",
    "authenticity": "真实度",
    "time_control": "信息密度",
    "sincerity": "真诚度",
    "depth": "思考深度",
    "match": "岗位契合",
    "stress_resistance": "情绪稳定",
    "analysis": "分析能力",
    "communication": "表达清晰",
    "decision_making": "决策执行",
    "clarity": "表达条理",
    "feasibility": "计划可行性",
    "motivation": "内在动机",
    "relevance": "切题程度",
    "substance": "实质信息",
    "fit": "岗位匹配",
}


def load_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"找不到数据文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_payload(trace_path: Path, report_path: Path) -> dict:
    trace_doc = load_json(trace_path)
    report = load_json(report_path)

    turns = []
    for item in trace_doc.get("trace", []):
        turns.append(
            {
                "turn": item.get("turn"),
                "tools": item.get("tool_calls") or [],
                "thinking": " ".join((item.get("thinking") or "").split()),
                "content": " ".join((item.get("content") or "").split()),
            }
        )

    rounds = []
    for r in report.get("rounds", []):
        dims = r.get("dimensions") or {}
        rounds.append(
            {
                "id": r.get("question_id"),
                "track": r.get("track"),
                "question": r.get("question"),
                "answer": r.get("answer") or "",
                "score": r.get("score"),
                "comment": r.get("comment") or "",
                "source": r.get("source"),
                "dimensions": dims,
                "evidence": (r.get("evidence_refs") or [])[:2],
            }
        )

    return {
        "meta": {
            "candidate": report.get("candidate"),
            "role": report.get("target_role"),
            "company": report.get("target_company"),
            "date": report.get("interview_date"),
            "generated_by": report.get("generated_by"),
            "built_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "trace_file": trace_path.name,
            "report_file": report_path.name,
        },
        "summary": trace_doc.get("summary", {}),
        "turns": turns,
        "report": {
            "overall_score": report.get("overall_score"),
            "question_avg": report.get("question_avg"),
            "track_avg": report.get("track_avg") or {},
            "radar": report.get("radar") or {},
            "verdict": report.get("verdict") or "",
            "highlights": report.get("highlights") or [],
            "weaknesses": report.get("weaknesses") or [],
            "improvements": report.get("improvements") or [],
            "plan": report.get("next_7_days_plan") or [],
        },
        "rounds": rounds,
        "labels": {
            "tools": TOOL_NOTES,
            "radar": RADAR_LABELS,
            "track": TRACK_LABELS,
            "dim": DIM_LABELS,
        },
    }


# ===========================================================================
# 页面模板
# ===========================================================================

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MockMate 运行回放 · 自研 Agent 调度循环</title>
<style>
:root{
  --bg:#ffffff; --bg2:#f6f5f2; --bg3:#eeede8;
  --fg:#191918; --fg2:#5f5e5a; --fg3:#8d8b83;
  --line:rgba(0,0,0,.12); --line2:rgba(0,0,0,.24);
  --accent:#185fa5; --accent-bg:#e6f1fb;
  --ok:#3b6d11; --ok-bg:#eaf3de;
  --warn:#a32d2d; --warn-bg:#fcebeb;
  --amber:#854f0b; --amber-bg:#faeeda;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#1b1b1a; --bg2:#262625; --bg3:#302f2e;
    --fg:#efeee9; --fg2:#b4b2a9; --fg3:#8d8b83;
    --line:rgba(255,255,255,.14); --line2:rgba(255,255,255,.26);
    --accent:#85b7eb; --accent-bg:#0c447c;
    --ok:#c0dd97; --ok-bg:#27500a;
    --warn:#f09595; --warn-bg:#501313;
    --amber:#fac775; --amber-bg:#412402;
  }
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
}
.wrap{max-width:920px; margin:0 auto; padding:2.5rem 1.25rem 4rem}
h1{font-size:22px; font-weight:600; margin:0 0 6px}
h2{font-size:16px; font-weight:600; margin:2.5rem 0 .75rem}
h3{font-size:14px; font-weight:600; margin:0 0 8px}
p{margin:.5rem 0}
.muted{color:var(--fg2)}
.dim{color:var(--fg3)}
.small{font-size:13px}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
code{background:var(--bg3); border-radius:4px; padding:1px 5px; font-size:12.5px}
a{color:var(--accent)}
.card{background:var(--bg2); border:1px solid var(--line); border-radius:12px; padding:1rem 1.25rem}
.grid{display:grid; gap:10px}
.stats{grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.stat{background:var(--bg2); border-radius:10px; padding:.85rem 1rem}
.stat .k{font-size:12.5px; color:var(--fg2)}
.stat .v{font-size:23px; font-weight:600; line-height:1.35}
.stat .u{font-size:12.5px; color:var(--fg2); font-weight:400}
.strip{display:flex; gap:3px; margin:.5rem 0}
.tick{flex:1 1 0; height:30px; border-radius:4px; cursor:pointer; border:1px solid var(--line); background:var(--bg3); padding:0; display:flex; align-items:flex-end; justify-content:center; font-size:10px; color:var(--fg3)}
.tick.tool{background:var(--accent-bg); border-color:var(--accent)}
.tick.end{background:var(--ok-bg); border-color:var(--ok)}
.tick.on{outline:2px solid var(--accent); outline-offset:1px}
.controls{display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:.85rem 0}
button{font:inherit; font-size:13px; padding:5px 12px; border-radius:8px; border:1px solid var(--line2); background:transparent; color:var(--fg); cursor:pointer}
button:hover{background:var(--bg3)}
button.primary{border-color:var(--accent); color:var(--accent)}
.chip{font-size:12px; font-family:ui-monospace,Consolas,monospace; background:var(--accent-bg); color:var(--accent); border-radius:6px; padding:3px 8px; display:inline-block; margin:0 6px 6px 0}
.chip.plain{font-family:inherit; background:var(--bg3); color:var(--fg2)}
.quote{background:var(--bg); border-left:3px solid var(--line2); padding:.5rem .85rem; border-radius:0 8px 8px 0; margin:.35rem 0}
.lbl{font-size:12.5px; color:var(--fg2); margin:.85rem 0 .2rem}
table{width:100%; border-collapse:collapse; font-size:13px}
th,td{text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top}
th{color:var(--fg2); font-weight:500; font-size:12.5px}
.bar{height:7px; border-radius:4px; background:var(--bg3); overflow:hidden; min-width:44px}
.bar i{display:block; height:100%; background:var(--accent)}
.scorebad{font-weight:600; font-size:15px}
.s0{color:var(--warn)} .s5{color:var(--amber)} .s7{color:var(--ok)}
ul{margin:.35rem 0 .35rem 1.1rem; padding:0}
li{margin:.2rem 0}
.radarwrap{display:flex; gap:1.5rem; flex-wrap:wrap; align-items:center}
footer{margin-top:3rem; padding-top:1.25rem; border-top:1px solid var(--line); font-size:12.5px; color:var(--fg3)}
@media (max-width:560px){ .wrap{padding:1.5rem 1rem 3rem} }
</style>
</head>
<body>
<div class="wrap">
  <h1>MockMate · 运行回放</h1>
  <p class="muted small">
    一场模拟面试的完整决策轨迹。每一轮都能看到<b>模型为什么决定下一步做什么</b>，
    以及它实际调用了哪个工具 —— 最后接上真实的复盘报告。
  </p>
  <p class="dim small" id="meta"></p>

  <h2>① 这一次运行</h2>
  <div class="grid stats" id="stats"></div>

  <h2>② 决策密度</h2>
  <p class="muted small">
    每一格是一轮。深色格 = 这一轮模型发起了工具调用，浅色格 = 纯对话轮。
    点任意一格可以跳过去看那一轮发生了什么。
  </p>
  <div class="strip" id="strip"></div>
  <div class="controls">
    <button class="primary" id="play">播放</button>
    <button id="prev">← 上一轮</button>
    <button id="next">下一轮 →</button>
    <span class="dim small" id="pos"></span>
    <span class="dim small">（也可以用键盘 ← → 翻页）</span>
  </div>

  <div class="card" id="detail"></div>

  <h2>③ 复盘报告</h2>
  <div class="card">
    <div class="radarwrap">
      <div id="radar"></div>
      <div style="flex:1 1 260px; min-width:220px">
        <div class="grid stats" style="grid-template-columns:repeat(2,1fr)">
          <div class="stat"><div class="k">模型给的总体分</div><div class="v" id="overall"></div></div>
          <div class="stat"><div class="k">系统算的逐题均分</div><div class="v" id="avg"></div></div>
        </div>
        <p class="small muted" id="anchor-note" style="margin-top:.75rem"></p>
      </div>
    </div>
    <p class="quote" id="verdict" style="margin-top:1rem"></p>
  </div>

  <h3 style="margin-top:1.5rem">逐题评分明细</h3>
  <p class="muted small">
    总分不是模型拍的：模型只判每个维度的达成度，加权计算由代码完成。
    下面每一行都能展开看到维度分和判分依据原文。
  </p>
  <div id="rounds"></div>

  <h3 style="margin-top:1.5rem">亮点 / 短板 / 改进建议</h3>
  <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">
    <div class="card"><h3>亮点</h3><ul id="highlights"></ul></div>
    <div class="card"><h3>短板</h3><ul id="weaknesses"></ul></div>
    <div class="card"><h3>改进建议</h3><ul id="improvements"></ul></div>
  </div>

  <h3 style="margin-top:1.5rem">7 天训练计划</h3>
  <div class="card"><ul id="plan"></ul></div>

  <footer id="footer"></footer>
</div>

<script type="application/json" id="payload">__PAYLOAD__</script>
<script>
(function(){
  var DATA = JSON.parse(document.getElementById("payload").textContent);
  var L = DATA.labels, S = DATA.summary, T = DATA.turns;
  var cur = 0, timer = null;

  var esc = function(s){
    return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  };
  var num = function(v){ return v == null ? "—" : String(Math.round(v)); };
  var scoreClass = function(v){ return v >= 7 ? "s7" : (v >= 4 ? "s5" : "s0"); };

  document.getElementById("meta").textContent =
    "候选人 " + (DATA.meta.candidate || "?") + " · 目标 " + (DATA.meta.role || "?") +
    " · 面试日期 " + (DATA.meta.date || "?") + " · 生成于 " + DATA.meta.built_at;

  var stats = [
    ["总轮数", S.turns, ""],
    ["工具调用", S.tool_calls, "次"],
    ["出题数量", S.questions_asked, "题"],
    ["逐题评分", S.answers_scored, "题"],
    ["LLM 评分占比", (S.answers_scored ? Math.round(S.scored_by_llm / S.answers_scored * 100) : 0), "%"],
    ["逐题均分", S.avg_score, "/ 10"],
    ["耗时", S.elapsed_sec, "秒"],
    ["LLM 调用", S.llm_calls, "次"]
  ];
  document.getElementById("stats").innerHTML = stats.map(function(r){
    return '<div class="stat"><div class="k">' + esc(r[0]) + '</div><div class="v">' +
      esc(r[1]) + (r[2] ? '<span class="u"> ' + esc(r[2]) + '</span>' : '') + '</div></div>';
  }).join("");

  var strip = document.getElementById("strip");
  T.forEach(function(t, i){
    var b = document.createElement("button");
    b.className = "tick" + (t.tools.length ? " tool" : "") +
      (t.tools.indexOf("end_interview") >= 0 ? " end" : "");
    b.title = "第 " + t.turn + " 轮" + (t.tools.length ? " · " + t.tools.join(", ") : " · 纯对话");
    b.textContent = t.turn;
    b.onclick = function(){ cur = i; render(); };
    strip.appendChild(b);
  });

  function render(){
    var t = T[cur];
    for (var i = 0; i < strip.children.length; i++){
      strip.children[i].classList.toggle("on", i === cur);
    }
    document.getElementById("pos").textContent = "第 " + t.turn + " / " + T.length + " 轮";

    var toolsHtml = t.tools.length
      ? t.tools.map(function(n){
          var note = L.tools[n] ? ' <span class="dim">· ' + esc(L.tools[n]) + "</span>" : "";
          return '<span class="chip">' + esc(n) + "()</span>" + note;
        }).join("<br>")
      : '<span class="chip plain">本轮没有工具调用</span>';

    var thinking = t.thinking
      ? esc(t.thinking)
      : '<span class="dim">（轨迹里这一轮没有推理文本 —— 模型直接发起了工具调用）</span>';
    var content = t.content
      ? esc(t.content)
      : '<span class="dim">（这一轮模型没有输出对话文本）</span>';

    document.getElementById("detail").innerHTML =
      '<h3>第 ' + t.turn + ' 轮</h3>' +
      '<div style="margin:.5rem 0 .25rem">' + toolsHtml + '</div>' +
      '<div class="lbl">模型推理（thinking）</div>' +
      '<div class="quote small">' + thinking + '</div>' +
      '<div class="lbl">面试官对候选人说的话</div>' +
      '<div class="quote small">' + content + '</div>';
  }

  document.getElementById("prev").onclick = function(){ cur = (cur > 0 ? cur - 1 : T.length - 1); render(); };
  document.getElementById("next").onclick = function(){ cur = (cur < T.length - 1 ? cur + 1 : 0); render(); };

  var playBtn = document.getElementById("play");
  playBtn.onclick = function(){
    if (timer){ clearInterval(timer); timer = null; playBtn.textContent = "播放"; return; }
    playBtn.textContent = "暂停";
    timer = setInterval(function(){
      if (cur >= T.length - 1){ clearInterval(timer); timer = null; playBtn.textContent = "播放"; return; }
      cur++; render();
    }, 900);
  };

  document.addEventListener("keydown", function(e){
    if (e.key === "ArrowLeft"){ cur = cur > 0 ? cur - 1 : T.length - 1; render(); }
    if (e.key === "ArrowRight"){ cur = cur < T.length - 1 ? cur + 1 : 0; render(); }
  });

  var R = DATA.report;
  document.getElementById("overall").innerHTML = num(R.overall_score) + '<span class="u"> / 100</span>';
  document.getElementById("avg").innerHTML = (R.question_avg == null ? "—" : R.question_avg) + '<span class="u"> / 10</span>';

  var anchorDiff = (R.overall_score != null && R.question_avg != null)
    ? Math.abs(R.overall_score - R.question_avg * 10) : null;
  document.getElementById("anchor-note").textContent = anchorDiff == null
    ? ""
    : (anchorDiff <= 10
        ? "两者自洽（相差 " + Math.round(anchorDiff) + " 分）—— 模型填的总体分有逐题数据支撑。"
        : "⚠ 两者相差 " + Math.round(anchorDiff) + " 分，说明模型填的总体分与逐题表现不一致 —— 这个提示是系统自动算的，不是模型自说自话。");

  document.getElementById("verdict").textContent = R.verdict;
  document.getElementById("highlights").innerHTML = R.highlights.map(function(s){ return "<li>" + esc(s) + "</li>"; }).join("") || "<li class='dim'>（无）</li>";
  document.getElementById("weaknesses").innerHTML = R.weaknesses.map(function(s){ return "<li>" + esc(s) + "</li>"; }).join("") || "<li class='dim'>（无）</li>";
  document.getElementById("improvements").innerHTML = R.improvements.map(function(s){ return "<li>" + esc(s) + "</li>"; }).join("") || "<li class='dim'>（无）</li>";
  document.getElementById("plan").innerHTML = R.plan.map(function(d){
    return "<li><b>第 " + esc(d.day) + " 天</b> " + esc(d.task) + "</li>";
  }).join("") || "<li class='dim'>（无）</li>";

  var NS = "http://www.w3.org/2000/svg";
  (function drawRadar(){
    var keys = Object.keys(R.radar);
    // ★ 画布尺寸不能太小：六个标签是环状排布的，左右两侧的标签会向外伸出
    //   （"系统设计 55" 这种一个就有 60px 宽）。第一版画布 250px 直接把两侧
    //   标签裁成了"系统设"—— SVG 默认会按视口裁切，不会自动留白。
    var W = 340, H = 290, cx = W / 2, cy = H / 2 - 3, rad = 76;
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "六维能力雷达图");

    var pt = function(i, r){
      var ang = -Math.PI / 2 + i * 2 * Math.PI / keys.length;
      return [cx + Math.cos(ang) * r, cy + Math.sin(ang) * r];
    };

    [0.25, 0.5, 0.75, 1].forEach(function(f){
      var pts = keys.map(function(_, i){ var p = pt(i, rad * f); return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
      var poly = document.createElementNS(NS, "polygon");
      poly.setAttribute("points", pts);
      poly.setAttribute("fill", "none");
      poly.setAttribute("stroke", "currentColor");
      poly.setAttribute("stroke-opacity", "0.18");
      svg.appendChild(poly);
    });

    keys.forEach(function(_, i){
      var p = pt(i, rad);
      var ln = document.createElementNS(NS, "line");
      ln.setAttribute("x1", cx); ln.setAttribute("y1", cy);
      ln.setAttribute("x2", p[0]); ln.setAttribute("y2", p[1]);
      ln.setAttribute("stroke", "currentColor");
      ln.setAttribute("stroke-opacity", "0.18");
      svg.appendChild(ln);
    });

    var shape = keys.map(function(k, i){
      var p = pt(i, rad * Math.max(0, Math.min(100, R.radar[k])) / 100);
      return p[0].toFixed(1) + "," + p[1].toFixed(1);
    }).join(" ");
    var poly = document.createElementNS(NS, "polygon");
    poly.setAttribute("points", shape);
    // 用 style 而不是 fill/stroke 属性写 CSS 变量：SVG 表现属性对 var() 的支持
    // 各浏览器不完全一致，走 CSS 更稳。
    poly.setAttribute("style", "fill:var(--accent);fill-opacity:.22;stroke:var(--accent);stroke-width:2");
    svg.appendChild(poly);

    keys.forEach(function(k, i){
      var p = pt(i, rad + 18);
      var t = document.createElementNS(NS, "text");
      t.setAttribute("x", p[0]); t.setAttribute("y", p[1]);
      t.setAttribute("text-anchor", p[0] < cx - 4 ? "end" : (p[0] > cx + 4 ? "start" : "middle"));
      t.setAttribute("dominant-baseline", "middle");
      t.setAttribute("font-size", "11.5");
      t.setAttribute("fill", "currentColor");
      t.textContent = (L.radar[k] || k) + " " + num(R.radar[k]);
      svg.appendChild(t);
    });

    document.getElementById("radar").appendChild(svg);
  })();

  document.getElementById("rounds").innerHTML = DATA.rounds.map(function(r, i){
    var dims = Object.keys(r.dimensions).map(function(k){
      var v = r.dimensions[k];
      return '<div style="display:flex;align-items:center;gap:8px;margin:.25rem 0">' +
        '<span class="small" style="width:88px;color:var(--fg2)">' + esc(L.dim[k] || k) + "</span>" +
        '<span class="bar" style="flex:1 1 auto"><i style="width:' + Math.round(Math.max(0, Math.min(1, v)) * 100) + '%"></i></span>' +
        '<span class="small mono dim" style="width:30px;text-align:right">' + Number(v).toFixed(2) + "</span></div>";
    }).join("") || '<span class="dim small">（这一题走了规则降级，没有维度分）</span>';

    var ev = r.evidence.length
      ? "<div class='lbl'>判分依据（回答原文）</div>" + r.evidence.map(function(e){
          return "<div class='quote small dim'>" + esc(e) + "</div>";
        }).join("")
      : "";

    var srcTag = r.source === "llm"
      ? '<span class="chip">LLM 评分</span>'
      : '<span class="chip plain">规则降级</span>';

    return '<div class="card" style="margin-bottom:10px">' +
      '<div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">' +
        '<b style="font-size:14px">' + esc(r.question) + "</b>" +
        '<span class="small dim">' + esc(L.track[r.track] || r.track) + "</span>" + srcTag +
        '<span style="margin-left:auto" class="scorebad ' + scoreClass(r.score) + '">' + num(r.score) + '<span class="small muted"> / 10</span></span>' +
      "</div>" +
      '<p class="small" style="margin:.5rem 0">' + esc(r.comment) + "</p>" +
      '<details><summary class="small muted" style="cursor:pointer">展开维度得分与判分依据</summary>' +
        '<div style="margin-top:.6rem">' + dims + "</div>" +
        '<div class="lbl">候选人回答（截断）</div>' +
        '<div class="quote small dim">' + esc(r.answer.slice(0, 420)) + (r.answer.length > 420 ? " …" : "") + "</div>" +
        ev +
      "</details></div>";
  }).join("");

  document.getElementById("footer").innerHTML =
    "本页由 <code>python tools/build_replay.py</code> 从 <code>docs/examples/" +
    esc(DATA.meta.trace_file) + "</code> 与 <code>" + esc(DATA.meta.report_file) +
    "</code> 生成，数据未做任何手工修改 —— 可重新生成后逐字节核对。<br>" +
    "报告由 " + esc(DATA.meta.generated_by || "orchestrator") + " 落盘。";

  render();
})();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="从真实运行轨迹生成运行回放页")
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE, help="轨迹 JSON")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="报告 JSON")
    parser.add_argument("--out", type=Path, default=OUT_PATH, help="输出 HTML")
    args = parser.parse_args()

    payload = build_payload(args.trace, args.report)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # 内联 JSON 时必须把 </ 转义掉，否则页面里出现 "</script>" 之类的片段会
    # 提前闭合脚本标签；顺带躲开 <!-- 引发的 HTML 注释怪异模式。
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")

    html = TEMPLATE.replace("__PAYLOAD__", data)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    print(f"已生成 {args.out}")
    print(f"  轮数 {len(payload['turns'])} · 逐题记录 {len(payload['rounds'])} · "
          f"文件大小 {args.out.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
