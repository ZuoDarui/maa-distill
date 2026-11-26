"""蒸馏 + 方案生成。

对一个关卡：
1. 取出该关卡所有作业（含 actions 的完整版）。
2. 对照你的 box 检查每份作业：哪些位置你能直接上，哪些缺人。
3. 缺人的位置用"同分支 > 同职业同站位"的干员替补，生成改编方案（新作业 JSON）。
   改编方式：把缺的干员改写成同名的 group，group 里放替补候选。
   MAA 执行 group 时会自动挑练度最高的那个，actions 里按名字引用的地方全部不用改。
4. 每份候选方案打分 = 后验成功率 × 替补惩罚，按分数排序。
5. 同一份作业会生成多个替补组合（variants），某个组合实跑失败后分数下降，
   下次自动换下一个组合 —— 这就是"制定 → 实跑 → 优化"的循环。
"""

from __future__ import annotations

import copy
import itertools
import json
import sqlite3
from dataclasses import dataclass, field

from .box import Box, OwnedOper
from .feedback import own_stats
from .gamedata import OperInfo
from .schema import Copilot, Oper
from .scoring import posterior, site_prior

# 替补惩罚：同分支几乎等价，同职业差一些，跨职业不允许
PENALTY_SAME_BRANCH = 0.8
PENALTY_SAME_CLASS = 0.5


@dataclass
class SlotResolution:
    slot: str                      # 原作业中的干员名或群组名
    is_group: bool
    chosen: list[str]              # 你 box 里可以填这个位置的干员（按优先级）
    substituted: bool = False      # 是否用了替补
    penalty: float = 1.0
    note: str = ""


@dataclass
class Plan:
    copilot_id: int | None
    base: Copilot
    content: dict                  # 实际要交给 MAA 的作业 JSON
    slots: list[SlotResolution]
    prior: float
    successes: int = 0
    failures: int = 0
    score: float = 0.0
    plan_hash: str = ""
    reasons: list[str] = field(default_factory=list)

    @property
    def substitutions(self) -> list[SlotResolution]:
        return [s for s in self.slots if s.substituted]


def _candidates_for(oper: Oper, box: Box, info: dict[str, OperInfo], used: set[str]) -> list[tuple[OwnedOper, float]]:
    """为一个缺失干员找替补，返回 [(干员, 惩罚系数)]，按优先级排序。"""
    target = info.get(oper.name)
    if target is None:
        return []  # 不认识的名字（如召唤物），无法替补
    out: list[tuple[OwnedOper, float]] = []
    for o in box.values():
        if o.name in used or o.name == oper.name:
            continue
        oi = info.get(o.name)
        if oi is None:
            continue
        if oi.sub_profession == target.sub_profession:
            pen = PENALTY_SAME_BRANCH
        elif oi.profession == target.profession and oi.position == target.position:
            pen = PENALTY_SAME_CLASS
        else:
            continue
        # 练度差太多的替补再打折（原作业要求精二而你只有精一）
        if oper.requirements.elite >= 0 and o.elite < oper.requirements.elite:
            pen *= 0.6
        out.append((o, pen))
    out.sort(key=lambda t: (t[1], t[0].power()), reverse=True)
    return out


def _skill_for(sub: OwnedOper, original_skill: int) -> int:
    """替补用几技能：尽量和原作业一致，没有就用最高可用技能。"""
    max_skill = 3 if sub.rarity >= 6 and sub.elite >= 2 else 2 if sub.rarity >= 4 and sub.elite >= 1 else 1
    if original_skill <= 0:
        return 0
    return min(original_skill, max_skill)


def resolve(copilot: Copilot, box: Box, info: dict[str, OperInfo],
            max_variants: int = 3) -> list[tuple[list[SlotResolution], bool]]:
    """解析每个编队位。返回最多 max_variants 种替补组合；第二项为是否可行。"""
    used: set[str] = set()
    fixed: list[SlotResolution] = []
    missing: list[Oper] = []

    for o in copilot.opers:
        own = box.get(o.name)
        if own and own.meets(o.requirements):
            used.add(o.name)
            fixed.append(SlotResolution(o.name, False, [o.name]))
        else:
            missing.append(o)

    for g in copilot.groups:
        ok = [m.name for m in g.opers if m.name in box and box[m.name].meets(m.requirements) and m.name not in used]
        if ok:
            ok.sort(key=lambda n: box[n].power(), reverse=True)
            used.add(ok[0])
            fixed.append(SlotResolution(g.name, True, ok))
        else:
            # 群组整体缺人：用群组第一个成员的职业找替补
            missing.append(Oper(name=g.opers[0].name, skill=g.opers[0].skill,
                                requirements=g.opers[0].requirements,
                                raw={**g.opers[0].raw, "_group": g.name}) if g.opers else Oper(name=g.name))

    if not missing:
        return [(fixed, True)]

    per_slot: list[list[tuple[OwnedOper, float]]] = []
    for m in missing:
        cands = _candidates_for(m, box, info, used)[:max_variants]
        if not cands:
            slot_name = m.raw.get("_group", m.name)
            return [(fixed + [SlotResolution(slot_name, "_group" in m.raw, [], True, 0.0,
                                             f"缺少 {m.name}，box 中没有同职业替补")], False)]
        per_slot.append(cands)

    variants = []
    for combo in itertools.product(*per_slot):
        names = [c[0].name for c in combo]
        if len(set(names)) != len(names):
            continue  # 同一个人不能顶两个位置
        slots = list(fixed)
        for m, (sub, pen) in zip(missing, combo):
            slot_name = m.raw.get("_group", m.name)
            slots.append(SlotResolution(slot_name, "_group" in m.raw, [sub.name], True, pen,
                                        f"{m.name} → {sub.name}"))
        variants.append((slots, True))
    variants.sort(key=lambda v: _penalty(v[0]), reverse=True)
    return variants[:max_variants] or [(fixed, False)]


def _penalty(slots: list[SlotResolution]) -> float:
    p = 1.0
    for s in slots:
        p *= s.penalty
    return p


def build_content(copilot: Copilot, slots: list[SlotResolution], box: Box) -> dict:
    """根据替补结果生成新的作业 JSON。"""
    content = copy.deepcopy(copilot.raw)
    subs = {s.slot: s for s in slots if s.substituted}
    if not subs:
        return content

    orig_by_name = {o.name: o for o in copilot.opers}
    new_opers, new_groups = [], list(content.get("groups", []))
    for o_raw in content.get("opers", []):
        s = subs.get(o_raw["name"])
        if s is None:
            new_opers.append(o_raw)
            continue
        orig = orig_by_name[o_raw["name"]]
        members = []
        for n in s.chosen:
            m = {k: v for k, v in o_raw.items() if k not in ("name", "requirements", "skill")}
            m["name"] = n
            m["skill"] = _skill_for(box[n], orig.skill)
            members.append(m)
        # 关键技巧：group 名 = 原干员名，actions 里的 "name" 引用无需改动
        new_groups.append({"name": o_raw["name"], "opers": members})
    for g in new_groups:
        s = subs.get(g["name"])
        if s and s.is_group:
            template = g["opers"][0] if g["opers"] else {}
            g["opers"] = [{**{k: v for k, v in template.items() if k not in ("name", "requirements")},
                           "name": n} for n in s.chosen]
    content["opers"] = new_opers
    content["groups"] = new_groups
    doc = content.setdefault("doc", {})
    doc["title"] = "[改编] " + doc.get("title", "")
    doc["details"] = ("替补: " + "; ".join(s.note for s in subs.values()) + "\n\n" + doc.get("details", ""))
    return content


def plans_for_stage(conn: sqlite3.Connection, aliases: set[str], box: Box, info: dict[str, OperInfo],
                    prior_strength: float = 4.0, include_infeasible: bool = False,
                    min_risk: int | None = None, max_opers: int | None = None) -> list[Plan]:
    from .contract import accept

    q = ",".join("?" * len(aliases))
    rows = conn.execute(
        f"SELECT * FROM copilots WHERE has_actions=1 AND stage_name IN ({q})", tuple(aliases)
    ).fetchall()
    plans: list[Plan] = []
    for r in rows:
        try:
            cp = Copilot.from_json(r["content"])
        except (json.JSONDecodeError, KeyError):
            continue
        if not accept(cp, min_risk, max_opers):
            continue  # 危机合约：风险等级/人数不满足筛选条件
        prior = site_prior(r["likes"], r["dislikes"], r["views"])
        for slots, feasible in resolve(cp, box, info):
            if not feasible and not include_infeasible:
                continue
            content = build_content(cp, slots, box) if feasible else cp.to_json()
            p = Plan(copilot_id=r["id"], base=cp, content=content, slots=slots, prior=prior)
            p.plan_hash = Copilot.from_json(content).content_hash()
            p.successes, p.failures = own_stats(conn, p.plan_hash)
            p.score = posterior(prior, p.successes, p.failures, prior_strength) * _penalty(slots) if feasible else 0.0
            p.reasons.append(f"站内先验 {prior:.2f}，实跑 {p.successes} 胜 {p.failures} 负，替补系数 {_penalty(slots):.2f}")
            plans.append(p)
    plans.sort(key=lambda p: p.score, reverse=True)
    return plans


def stage_stats(conn: sqlite3.Connection, aliases: set[str]) -> dict:
    """关卡统计：最常用干员、最常用部署点。帮助你看懂"这关大家怎么打"。"""
    from collections import Counter

    q = ",".join("?" * len(aliases))
    rows = conn.execute(f"SELECT content, likes, dislikes, has_actions FROM copilots WHERE stage_name IN ({q})",
                        tuple(aliases)).fetchall()
    oper_count, loc_count = Counter(), Counter()
    for r in rows:
        cp = Copilot.from_json(r["content"])
        w = 1 + max(r["likes"] - r["dislikes"], 0) ** 0.5
        for name in [o.name for o in cp.opers] + [m.name for g in cp.groups for m in g.opers[:1]]:
            oper_count[name] += w
        for a in cp.actions:
            if a.type == "Deploy" and a.location:
                loc_count[(a.name, a.location)] += w
    return {
        "copilots": len(rows),
        "with_actions": sum(r["has_actions"] for r in rows),
        "top_opers": oper_count.most_common(15),
        "top_deploys": loc_count.most_common(15),
    }
