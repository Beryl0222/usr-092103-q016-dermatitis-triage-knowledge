"""虫媒皮炎分流知识台命令行。

示例：
  python3 -m src.cli rebuild                       # 由案例重算并重建事件账本
  python3 -m src.cli triage case-2026-09-26-face-blisters
  python3 -m src.cli triage case-2026-09-12-arm-redpatch --view agent --kb kb-2026-02
  python3 -m src.cli signals
  python3 -m src.cli impact
  python3 -m src.cli replay case-2026-09-13-face-blisters
  python3 -m src.cli season --month 9
"""

from __future__ import annotations

import argparse
import json

from . import ledger
from .knowledge_store import active_kb_version, catalog_index, load_kb, module
from .triage import assess
from .views import render_agent, render_public


def _load_case(case_id: str) -> dict:
    for c in ledger.read_cases():
        if c["case_id"] == case_id:
            return c
    raise SystemExit(f"找不到案例：{case_id}")


def cmd_rebuild(_args) -> None:
    events = ledger.rebuild()
    print(f"已重建 {ledger.LEDGER_PATH.relative_to(ledger.REPO_ROOT)}，共 {len(events)} 条事件。")


def cmd_triage(args) -> None:
    case = _load_case(args.case_id)
    result = assess(case, args.kb)
    print(render_agent(result) if args.view == "agent" else render_public(result))


def cmd_assess_all(_args) -> None:
    for case in ledger.read_cases():
        result = assess(case)
        print(f"{case['case_id']}  [{result['kb_version']}]  -> {result['level']}"
              f"  规则={result['winning_rule_id']}  缺失问题={len(result['missing_question_ids'])}")


def cmd_signals(_args) -> None:
    snap = ledger.signals_snapshot(ledger.load_ledger())
    print("各医疗机构上报（按来源原样保留，疾控未确认前不对外）：")
    for s in snap["signals_by_source"]:
        mark = "已并入预警" if s["folded_into_alert"] else "待疾控复核"
        print(f"  [{s['signal_id']}] {s['reported_by_facility']['name']}·{s['reported_by_facility']['department']}"
              f"｜{s['case_count']}例｜{s['area']}｜{mark}")
        print(f"      原始记录：{s['raw_note']}")
        print(f"      来源单据：{s['source_doc_ref']}｜报告人：{s['reporter']}")
    print(f"合计：{snap['total_sources']}家机构，{snap['total_cases_reported']}例（各来源数据未合并改写）。")
    alert = snap["public_alert"]
    if alert:
        print(f"\n聚集预警（疾控确认后发布）：{alert['alert_id']}")
        print(f"  确认人：{alert['reviewed_by']}")
        print(f"  理由：{alert['rationale']}")
        print(f"  依据知识版本：{alert['kb_version']}")
    else:
        print("\n尚无经疾控确认的聚集预警（信号仅内部留存）。")


def cmd_impact(_args) -> None:
    report = ledger.withdrawal_impact(ledger.load_ledger())
    open_total = 0
    for row in report:
        print(f"撤回条目 {row['withdrawn_item']}（来自 {row['origin_kb']}）")
        print(f"  撤回原因：{row['reason']}")
        for rel in row["affected_releases"]:
            tag = "仍在线 ✗" if rel["status"] == "STILL_LIVE" else "已下线 ✓"
            who = f"，确认人：{rel['confirmed_by']}" if rel["confirmed_by"] else ""
            print(f"    [{tag}] {rel['channel']}｜{rel['channel_name']}｜{rel['locator']}{who}")
            print(f"        {rel['note']}")
        if row["open_breaches"]:
            open_total += row["open_breaches"]
            print(f"  !! 仍有 {row['open_breaches']} 处渠道在使用该被撤内容")
        print()
    print(f"汇总：未闭环的违规使用点 {open_total} 处。" if open_total else "汇总：所有被撤内容的发布点均已确认下线。")


def cmd_replay(args) -> None:
    r = ledger.replay_case(args.case_id, args.kb)
    print(f"案例 {r['case_id']} 的建议修正回放")
    print(f"  当时绑定知识版本：{r['bound_version']}")
    print(f"  当时分流级别：{r['bound_level']}")
    print(f"  用现行版 {r['replayed_version']} 重放：{r['replayed_level']}（规则 {r['replayed_rule']}）")
    print(f"  级别是否改变：{'是' if r['level_changed'] else '否'}")
    if r["later_withdrawals"]:
        print("  当时给出、后来被撤回的内容：")
        for w in r["later_withdrawals"]:
            print(f"    - {w['item_id']}「{w['what_it_said_then']}」")
            print(f"        为何撤回：{w['reason']}")
            print(f"        替代为：{w['superseded_by']}（撤回事件 {w['event_id']}）")
    if not r["changed"]:
        print("  该建议未被后续修正。")


def cmd_season(args) -> None:
    kb = load_kb(active_kb_version())
    exposures = catalog_index(kb, "exposure_routes")
    for s in module(kb, "seasonal_risks").get("items", []):
        if args.month is not None and args.month not in s["months"]:
            continue
        linked = "、".join(exposures[e]["name"] for e in s["linked_exposures"] if e in exposures)
        print(f"{s['name']}（{s['months']}月）｜{s['regions']}｜相关暴露：{linked}")
        print(f"    {s['note']}")


def cmd_sources(_args) -> None:
    kb = load_kb(active_kb_version())
    for s in catalog_index(kb, "sources").values():
        print(f"[{s['id']}] {s['title']}")
        print(f"    发布方：{s['publisher']}｜权威级别：{s['authority_level']}")
        print(f"    备注：{s['ref_note']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="虫媒皮炎分流知识台")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("rebuild", help="由案例重算并重建事件账本")
    sp.set_defaults(func=cmd_rebuild)

    sp = sub.add_parser("triage", help="对单个咨询案例分流")
    sp.add_argument("case_id")
    sp.add_argument("--view", choices=["public", "agent"], default="public")
    sp.add_argument("--kb", help="覆盖知识版本（默认用案例绑定版本）")
    sp.set_defaults(func=cmd_triage)

    sp = sub.add_parser("assess-all", help="列出全部案例的分流结论")
    sp.set_defaults(func=cmd_assess_all)

    sp = sub.add_parser("signals", help="聚集信号与疾控预警状态")
    sp.set_defaults(func=cmd_signals)

    sp = sub.add_parser("impact", help="撤回内容的渠道影响扫描")
    sp.set_defaults(func=cmd_impact)

    sp = sub.add_parser("replay", help="回放某条建议后来为何被修正")
    sp.add_argument("case_id")
    sp.add_argument("--kb", help="用于重放的版本，默认现行版")
    sp.set_defaults(func=cmd_replay)

    sp = sub.add_parser("season", help="查看季节风险")
    sp.add_argument("--month", type=int, choices=range(1, 13))
    sp.set_defaults(func=cmd_season)

    sp = sub.add_parser("sources", help="列出现行版权威来源")
    sp.set_defaults(func=cmd_sources)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
