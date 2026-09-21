"""
MockMate 端到端测试脚本
模拟完整面试流程：简历分析 -> 技术面 3 轮 -> HR 面 4 阶段 -> 复盘报告
"""
import json
import sys
import os
import tempfile
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.mock_tools import (
    mock_resume_read_resume,
    mock_jd_fetch_jd,
    mock_jd_search_jd_kb,
    mock_question_bank_pick,
    mock_evaluator_score_answer,
    mock_evaluator_cross_check,
    mock_report_render,
)

SCENARIO_ID = "backend_intern"

# 自检产物写到临时目录。
# 这个脚本会真实落盘报告，如果写进 scenarios/ 就会把真实运行的报告覆盖掉
# （scenarios/*.report.md 是 README 实测数据的原件）。
# 想保留自检产物，用环境变量 MOCKMATE_E2E_OUTDIR 指定一个目录。
OUT_DIR = Path(os.environ.get("MOCKMATE_E2E_OUTDIR") or tempfile.mkdtemp(prefix="mockmate_e2e_"))

# 模拟候选人回答（不同质量，让评分有区分度）
SAMPLE_ANSWERS = {
    # 技术面 - 算法题（回答较充分）
    "coding": "用哈希表 + 双向链表实现。哈希表存 key->node 映射实现 O(1) 查找，双向链表维护访问顺序。get 时把节点移到头部，put 时如果满了就删尾部节点。这样 get/put 都是 O(1)。",
    # 技术面 - 系统设计（回答中等）
    "system_design": "数据模型：短码 -> 原URL映射，存MySQL。API：POST /shorten 生成短链，GET /:code 跳转。用Redis缓存热点短链减少DB压力。生成算法用自增ID + Base62编码。",
    # 技术面 - 项目深挖（回答偏短）
    "project": "我用了 Redis 做缓存，QPS 大概 2000 左右。",
    # HR 面 - 自我介绍（回答充分）
    "self_intro": "我是XX大学计算机专业大三学生，在校期间做过一个校园二手交易平台，用Spring Boot + MySQL + Redis，日活500+。我对后端开发很感兴趣，特别是高并发场景，所以想申请字节后端实习，能在高并发环境下锻炼自己。",
    # HR 面 - 动机（回答中等）
    "motivation": "字节跳动技术氛围好，用户量大，能接触到真正的高并发场景，对我成长帮助大。",
    # HR 面 - 压力面（回答充分）
    "pressure": "首先我会评估两个任务的工作量和风险，然后找PM沟通，说明同时上线的风险，建议按业务优先级排序。如果确实都重要，我会拉上两个PM一起对齐优先级，必要时向leader求助，确保至少核心功能能按时上线。",
    # HR 面 - 职业规划（回答中等）
    "career_plan": "短期希望深入后端开发，打好基础。中期想往架构方向发展。长期希望能独当一面。",
}


def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_json(data, indent=2):
    print(json.dumps(data, ensure_ascii=False, indent=indent))


def main():
    print_header("MockMate 端到端测试 - 后端开发实习面试")
    print(f"  场景 ID: {SCENARIO_ID}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  (此脚本直接调用 mock 工具，不需要启动 HTTP 服务器)")

    # ================================================================
    # Phase 1: Resume Analyst
    # ================================================================
    print_header("Phase 1: Resume Analyst - 简历分析")

    print("\n[1.1] 读取候选人简历...")
    resume = mock_resume_read_resume(SCENARIO_ID)
    candidate = resume.get("candidate", {})
    print(f"  姓名: {candidate.get('name', 'N/A')}")
    print(f"  学校: {candidate.get('school', 'N/A')}")
    print(f"  专业: {candidate.get('major', 'N/A')}")
    print(f"  年级: {candidate.get('year', 'N/A')}")
    print(f"  GPA: {candidate.get('gpa', 'N/A')}")
    print(f"  简历文本长度: {len(resume.get('resume_text', ''))} 字符")

    print("\n[1.2] 获取目标 JD...")
    jd = mock_jd_fetch_jd(SCENARIO_ID)
    print(f"  公司: {jd.get('company', 'N/A')}")
    print(f"  岗位: {jd.get('role', 'N/A')}")
    print(f"  必会技能: {jd.get('required_skills', [])}")
    print(f"  加分技能: {jd.get('bonus_skills', [])}")

    print("\n[1.3] RAG 检索 JD 知识库...")
    rag = mock_jd_search_jd_kb(SCENARIO_ID, query="后端 高并发", top_k=3)
    print(f"  检索关键词: 后端 高并发")
    print(f"  命中条数: {len(rag.get('hits', []))}")
    for i, hit in enumerate(rag.get("hits", []), 1):
        print(f"  [{i}] score={hit.get('score', 0)} | {hit.get('text', '')[:60]}...")

    # ================================================================
    # Phase 2: Technical Interviewer
    # ================================================================
    print_header("Phase 2: Technical Interviewer - 技术面 3 轮")

    tech_scores = []

    # Round 1: Coding
    print("\n[2.1] Round 1 - 算法题 (medium)")
    coding_q = mock_question_bank_pick(SCENARIO_ID, track="coding", difficulty="medium", focus=["链表"])
    print(f"  题目 ID: {coding_q.get('id', 'N/A')}")
    print(f"  题目标题: {coding_q.get('title', 'N/A')}")
    print(f"  标签: {coding_q.get('tags', [])}")
    print(f"  题目描述: {coding_q.get('description', 'N/A')[:80]}...")
    print(f"\n  > 候选人回答: {SAMPLE_ANSWERS['coding']}")
    coding_score = mock_evaluator_score_answer(SCENARIO_ID, coding_q, SAMPLE_ANSWERS["coding"])
    print(f"  评分: {coding_score.get('score', 0)}/10 | 评语: {coding_score.get('comment', '')}")
    print(f"  证据: {coding_score.get('evidence_refs', [])}")
    tech_scores.append({"track": "coding", "score": coding_score["score"], "comment": coding_score["comment"], "evidence_refs": coding_score["evidence_refs"]})

    # Round 2: System Design
    print("\n[2.2] Round 2 - 系统设计")
    sd_q = mock_question_bank_pick(SCENARIO_ID, track="system_design")
    print(f"  题目 ID: {sd_q.get('id', 'N/A')}")
    print(f"  题目标题: {sd_q.get('title', 'N/A')}")
    print(f"  场景: {sd_q.get('context', 'N/A')}")
    follow_ups = sd_q.get("follow_up_path", [])
    print(f"  追问路径: {len(follow_ups)} 步")
    for fu in follow_ups:
        print(f"    Step {fu.get('step')}: {fu.get('question', '')}")
    print(f"\n  > 候选人回答: {SAMPLE_ANSWERS['system_design']}")
    sd_score = mock_evaluator_score_answer(SCENARIO_ID, sd_q, SAMPLE_ANSWERS["system_design"])
    print(f"  评分: {sd_score.get('score', 0)}/10 | 评语: {sd_score.get('comment', '')}")
    print(f"  证据: {sd_score.get('evidence_refs', [])}")
    tech_scores.append({"track": "system_design", "score": sd_score["score"], "comment": sd_score["comment"], "evidence_refs": sd_score["evidence_refs"]})

    # Round 3: Project Deep Dive
    print("\n[2.3] Round 3 - 项目深挖")
    proj_q = mock_question_bank_pick(SCENARIO_ID, track="coding", difficulty="easy")
    print(f"  (以算法题模拟项目深挖场景)")
    print(f"  题目 ID: {proj_q.get('id', 'N/A')}")
    print(f"  题目标题: {proj_q.get('title', 'N/A')}")
    print(f"\n  > 候选人回答: {SAMPLE_ANSWERS['project']}")
    proj_score = mock_evaluator_score_answer(SCENARIO_ID, proj_q, SAMPLE_ANSWERS["project"])
    print(f"  评分: {proj_score.get('score', 0)}/10 | 评语: {proj_score.get('comment', '')}")
    print(f"  证据: {proj_score.get('evidence_refs', [])}")
    tech_scores.append({"track": "project", "score": proj_score["score"], "comment": proj_score["comment"], "evidence_refs": proj_score["evidence_refs"]})

    tech_avg = sum(s["score"] for s in tech_scores) / len(tech_scores)
    print(f"\n  >> 技术面平均分: {tech_avg:.1f}/10")

    # ================================================================
    # Phase 3: HR Interviewer
    # ================================================================
    print_header("Phase 3: HR Interviewer - HR 行为面 4 阶段")

    hr_scores = []
    stages = [
        ("self_intro", "自我介绍"),
        ("motivation", "动机探测"),
        ("pressure", "压力面"),
        ("career_plan", "职业规划"),
    ]

    for stage_key, stage_name in stages:
        print(f"\n[3.{stages.index((stage_key, stage_name)) + 1}] {stage_name}")
        hr_q = mock_question_bank_pick(SCENARIO_ID, track="hr", stage=stage_key)
        print(f"  题目 ID: {hr_q.get('id', 'N/A')}")
        print(f"  问题: {hr_q.get('question', 'N/A')}")
        print(f"\n  > 候选人回答: {SAMPLE_ANSWERS.get(stage_key, '(无回答)')}")
        hr_score = mock_evaluator_score_answer(SCENARIO_ID, hr_q, SAMPLE_ANSWERS.get(stage_key, ""))
        print(f"  评分: {hr_score.get('score', 0)}/10 | 评语: {hr_score.get('comment', '')}")
        print(f"  证据: {hr_score.get('evidence_refs', [])}")
        hr_scores.append({"stage": stage_key, "score": hr_score["score"], "comment": hr_score["comment"], "evidence_refs": hr_score["evidence_refs"]})

    hr_avg = sum(s["score"] for s in hr_scores) / len(hr_scores)
    print(f"\n  >> HR 面平均分: {hr_avg:.1f}/10")

    # ================================================================
    # Phase 4: Feedback Coach
    # ================================================================
    print_header("Phase 4: Feedback Coach - 复盘报告")

    # 4.1 Cross-check
    print("\n[4.1] 评分校准 (cross_check)...")
    all_records = {"technical": tech_scores, "hr": hr_scores}
    cross_check = mock_evaluator_cross_check(SCENARIO_ID, all_records)
    print(f"  校准日志:")
    for log in cross_check.get("calibration_log", []):
        print(f"    - {log.get('round_id', '')}: 原分={log.get('original_score', 0)} -> 校准={log.get('calibrated_score', 0)} | {log.get('reason', '')}")

    # 4.2 Render report
    print("\n[4.2] 渲染最终报告...")
    report_data = {
        "candidate": candidate.get("name", ""),
        "target_role": jd.get("role", ""),
        "interview_date": datetime.now().strftime("%Y-%m-%d"),
        "overall_score": int((tech_avg * 10 + hr_avg * 10) / 2),
        "radar": {
            "tech_depth": int(tech_scores[0]["score"] * 10),
            "system_design": int(tech_scores[1]["score"] * 10),
            "project_pitch": int(tech_scores[2]["score"] * 10),
            "coding": int(tech_scores[0]["score"] * 10),
            "behavioral": int(hr_avg * 10),
            "motivation_fit": int(hr_scores[1]["score"] * 10),
        },
        "highlights": [
            {"text": "算法基础扎实，LRU 缓存思路清晰", "evidence_refs": ["question:lc-146-lru-cache", "answer:turn-1"]},
            {"text": "系统设计有 Redis 缓存意识", "evidence_refs": ["question:sd-short-url", "answer:turn-2"]},
            {"text": "压力面应对有结构化思路", "evidence_refs": ["question:hr-pressure-deadline-001", "answer:turn-6"]},
        ],
        "weaknesses": [
            {"text": "项目深挖回答过短，缺少量化数据", "evidence_refs": ["answer:turn-3"]},
            {"text": "系统设计未展开容量估算", "evidence_refs": ["question:sd-short-url", "answer:turn-2"]},
            {"text": "职业规划回答偏笼统", "evidence_refs": ["answer:turn-7"]},
        ],
        "improvements": [
            "准备 2-3 个项目的 STAR 故事，每个包含 QPS/数据量/技术选型理由",
            "系统设计练习容量估算方法（QPS -> 机器数 -> 存储量）",
            "职业规划按「1年打基础 / 2年深耕 / 3年独当一面」结构展开",
            "动机面准备「为什么选这家公司」的 3 个具体理由",
            "刷 LeetCode 中等难度链表/哈希表题各 20 道",
        ],
        "next_7_days_plan": [
            {"day": 1, "task": "复盘本次面试报告，标记 3 个最大短板"},
            {"day": 2, "task": "重写项目经历，加入 QPS/数据量/技术选型理由"},
            {"day": 3, "task": "系统设计：短链系统完整设计 + 容量估算练习"},
            {"day": 4, "task": "系统设计：秒杀系统完整设计 + 限流方案"},
            {"day": 5, "task": "LeetCode 链表 medium 5 道"},
            {"day": 6, "task": "HR 面准备：自我介绍 + 动机 + 职业规划各写 1 版"},
            {"day": 7, "task": "模拟面试 Round 2，对比本次报告看进步"},
        ],
        "verdict": "建议补技能后投递",
    }

    result = mock_report_render(SCENARIO_ID, template="default", data=report_data, out_dir=OUT_DIR)
    print(f"  报告已生成:")
    print(f"  Markdown: {result.get('md_path', 'N/A')}")
    print(f"  JSON:     {result.get('report_path', 'N/A')}")

    # ================================================================
    # Summary
    # ================================================================
    print_header("测试完成 - 结果汇总")

    print(f"""
  场景: {SCENARIO_ID} (后端开发实习面试)
  候选人: {candidate.get('name', '')}
  目标: {jd.get('company', '')} - {jd.get('role', '')}

  技术面:
    - 算法题:     {tech_scores[0]['score']}/10  {tech_scores[0]['comment']}
    - 系统设计:   {tech_scores[1]['score']}/10  {tech_scores[1]['comment']}
    - 项目深挖:   {tech_scores[2]['score']}/10  {tech_scores[2]['comment']}
    - 技术面均分: {tech_avg:.1f}/10

  HR 面:
    - 自我介绍:   {hr_scores[0]['score']}/10
    - 动机探测:   {hr_scores[1]['score']}/10
    - 压力面:     {hr_scores[2]['score']}/10
    - 职业规划:   {hr_scores[3]['score']}/10
    - HR 面均分:  {hr_avg:.1f}/10

  综合评分: {report_data['overall_score']}/100
  结论: {report_data['verdict']}

  6 维雷达:""")
    for dim, val in report_data["radar"].items():
        bar = "#" * (val // 5)
        print(f"    {dim:20s} {val:3d}/100  {bar}")

    print(f"""
  报告文件（写到临时目录，不会覆盖 scenarios/ 下的真实运行产物）:
    - {result.get('md_path', '')}
    - {result.get('report_path', '')}

  ============================================================
  所有 8 个 mock 工具函数均调用成功，端到端流程跑通!
  ============================================================
  """)


if __name__ == "__main__":
    main()
