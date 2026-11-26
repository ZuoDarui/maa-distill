import json
import tempfile
import unittest
from pathlib import Path

from maa_distill import roguelike
from maa_distill.box import OwnedOper

SRC = {"theme": "Phantom", "team_complete_condition": [{"groups": ["g"], "threshold": 1}],
       "priority": [{"name": "g", "opers": [
           {"name": "甲", "recruit_priority": 100, "is_start": True},
           {"name": "乙", "recruit_priority": 90},
           {"name": "丙", "recruit_priority": 80}]}]}


class RoguelikeOverrideTest(unittest.TestCase):
    def test_override_is_complete_and_adjusted(self):
        with tempfile.TemporaryDirectory() as d:
            res = Path(d) / "res"
            (res / "roguelike" / "Phantom").mkdir(parents=True)
            (res / "roguelike" / "Phantom" / "recruitment.json").write_text(json.dumps(SRC, ensure_ascii=False), encoding="utf-8")
            box = {"乙": OwnedOper("乙", 2, 90), "丙": OwnedOper("丙", 1, 50)}
            f, notes = roguelike.write_override(res, "Phantom", box, Path(d) / "inc", bonus=40)
            self.assertEqual(f, Path(d) / "inc" / "resource" / "roguelike" / "Phantom" / "recruitment.json")
            out = json.loads(f.read_text(encoding="utf-8"))
            # MAA 会 clear(theme) 后整份载入：覆盖文件必须保留全部字段
            self.assertEqual(out["team_complete_condition"], SRC["team_complete_condition"])
            pr = {o["name"]: o["recruit_priority"] for o in out["priority"][0]["opers"]}
            self.assertEqual(pr, {"甲": 100, "乙": 130, "丙": 100})
            self.assertEqual(len(notes), 2)


if __name__ == "__main__":
    unittest.main()
