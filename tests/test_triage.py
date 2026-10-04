import unittest

from src.knowledge_store import load_kb
from src.triage import assess, escalate

V1 = "kb-2026-01"
V2 = "kb-2026-02"


def case(cid, facts, kb=V2, negated=None):
    return {"case_id": cid, "facts": list(facts), "negated_facts": list(negated or []), "kb_version": kb}


class AnchorScenariosTest(unittest.TestCase):
    def test_small_arm_erythema_child_is_home_observe_when_questions_cleared(self):
        # 孩子手臂一小片红斑，无破溃、无全身症状，核心问题已问清
        c = case("arm", {
            "any_skin_lesion", "lesion_erythema", "lesion_papule", "small_localized",
            "site_limbs", "is_child",
        }, negated=["erosion_oozing", "systemic_anaphylaxis", "infection_signs",
                    "extensive_blisters", "site_face", "tick_attached", "is_infant"])
        r = assess(c)
        self.assertEqual(r["level"], "home_observe")
        self.assertEqual(r["winning_rule_id"], "r-mild-local")

    def test_dense_face_vesicles_is_urgent_same_day(self):
        # 面部已有密集水疱 —— 必须当日就医，不能居家观察
        c = case("face", {
            "any_skin_lesion", "lesion_vesicle", "site_face", "dense_cluster",
            "paederus_contact", "is_adult",
        })
        r = assess(c)
        self.assertEqual(r["level"], "urgent_same_day")
        self.assertEqual(r["winning_rule_id"], "r-face-dense-vesicles")
        self.assertIn("r-face-dense-vesicles", r["trigger_ids"])
        esc = escalate(r, c)
        self.assertIsNotNone(esc)
        self.assertIn("皮肤科", esc["target"])

    def test_two_scenarios_get_different_advice(self):
        arm = assess(case("arm", {"any_skin_lesion", "lesion_erythema", "small_localized", "site_limbs", "is_child"},
                          negated=["erosion_oozing", "systemic_anaphylaxis", "infection_signs",
                                   "extensive_blisters", "site_face", "tick_attached", "is_infant"]))
        face = assess(case("face", {"any_skin_lesion", "lesion_vesicle", "site_face", "dense_cluster", "is_adult"}))
        self.assertNotEqual(arm["level"], face["level"])
        self.assertNotEqual(arm["advice_item_ids"], face["advice_item_ids"])

    def test_old_kb_sent_both_scenarios_home_with_irritants(self):
        # 旧版两个场景都归为居家观察，且下发酒精/碘伏/挑破水疱
        for facts in (
            {"any_skin_lesion", "is_child", "small_localized"},
            {"any_skin_lesion", "lesion_vesicle", "site_face", "dense_cluster"},
        ):
            r = assess(case("old", facts, kb=V1))
            self.assertEqual(r["level"], "home_observe")
            self.assertIn("old-home-01", r["advice_item_ids"])  # 酒精
            self.assertIn("old-home-02", r["advice_item_ids"])  # 碘伏
            self.assertIn("old-home-03", r["advice_item_ids"])  # 挑破水疱


class PriorityEscalationTest(unittest.TestCase):
    def test_systemic_anaphylaxis_is_emergency(self):
        r = assess(case("ana", {"any_skin_lesion", "systemic_anaphylaxis"}))
        self.assertEqual(r["level"], "emergency_now")
        esc = escalate(r, case("ana", {"systemic_anaphylaxis"}))
        self.assertIn("120", esc["target"])

    def test_extensive_blisters_and_erosion_escalate(self):
        self.assertEqual(assess(case("x", {"lesion_vesicle", "extensive_blisters"}))["level"], "urgent_same_day")
        self.assertEqual(assess(case("x", {"any_skin_lesion", "erosion_oozing"}))["level"], "urgent_same_day")

    def test_child_with_vesicle_is_24_48_hours(self):
        r = assess(case("cv", {"is_child", "lesion_vesicle", "site_limbs"},
                        negated=["site_face", "extensive_blisters", "erosion_oozing", "is_infant"]))
        self.assertEqual(r["level"], "reassess_24_48")
        self.assertEqual(r["winning_rule_id"], "r-child-vesicle")

    def test_infant_any_lesion_is_24_48_hours(self):
        r = assess(case("inf", {"is_infant", "any_skin_lesion", "small_localized"}))
        self.assertEqual(r["level"], "reassess_24_48")


class ContraindicationTest(unittest.TestCase):
    def test_irritants_never_recommended_as_steps(self):
        # 任何分流级别，居家步骤里都不得出现酒精/碘伏/挑破水疱
        kb = load_kb(V2)
        step_ids = {s["id"] for m in kb["modules"].values() for s in m.get("items", [])
                    if isinstance(s, dict) and m.get("module_version", "").startswith("home")}
        for banned in ("ctr-alcohol", "ctr-iodine", "ctr-pop-blister"):
            self.assertNotIn(banned, step_ids)

    def test_erosion_warns_calamine_contraindicated(self):
        r = assess(case("er", {"any_skin_lesion", "erosion_oozing"}))
        self.assertIn("ctr-calamine-broken", r["contraindication_ids"])
        step_ids = set(r["advice_item_ids"])
        self.assertNotIn("home-calamine", step_ids)  # 渗液处不给炉甘石

    def test_alcohol_and_iodine_listed_as_contraindications(self):
        r = assess(case("f", {"any_skin_lesion", "lesion_vesicle", "site_face", "dense_cluster"}))
        self.assertIn("ctr-alcohol", r["contraindication_ids"])
        self.assertIn("ctr-iodine", r["contraindication_ids"])
        self.assertIn("ctr-pop-blister", r["contraindication_ids"])


class UncertaintyTest(unittest.TestCase):
    def test_insufficient_info_is_indeterminate_with_questions(self):
        r = assess(case("vague", {"is_child"}))
        self.assertEqual(r["level"], "indeterminate")
        self.assertGreaterEqual(len(r["missing_question_ids"]), 5)
        self.assertTrue(r["uncertainty"])

    def test_cannot_conclude_home_without_core_questions(self):
        # 只有“有点红”，核心问题未问清 → 不允许直接居家观察
        r = assess(case("thin", {"any_skin_lesion"}))
        self.assertEqual(r["level"], "indeterminate")

    def test_known_adult_does_not_ask_age_again(self):
        r = assess(case("adult", {"any_skin_lesion", "lesion_erythema", "small_localized", "is_adult"},
                        negated=["erosion_oozing", "systemic_anaphylaxis", "infection_signs",
                                 "extensive_blisters", "site_face", "tick_attached"]))
        # 年龄问题已通过 is_adult 解决，不应再出现在缺失问题里
        self.assertNotIn("q-age", r["missing_question_ids"])


if __name__ == "__main__":
    unittest.main()
