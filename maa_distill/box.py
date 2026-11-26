"""你的干员 box（拥有哪些干员、练度如何）。

来源有两种：
1. MAA 的 OperBox 任务识别结果（回调消息 SubTaskExtraInfo → what=OperBoxInfo 的 details）
   runner.scan_box() 会自动跑一次并保存。
2. 手写 JSON（适合先离线体验）：
   [{"name": "史尔特尔", "elite": 2, "level": 90, "skill_level": 10}, ...]
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .schema import Requirements


@dataclass
class OwnedOper:
    name: str
    elite: int
    level: int
    potential: int = 1
    rarity: int = 0
    skill_level: int = -1   # OperBox 不识别技能等级，-1 表示未知（按满足处理）
    module: int = -1

    def meets(self, req: Requirements) -> bool:
        if req.elite >= 0 and self.elite < req.elite:
            return False
        if req.elite >= 0 and self.elite == req.elite and req.level >= 0 and self.level < req.level:
            return False
        if req.elite < 0 and req.level >= 0 and self.elite == 0 and self.level < req.level:
            return False
        if req.skill_level >= 0 and self.skill_level >= 0 and self.skill_level < req.skill_level:
            return False
        return True

    def power(self) -> float:
        """粗略练度分，用于在多个候选里挑练度高的。"""
        return self.rarity * 100 + self.elite * 30 + self.level * 0.3 + max(self.skill_level, 0)


Box = dict[str, OwnedOper]


def from_operbox_details(details: dict) -> Box:
    return {
        o["name"]: OwnedOper(name=o["name"], elite=o["elite"], level=o["level"],
                             potential=o.get("potential", 1), rarity=o.get("rarity", 0))
        for o in details.get("own_opers", []) if o.get("own", True)
    }


def from_json_file(path: Path) -> Box:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "own_opers" in data:
        return from_operbox_details(data)
    return {d["name"]: OwnedOper(**{k: d[k] for k in d if k in OwnedOper.__dataclass_fields__}) for d in data}


def save(conn: sqlite3.Connection, box: Box) -> None:
    conn.execute("DELETE FROM box")
    conn.executemany(
        "INSERT INTO box VALUES (?,?,?,?,?,?,?)",
        [(o.name, o.elite, o.level, o.potential, o.rarity, o.skill_level, o.module) for o in box.values()],
    )
    conn.commit()


def load(conn: sqlite3.Connection) -> Box:
    return {r["name"]: OwnedOper(**dict(r)) for r in conn.execute("SELECT * FROM box")}
