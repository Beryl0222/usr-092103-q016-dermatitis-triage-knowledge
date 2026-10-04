"""数据驱动的虫媒皮炎分流引擎。

输入：咨询案例（来电事实 + 绑定的知识版本）。
输出：分流结论（级别、命中规则、居家/就诊前步骤、禁忌、优先升级信号、
缺失问题、不确定性）。

重要原则：
- 系统只做分流，不做诊断；任何输出都附不确定性与“还需确认”的问题。
- 规则全部来自知识包 care_rules 模块，引擎不内置医学结论。
- 多条规则命中时取最高级别；priority_signal 规则用于解释“为什么升级”。
- 关键信息缺失且不足以支撑居家结论时，返回 indeterminate，就高不就低。
"""

from __future__ import annotations

from .knowledge_store import (
    catalog_index,
    level_rank,
    load_kb,
    module,
)

CORE_QUESTIONS = (
    "q-age",
    "q-site",
    "q-lesion",
    "q-area",
    "q-integrity",
    "q-systemic",
)

HIGH_RISK_FACTS = (
    "systemic_anaphylaxis",
    "extensive_blisters",
    "erosion_oozing",
    "infection_signs",
    "site_face",
    "tick_attached",
    "is_infant",
)

DISCLAIMER = "本建议为健康热线分流参考，不构成医师诊断；如症状与描述不符或持续加重，请以面诊医生判断为准。"

# 互斥事实组：确认其中任一，即视为其余已被否定（用于判断“问题是否已问清”）
EXCLUSIVE_GROUPS = (
    {"is_infant", "is_child", "is_adult", "is_elderly"},
    {"site_face", "site_limbs", "site_trunk"},
)


def _expand_known(facts: frozenset[str], negated: frozenset[str]) -> frozenset[str]:
    known = set(facts) | set(negated)
    for group in EXCLUSIVE_GROUPS:
        if group & facts:
            known |= group
    return frozenset(known)


def _rule_fires(rule: dict, facts: frozenset[str]) -> bool:
    when = rule.get("when", {})
    required_all = [f.removeprefix("fact:") for f in when.get("all", [])]
    required_any = [f.removeprefix("fact:") for f in when.get("any", [])]
    if required_all and not all(f in facts for f in required_all):
        return False
    if required_any and not any(f in facts for f in required_any):
        return False
    return bool(required_all or required_any)


def _questions(kb: dict) -> list[dict]:
    return module(kb, "intake_questions").get("items", [])


def assess(case: dict, kb_version: str | None = None) -> dict:
    kb_version = kb_version or case.get("kb_version", "")
    kb = load_kb(kb_version)
    facts = frozenset(case.get("facts", []))
    negated = frozenset(case.get("negated_facts", []))
    known = _expand_known(facts, negated)

    rules = module(kb, "care_rules").get("items", [])
    matched = [r for r in rules if _rule_fires(r, facts)]
    matched.sort(key=lambda r: level_rank(kb, r.get("level", "")), reverse=True)
    winner = matched[0] if matched else None

    # 缺失问题：该问题能建立的事实既未确认也未否认
    questions = _questions(kb)
    missing = [q["id"] for q in questions if not set(q.get("establishes", [])) & known]
    missing_core = [qid for qid in missing if qid in CORE_QUESTIONS]

    # 不确定性：缺失问题中凡是关系到高风险事实的，都要显式提示“未能排除”
    uncertainty: list[str] = []
    for q in questions:
        if q["id"] in missing and set(q.get("establishes", [])) & set(HIGH_RISK_FACTS):
            uncertainty.append(f"未能排除“{q['why']}”——{q['text']}")

    if winner is None:
        level = "indeterminate"
        uncertainty.append("现有信息不足以判断皮损形态与严重程度，不能给出居家观察结论，按就高不就低处理。")
    else:
        level = winner["level"]
        # 安全兜底：想让轻症居家，但核心问题没问清 → 不允许居家结论
        if level == "home_observe" and missing_core:
            level = "indeterminate"
            uncertainty.append("尚有关键问题未确认，不能直接建议居家观察；请先补齐下列问题后再分流。")

    if level == "indeterminate" and not missing:
        uncertainty.append("知识版本缺少采集问题模块，无法自动指出缺口，请人工补充问清。")

    matched_ids = [r["id"] for r in matched]
    priority_triggers = [r["id"] for r in matched if r.get("priority_signal")]

    steps_index = catalog_index(kb, "home_steps")
    contra_index = catalog_index(kb, "contraindications")

    step_ids: list[str] = []
    if winner:
        for sid in winner.get("home_step_ids", []):
            if sid in steps_index and sid not in step_ids:
                step_ids.append(sid)

    contra_ids: list[str] = []
    for r in matched:
        for cid in r.get("contraindication_ids", []):
            if cid in contra_index and cid not in contra_ids:
                contra_ids.append(cid)

    return {
        "case_id": case["case_id"],
        "kb_version": kb_version,
        "facts": sorted(facts),
        "matched_rule_ids": matched_ids,
        "winning_rule_id": winner["id"] if winner else None,
        "level": level,
        "advice_item_ids": step_ids,
        "contraindication_ids": contra_ids,
        "trigger_ids": priority_triggers,
        "missing_question_ids": missing,
        "uncertainty": uncertainty,
    }


def escalate(assessment: dict, case: dict, kb_version: str | None = None) -> dict | None:
    """命中紧急/当日就医级别时生成升级建议；否则返回 None。"""
    kb = load_kb(kb_version or assessment["kb_version"])
    if assessment["level"] not in ("emergency_now", "urgent_same_day"):
        return None
    rules = catalog_index(kb, "care_rules")
    winner = rules.get(assessment["winning_rule_id"], {})
    target = "120/急诊" if assessment["level"] == "emergency_now" else "皮肤科或急诊（当日）"
    priority_names = [rules[r]["name"] for r in assessment["trigger_ids"] if r in rules]
    return {
        "case_id": assessment["case_id"],
        "target": target,
        "reason_rule_id": assessment["winning_rule_id"],
        "priority_signals": priority_names,
        "advised_within": winner.get("advised_within", ""),
    }
