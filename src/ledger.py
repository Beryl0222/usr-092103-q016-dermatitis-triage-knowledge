"""事件账本与只读投影。

- 账本 = data/seed-events.json（人工登记的外部事实）+ 由分流引擎对
  data/cases 下咨询案例计算出的 CONSULTATION_ASSESSED / CASE_ESCALATED 事件。
  评估事件由代码生成，保证“账本里的结论”与“引擎现在能算出的结论”一致，
  避免人工抄写漂移。
- 既往咨询永久绑定当时的知识版本（kb_version），事后可用新版重放对比。
- 聚集信号分来源保留；只有 CLUSTER_REVIEWED=confirm_alert 后才形成预警。
- 撤回影响扫描：找出仍在发布被撤条目、且没有下线确认的网页/话术库/合作渠道。
"""

from __future__ import annotations

import json
from pathlib import Path

from .knowledge_store import active_kb_version, load_kb
from .triage import assess, escalate

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "data" / "seed-events.json"
CASES_DIR = REPO_ROOT / "data" / "cases"
LEDGER_PATH = REPO_ROOT / "events" / "domain-events.jsonl"


def read_seed() -> list[dict]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def read_cases() -> list[dict]:
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CASES_DIR.glob("*.json"))]
    cases.sort(key=lambda c: c["received_at"])
    return cases


def generate_case_events() -> list[dict]:
    events: list[dict] = []
    for case in read_cases():
        result = assess(case)
        stamp = case["received_at"]
        cid = case["case_id"]
        events.append({
            "event_id": f"evt-{cid}-assessed",
            "event_type": "CONSULTATION_ASSESSED",
            "aggregate_type": "consultation_case",
            "aggregate_id": cid,
            "occurred_at": stamp,
            "version": 1,
            "summary": f"{cid} 按 {case['kb_version']} 分流为 {result['level']}",
            "payload": {
                "case_id": cid,
                "kb_version": result["kb_version"],
                "facts": result["facts"],
                "matched_rule_ids": result["matched_rule_ids"],
                "level": result["level"],
                "advice_item_ids": result["advice_item_ids"],
                "contraindication_ids": result["contraindication_ids"],
                "trigger_ids": result["trigger_ids"],
                "missing_question_ids": result["missing_question_ids"],
                "uncertainty": result["uncertainty"],
            },
        })
        esc = escalate(result, case)
        if esc:
            events.append({
                "event_id": f"evt-{cid}-escalated",
                "event_type": "CASE_ESCALATED",
                "aggregate_type": "consultation_case",
                "aggregate_id": cid,
                "occurred_at": stamp,
                "version": 1,
                "summary": f"{cid} 升级至 {esc['target']}（规则 {esc['reason_rule_id']}）",
                "payload": esc,
            })
    return events


def rebuild() -> list[dict]:
    events = read_seed() + generate_case_events()
    events.sort(key=lambda e: e["occurred_at"])
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return events


def load_ledger() -> list[dict]:
    if not LEDGER_PATH.exists():
        return rebuild()
    return [json.loads(line) for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def signals_snapshot(events: list[dict]) -> dict:
    """各机构信号按来源原样保留；疾控确认前不产生预警。"""
    signals = [e["payload"] for e in events if e["event_type"] == "RISK_SIGNAL_REPORTED"]
    reviews = [e["payload"] for e in events if e["event_type"] == "CLUSTER_REVIEWED"]
    confirmed = next((r for r in reviews if r["decision"] == "confirm_alert"), None)
    confirmed_ids = set(confirmed["signal_ids"]) if confirmed else set()
    for s in signals:
        s["folded_into_alert"] = s["signal_id"] in confirmed_ids
    return {
        "signals_by_source": signals,
        "total_sources": len({s["reported_by_facility"]["facility_id"] for s in signals}),
        "total_cases_reported": sum(s["case_count"] for s in signals),
        "public_alert": {"alert_id": confirmed["alert_id"], "reviewed_by": confirmed["reviewed_by"],
                         "rationale": confirmed["rationale"], "kb_version": confirmed.get("advisory_kb_version")}
        if confirmed else None,
    }


def _releases(events: list[dict]) -> dict[str, dict]:
    return {e["payload"]["revision_id"]: e["payload"]
            for e in events if e["event_type"] == "CHANNEL_PUBLISHED"}


def _takedowns(events: list[dict]) -> dict[str, dict]:
    return {e["payload"]["revision_id"]: e["payload"]
            for e in events if e["event_type"] == "CHANNEL_TAKEDOWN_CONFIRMED"}


def withdrawal_impact(events: list[dict]) -> list[dict]:
    """对每条撤回，扫描仍引用它、且没有下线确认的渠道发布。"""
    releases = _releases(events)
    takedowns = _takedowns(events)
    withdrawals = [e for e in events if e["event_type"] == "CONTENT_WITHDRAWN"]

    report: list[dict] = []
    for w in withdrawals:
        for item in w["payload"]["items"]:
            item_id = item["item_id"]
            affected = []
            for rid, rel in releases.items():
                if item_id not in rel.get("content_refs", []):
                    continue
                down = takedowns.get(rid)
                affected.append({
                    "revision_id": rid,
                    "channel": rel.get("channel"),
                    "channel_name": rel.get("channel_name"),
                    "locator": rel.get("locator"),
                    "status": "taken_down" if down else "STILL_LIVE",
                    "confirmed_by": down.get("confirmed_by") if down else None,
                    "note": down.get("note") if down else "未发现下线确认，仍在使用被撤回内容",
                })
            still_live = [a for a in affected if a["status"] == "STILL_LIVE"]
            report.append({
                "withdrawn_item": item_id,
                "origin_kb": item.get("origin_kb"),
                "reason": item["reason"],
                "superseded_by": item.get("superseded_by"),
                "affected_releases": affected,
                "open_breaches": len(still_live),
            })
    return report


def replay_case(case_id: str, current_version: str | None = None) -> dict:
    """回放某条建议当时怎么给的、后来为何被修正。"""
    events = load_ledger()
    assessed = next(
        (e["payload"] for e in events
         if e["event_type"] == "CONSULTATION_ASSESSED" and e["aggregate_id"] == case_id),
        None,
    )
    if assessed is None:
        raise KeyError(f"账本中没有该咨询：{case_id}")

    case = next(c for c in read_cases() if c["case_id"] == case_id)
    bound_version = assessed["kb_version"]
    current_version = current_version or active_kb_version()

    replayed = assess(case, current_version) if current_version != bound_version else assessed

    # 当时给的建议条目里，后来被撤回的有哪些
    later_withdrawals = []
    bound_kb = load_kb(bound_version)
    item_text = {}
    for m in bound_kb["modules"].values():
        for it in m.get("items", []):
            if isinstance(it, dict) and "id" in it:
                item_text[it["id"]] = it.get("text") or it.get("name") or it["id"]
    for e in events:
        if e["event_type"] != "CONTENT_WITHDRAWN":
            continue
        for item in e["payload"]["items"]:
            if item["item_id"] in assessed.get("advice_item_ids", []) or \
               item["item_id"] in assessed.get("matched_rule_ids", []):
                later_withdrawals.append({
                    "event_id": e["event_id"],
                    "item_id": item["item_id"],
                    "what_it_said_then": item_text.get(item["item_id"], item["item_id"]),
                    "reason": item["reason"],
                    "superseded_by": item.get("superseded_by"),
                })

    return {
        "case_id": case_id,
        "bound_version": bound_version,
        "bound_level": assessed["level"],
        "bound_advice": assessed.get("advice_item_ids", []),
        "replayed_version": current_version,
        "replayed_level": replayed["level"],
        "level_changed": assessed["level"] != replayed["level"],
        "replayed_rule": replayed.get("winning_rule_id"),
        "later_withdrawals": later_withdrawals,
        "changed": assessed["level"] != replayed["level"] or bool(later_withdrawals),
    }
