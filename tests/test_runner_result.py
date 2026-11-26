"""用用户实机 run 1-7 的真实回调（2026-11-26）验证"未开打"判定。"""

import unittest

from maa_distill.runner import CopilotResult

REAL_PRE_BATTLE_FAIL = [
    ("SubTaskError", {"class": "asst::ProcessTask", "details": {}, "first": ["BattleStartPre"], "taskchain": "Copilot"}),
    ("SubTaskError", {"class": "asst::ProcessTask", "details": {}, "first": ["BattleStartAll"], "taskchain": "Copilot"}),
    ("TaskChainError", {"taskchain": "Copilot", "taskid": 1}),
    ("AllTasksCompleted", {}),
]


class CopilotResultTest(unittest.TestCase):
    def test_pre_battle_failure_not_started(self):
        r = CopilotResult.from_events(False, REAL_PRE_BATTLE_FAIL)
        self.assertFalse(r.started)
        self.assertIn("开始行动", r.hint)

    def test_battle_lost(self):
        ev = [("SubTaskExtraInfo", {"what": "CopilotAction", "details": {"action": "Deploy"}}),
              ("TaskChainError", {"taskchain": "Copilot"})]
        r = CopilotResult.from_events(False, ev)
        self.assertTrue(r.started)
        self.assertFalse(r.ok)

    def test_battle_won(self):
        ev = [("SubTaskExtraInfo", {"what": "CopilotAction", "details": {}}), ("TaskChainCompleted", {})]
        r = CopilotResult.from_events(True, ev)
        self.assertTrue(r.ok and r.started)


if __name__ == "__main__":
    unittest.main()
