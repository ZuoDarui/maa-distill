"""离线单元测试：python -m unittest discover tests"""

import json
import unittest
from pathlib import Path

from maa_distill import box as boxmod
from maa_distill import db, feedback, planner, scoring
from maa_distill.gamedata import OperInfo
from maa_distill.schema import Copilot

FIX = Path(__file__).parent / "fixtures"


def fake_info():
    # 只放测试需要的干员，不依赖 MAA 资源文件
    rows = [
        ("圣聆初雪", "CASTER", "phalanx", "RANGED", 6), ("伊芙利特", "CASTER", "blastcaster", "RANGED", 6),
        ("蜜蜡", "CASTER", "phalanx", "RANGED", 5), ("遥", "SUPPORT", "x", "RANGED", 6),
        ("乌尔比安", "TANK", "y", "MELEE", 6), ("歌蕾蒂娅", "SPECIAL", "z", "MELEE", 6),
        ("凛御银灰", "WARRIOR", "w", "MELEE", 6), ("德克萨斯", "PIONEER", "v", "MELEE", 5),
        ("黍", "TANK", "u", "MELEE", 6), ("塞雷娅", "TANK", "u", "MELEE", 6),
    ]
    return {r[0]: OperInfo(*r) for r in rows}


def make_box(names, elite=2, level=70):
    info = fake_info()
    return {n: boxmod.OwnedOper(n, elite, level, rarity=info[n].rarity) for n in names}


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((FIX / "act55side_s02_110081.json").read_text(encoding="utf-8"))
        self.cp = Copilot.from_json(self.raw)
        self.conn = db.connect(":memory:")
        self.conn.execute(
            "INSERT INTO copilots(id, stage_name, likes, dislikes, views, content, has_actions) VALUES (?,?,?,?,?,?,1)",
            (1, self.cp.stage_name, 100, 1, 1000, json.dumps(self.raw, ensure_ascii=False)))

    def test_full_box_no_substitution(self):
        b = make_box(["圣聆初雪", "遥", "乌尔比安", "歌蕾蒂娅", "凛御银灰", "德克萨斯", "黍"])
        variants = planner.resolve(self.cp, b, fake_info())
        self.assertEqual(len(variants), 1)
        slots, ok = variants[0]
        self.assertTrue(ok)
        self.assertFalse(any(s.substituted for s in slots))

    def test_same_branch_preferred(self):
        b = make_box(["伊芙利特", "蜜蜡", "遥", "乌尔比安", "歌蕾蒂娅", "凛御银灰", "德克萨斯", "黍"])
        slots, ok = planner.resolve(self.cp, b, fake_info())[0]
        self.assertTrue(ok)
        sub = [s for s in slots if s.substituted][0]
        self.assertEqual(sub.chosen, ["蜜蜡"])  # 同为阵法术师，优先于伊芙利特

    def test_adapted_json_keeps_action_names(self):
        b = make_box(["伊芙利特", "遥", "乌尔比安", "歌蕾蒂娅", "凛御银灰", "德克萨斯", "黍"])
        slots, _ = planner.resolve(self.cp, b, fake_info())[0]
        content = planner.build_content(self.cp, slots, b)
        names = {o["name"] for o in content["opers"]} | {g["name"] for g in content["groups"]}
        original_slots = set(self.cp.slot_names())
        for a in content["actions"]:
            # 关卡道具（如 自爆榴弹）不属于编队，跳过
            if a.get("name") in original_slots:
                self.assertIn(a["name"], names, "原作业引用的编队位在改编后必须仍然存在")
        self.assertNotIn("圣聆初雪", {o["name"] for o in content["opers"]})

    def test_infeasible_when_no_substitute(self):
        b = make_box(["遥", "乌尔比安", "歌蕾蒂娅", "凛御银灰", "德克萨斯", "黍"])
        self.assertFalse(planner.resolve(self.cp, b, fake_info())[0][1])

    def test_feedback_reorders(self):
        b = make_box(["伊芙利特", "蜜蜡", "遥", "乌尔比安", "歌蕾蒂娅", "凛御银灰", "德克萨斯", "黍"])
        plans = planner.plans_for_stage(self.conn, {self.cp.stage_name}, b, fake_info())
        first = plans[0]
        for _ in range(3):
            feedback.record_run(self.conn, first.plan_hash, self.cp.stage_name, False, 1)
        plans2 = planner.plans_for_stage(self.conn, {self.cp.stage_name}, b, fake_info())
        self.assertNotEqual(plans2[0].plan_hash, first.plan_hash)


class ScoringTest(unittest.TestCase):
    def test_wilson(self):
        self.assertGreater(scoring.wilson_lower_bound(1000, 10), scoring.wilson_lower_bound(10, 0))
        self.assertEqual(scoring.wilson_lower_bound(0, 0), 0.5)

    def test_posterior_moves_with_evidence(self):
        p0 = 0.9
        self.assertLess(scoring.posterior(p0, 0, 3), p0)
        self.assertGreater(scoring.posterior(0.5, 3, 0), 0.5)


if __name__ == "__main__":
    unittest.main()
