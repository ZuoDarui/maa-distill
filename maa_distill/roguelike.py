"""肉鸽（集成战略）分析 —— 第二阶段功能的起点。

作业站基本没有肉鸽作业：MAA 打肉鸽靠的是 resource/roguelike/<主题>/ 下的
  recruitment.json（招募优先级）、autopilot/*.json（每个关卡的部署方案）、shopping.json 等。
所以肉鸽的"蒸馏"对象是 MAA 自带策略 + 你自己的运行日志，而不是作业站。

本模块目前提供：
- coverage(): 对照你的 box，列出该主题策略里的核心干员你有哪些、缺哪些，
  缺的核心干员会严重拉低成功率，这是调整策略的第一步。
后续计划见 docs/PLAN.md 的"阶段 4"。
"""

from __future__ import annotations

import json
from pathlib import Path

from .box import Box

THEMES = {"Phantom": "傀影", "Mizuki": "水月", "Sami": "萨米", "Sarkaz": "萨卡兹",
          "JieGarden": "界园", "BlackFlow": "黑流树海"}


def coverage(resource_dir: Path, theme: str, box: Box) -> dict:
    data = json.loads((resource_dir / "roguelike" / theme / "recruitment.json").read_text(encoding="utf-8"))
    key_owned, key_missing, groups = [], [], {}
    for grp in data["priority"]:
        owned_in_group = []
        for o in grp["opers"]:
            if o["name"] in box:
                owned_in_group.append(o["name"])
            if o.get("is_key"):
                (key_owned if o["name"] in box else key_missing).append(
                    (o["name"], o.get("recruit_priority", 0)))
        groups[grp["name"]] = owned_in_group
    key_missing.sort(key=lambda t: -t[1])
    key_owned.sort(key=lambda t: -t[1])
    return {
        "theme": theme,
        "key_owned": key_owned,
        "key_missing": key_missing,
        "empty_groups": [g for g, v in groups.items() if not v],
    }
