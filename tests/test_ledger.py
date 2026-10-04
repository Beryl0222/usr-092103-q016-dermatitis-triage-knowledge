import unittest

from src import ledger
from src.validator import validate_event_full


class LedgerContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = ledger.rebuild()

    def test_every_event_passes_full_validation(self):
        for e in self.events:
            self.assertEqual(validate_event_full(e), [], f"事件不合规：{e['event_id']}")

    def test_assessments_bound_to_a_kb_version(self):
        assessed = [e for e in self.events if e["event_type"] == "CONSULTATION_ASSESSED"]
        self.assertGreaterEqual(len(assessed), 5)
        for e in assessed:
            self.assertTrue(e["payload"]["kb_version"].startswith("kb-"))

    def test_escalation_only_for_urgent_or_emergency(self):
        levels = {e["aggregate_id"]: e["payload"]["level"]
                  for e in self.events if e["event_type"] == "CONSULTATION_ASSESSED"}
        for e in self.events:
            if e["event_type"] == "CASE_ESCALATED":
                self.assertIn(levels[e["aggregate_id"]], ("urgent_same_day", "emergency_now"))
        # 面部密集水疱案例必须有升级事件
        esc_targets = {e["aggregate_id"] for e in self.events if e["event_type"] == "CASE_ESCALATED"}
        self.assertIn("case-2026-09-26-face-blisters", esc_targets)
        # 信息不足案例不得被静默居家或升级，而是 indeterminate
        self.assertEqual(levels["case-2026-09-28-vague"], "indeterminate")


class ClusterSignalTest(unittest.TestCase):
    def test_sources_kept_separately_before_confirmation(self):
        # 构造“只有上报、尚未评审”的事件子集
        seed = [e for e in ledger.read_seed() if e["event_type"] == "RISK_SIGNAL_REPORTED"]
        snap = ledger.signals_snapshot(ledger.generate_case_events() + seed)
        self.assertEqual(snap["total_sources"], 3)
        self.assertEqual(snap["total_cases_reported"], 17 + 11 + 9)
        self.assertIsNone(snap["public_alert"])  # 疾控未确认 → 无预警
        self.assertTrue(all(not s["folded_into_alert"] for s in snap["signals_by_source"]))

    def test_alert_only_after_cdc_confirmation(self):
        snap = ledger.signals_snapshot(ledger.load_ledger())
        self.assertIsNotNone(snap["public_alert"])
        self.assertEqual(snap["public_alert"]["alert_id"], "alert-2026-09-paederus-01")
        # 三个来源都被点名并入，且各自数据仍保留
        self.assertEqual(len(snap["signals_by_source"]), 3)
        self.assertTrue(all(s["folded_into_alert"] for s in snap["signals_by_source"]))


class WithdrawalImpactTest(unittest.TestCase):
    def test_every_affected_release_is_eventually_taken_down(self):
        report = ledger.withdrawal_impact(ledger.load_ledger())
        affected = [rel for row in report for rel in row["affected_releases"]]
        self.assertTrue(affected, "应能扫到引用被撤内容的渠道发布")
        # 当前账本里全部已确认下线
        self.assertEqual(sum(row["open_breaches"] for row in report), 0)
        channels = {rel["channel"] for rel in affected}
        self.assertEqual(channels, {"web", "script_library", "partner"})

    def test_unconfirmed_release_is_flagged_still_live(self):
        # 人为追加一个引用旧条目但尚未下线的合作渠道
        events = ledger.load_ledger() + [{
            "event_id": "evt-test-rogue",
            "event_type": "CHANNEL_PUBLISHED",
            "aggregate_type": "channel_release",
            "aggregate_id": "rel-rogue-1",
            "occurred_at": "2026-10-01T10:00:00+08:00",
            "version": 1,
            "summary": "某外渠道仍在转载含酒精说法的旧稿",
            "payload": {"channel": "partner", "channel_name": "未登记外部自媒体",
                        "revision_id": "rel-rogue-1", "kb_version": "kb-2026-01",
                        "content_refs": ["old-home-01"], "locator": "partner://rogue/x"}
        }]
        report = ledger.withdrawal_impact(events)
        alcohol = next(row for row in report if row["withdrawn_item"] == "old-home-01")
        rogue = next(rel for rel in alcohol["affected_releases"] if rel["revision_id"] == "rel-rogue-1")
        self.assertEqual(rogue["status"], "STILL_LIVE")
        self.assertGreaterEqual(alcohol["open_breaches"], 1)


class ReplayTest(unittest.TestCase):
    def test_replay_shows_face_case_was_corrected(self):
        r = ledger.replay_case("case-2026-09-13-face-blisters")
        self.assertEqual(r["bound_version"], "kb-2026-01")
        self.assertEqual(r["bound_level"], "home_observe")
        self.assertEqual(r["replayed_level"], "urgent_same_day")
        self.assertTrue(r["level_changed"])
        withdrawn_ids = {w["item_id"] for w in r["later_withdrawals"]}
        self.assertIn("old-home-01", withdrawn_ids)
        self.assertIn("old-rule-observe-all", withdrawn_ids)

    def test_replay_binds_to_version_at_time(self):
        # 09-26 的咨询绑定现行版，用现行版重放不应再变化
        r = ledger.replay_case("case-2026-09-26-face-blisters")
        self.assertEqual(r["bound_version"], r["replayed_version"])
        self.assertEqual(r["replayed_level"], "urgent_same_day")


if __name__ == "__main__":
    unittest.main()
