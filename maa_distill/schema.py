"""MAA 作业 JSON 的 Python 数据模型。

字段含义见 MAA 文档 docs/zh-cn/protocol/copilot-schema.md。
这里只建模"蒸馏"需要的字段，其余字段原样保存在 raw 里，写回时不会丢。
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# 中文 action 类型 → 英文（作业站只接受英文，统一成英文方便统计）
ACTION_TYPE_ALIASES = {
    "部署": "Deploy", "技能": "Skill", "撤退": "Retreat", "二倍速": "SpeedUp",
    "子弹时间": "BulletTime", "技能用法": "SkillUsage", "打印": "Output",
    "摆完挂机": "SkillDaemon", "移动镜头": "MoveCamera", "重置全局计时器": "ResetStopwatch",
    "点击": "Click", "滑动": "Swipe", "设置单位坐标": "SetUnitLocation",
}


@dataclass
class Requirements:
    elite: int = -1
    level: int = -1
    skill_level: int = -1
    module: int = -1

    @classmethod
    def from_json(cls, d: dict | None) -> "Requirements":
        d = d or {}
        return cls(
            elite=int(d.get("elite", -1)),
            level=int(d.get("level", -1)),
            skill_level=int(d.get("skill_level", -1)),
            module=int(d.get("module", -1)),
        )


@dataclass
class Oper:
    name: str
    skill: int = 0
    requirements: Requirements = field(default_factory=Requirements)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, d: dict) -> "Oper":
        return cls(
            name=d["name"],
            skill=int(d.get("skill", 0) or 0),
            requirements=Requirements.from_json(d.get("requirements")),
            raw=d,
        )


@dataclass
class Group:
    name: str
    opers: list[Oper]


@dataclass
class Action:
    type: str
    name: str | None
    location: tuple[int, int] | None
    direction: str | None
    raw: dict

    @classmethod
    def from_json(cls, d: dict) -> "Action":
        t = d.get("type", "Deploy")
        t = ACTION_TYPE_ALIASES.get(t, t)
        loc = d.get("location")
        return cls(
            type=t,
            name=d.get("name"),
            location=tuple(loc) if isinstance(loc, list) and len(loc) == 2 else None,
            direction=d.get("direction"),
            raw=d,
        )


@dataclass
class Copilot:
    stage_name: str
    opers: list[Oper]
    groups: list[Group]
    actions: list[Action]
    raw: dict

    @classmethod
    def from_json(cls, d: dict | str) -> "Copilot":
        if isinstance(d, str):
            d = json.loads(d)
        return cls(
            stage_name=d.get("stage_name", ""),
            opers=[Oper.from_json(o) for o in d.get("opers", [])],
            groups=[
                Group(name=g["name"], opers=[Oper.from_json(o) for o in g.get("opers", [])])
                for g in d.get("groups", [])
            ],
            actions=[Action.from_json(a) for a in d.get("actions", [])],
            raw=d,
        )

    @property
    def title(self) -> str:
        return (self.raw.get("doc") or {}).get("title", "")

    def slot_names(self) -> list[str]:
        """作业中每个"编队位"的名字：单个干员名或群组名。"""
        return [o.name for o in self.opers] + [g.name for g in self.groups]

    def to_json(self) -> dict:
        return copy.deepcopy(self.raw)

    def content_hash(self) -> str:
        """只对影响战斗的字段取哈希，doc 改了不算新方案。"""
        key = {k: self.raw.get(k) for k in ("stage_name", "opers", "groups", "actions")}
        s = json.dumps(key, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def load_any(obj: Any) -> Copilot:
    return obj if isinstance(obj, Copilot) else Copilot.from_json(obj)
