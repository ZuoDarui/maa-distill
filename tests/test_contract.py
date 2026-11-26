import unittest

from maa_distill import contract
from maa_distill.schema import Copilot


def cp(title, n=5):
    return Copilot.from_json({"stage_name": "level_rune_14-02", "doc": {"title": title},
                              "opers": [{"name": f"o{i}"} for i in range(n)], "actions": []})


class ContractTest(unittest.TestCase):
    def test_parse_titles(self):
        i = contract.parse(cp("危机合约#12 4/3日替 10级tag 迷雾战区 5人"))
        self.assertEqual((i.risk, i.declared_opers), (10, 5))
        i = contract.parse(cp("起源行动3.21每日轮替8三人迷雾战区", n=3))
        self.assertEqual((i.risk, i.declared_opers), (8, 3))
        self.assertIsNone(contract.parse(cp("随便打打")).risk)

    def test_accept(self):
        self.assertTrue(contract.accept(cp("10级tag"), min_risk=8))
        self.assertFalse(contract.accept(cp("8级tag"), min_risk=10))
        self.assertFalse(contract.accept(cp("无等级"), min_risk=1))
        self.assertFalse(contract.accept(cp("10级", n=6), max_opers=5))
        self.assertTrue(contract.accept(cp("无等级")))


if __name__ == "__main__":
    unittest.main()
