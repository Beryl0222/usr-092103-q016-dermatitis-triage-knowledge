"""把分流结论渲染成两种中文视图。

- render_public：面向公众的简明“当下指引”，不含术语与规则编号。
- render_agent：面向坐席的工作视图，解释为什么升级、依据哪些规则与来源、
  还缺哪些问题、不确定性来自哪里。
"""

from __future__ import annotations

from .knowledge_store import catalog_index, level_label, load_kb, module
from .triage import DISCLAIMER


def _ordered(kb: dict, module_name: str, ids: list[str]) -> list[dict]:
    index = catalog_index(kb, module_name)
    return [index[i] for i in ids if i in index]


def render_public(assessment: dict) -> str:
    kb = load_kb(assessment["kb_version"])
    rules = catalog_index(kb, "care_rules")
    winner = rules.get(assessment["winning_rule_id"], {})
    level = assessment["level"]
    lines: list[str] = []

    lines.append(f"【现在该怎么做】{level_label(kb, level)}")
    if level == "indeterminate":
        lines.append("您提供的信息还不够判断，先别自行处理或只在家观察，请配合坐席补充几个问题；若不放心，可先按就高原则到皮肤科面诊。")
    elif winner:
        lines.append(winner.get("action", ""))
        if winner.get("advised_within"):
            lines.append(f"建议时限：{winner['advised_within']}。")

    steps = _ordered(kb, "home_steps", assessment["advice_item_ids"])
    if steps:
        lines.append("")
        lines.append("就医前/居家可先这样护理：")
        lines.extend(f"  {i}. {s['text']}" for i, s in enumerate(steps, 1))

    contras = _ordered(kb, "contraindications", assessment["contraindication_ids"])
    if contras:
        lines.append("")
        lines.append("这些做法请务必避免：")
        lines.extend(f"  ✕ {c['text']}" for c in contras)

    if assessment["missing_question_ids"] and level != "indeterminate":
        q_index = {q["id"]: q for q in module(kb, "intake_questions").get("items", [])}
        lines.append("")
        lines.append("还请您补充：")
        lines.extend(f"  ？{q_index[q]['text']}" for q in assessment["missing_question_ids"] if q in q_index)

    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def render_agent(assessment: dict) -> str:
    kb = load_kb(assessment["kb_version"])
    rules_index = catalog_index(kb, "care_rules")
    levels = {item["level"]: item for item in module(kb, "severity_levels").get("items", [])}
    q_index = {q["id"]: q for q in module(kb, "intake_questions").get("items", [])}
    sources = catalog_index(kb, "sources")

    lines = [
        f"坐席分流卡｜案例 {assessment['case_id']}",
        f"知识版本：{assessment['kb_version']}（状态：{kb.get('status', '?')}）",
        "模块版本：" + "，".join(
            f"{name}={m.get('module_version', '?')}"
            for name, m in kb.get("modules", {}).items()
        ),
        f"已知事实：{', '.join(assessment['facts']) or '（无）'}",
        f"分流级别：{assessment['level']} —— {level_label(kb, assessment['level'])}",
    ]
    lvl_def = levels.get(assessment["level"])
    if lvl_def:
        lines.append(f"级别定义：{lvl_def.get('definition', '')}")

    lines.append("")
    lines.append("命中规则（按级别从高到低）：")
    for rid in assessment["matched_rule_ids"]:
        r = rules_index[rid]
        flag = "【优先升级信号】" if r.get("priority_signal") else ""
        mark = " ◄ 决定级别" if rid == assessment["winning_rule_id"] else ""
        lines.append(f"  • [{rid}] {r['name']} → {r['level']}{flag}{mark}")
        lines.append(f"      理由：{r.get('rationale', '')}")
        srcs = [f"{sid}《{sources[sid]['title']}》" for sid in r.get("source_ids", []) if sid in sources]
        if srcs:
            lines.append(f"      依据来源：{'；'.join(srcs)}")

    if assessment["trigger_ids"]:
        lines.append("")
        lines.append("为什么升级：命中优先信号 " + "、".join(
            rules_index[t]["name"] for t in assessment["trigger_ids"] if t in rules_index
        ) + "，按就高不就低覆盖较低级别规则。")

    lines.append("")
    lines.append(f"缺失问题（{len(assessment['missing_question_ids'])}）：")
    if assessment["missing_question_ids"]:
        for qid in assessment["missing_question_ids"]:
            q = q_index.get(qid)
            lines.append(f"  ？[{qid}] {q['text'] if q else qid}（影响：{q['why'] if q else '?'}）")
    else:
        lines.append("  无（核心采集问题已问清）")

    lines.append("")
    lines.append("不确定性：")
    lines.extend(f"  ! {u}" for u in assessment["uncertainty"])
    lines.append(f"  ! {DISCLAIMER}")
    return "\n".join(lines)
