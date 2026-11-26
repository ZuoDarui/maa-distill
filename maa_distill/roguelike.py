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


# ---------------------------------------------------------------------------
# 招募优先级覆盖（增量资源）
#
# 已从 MAA 源码确认（Config/ResourceLoader.h、Roguelike/RoguelikeRecruitConfig.cpp）：
# - Asst.load(path, incremental_path=P) 会读取 P/resource/... 下存在的文件，不存在的文件跳过；
# - RoguelikeRecruitConfig::parse 会先 clear(theme) 再整份载入，
#   所以覆盖文件必须是"完整的 recruitment.json"，不能只写改动部分。
# 因此这里的做法是：复制 MAA 原版 → 按你的练度微调 recruit_priority → 写到 P。
# MAA 更新后重新生成一次即可，不会落后于上游策略。
# ---------------------------------------------------------------------------

def build_override(resource_dir: Path, theme: str, box: Box, bonus: int = 50) -> tuple[dict, list[str]]:
    """返回 (新的 recruitment.json, 改动说明)。

    规则（保守）：同一职能组里，你拥有且精二的干员 recruit_priority +bonus，
    精一 +bonus/2；不会改动组的顺序、开局干员和阵容完成条件。
    """
    import copy

    data = json.loads((resource_dir / "roguelike" / theme / "recruitment.json").read_text(encoding="utf-8"))
    out = copy.deepcopy(data)
    notes: list[str] = []
    for grp in out["priority"]:
        for o in grp["opers"]:
            own = box.get(o["name"])
            if own is None or "recruit_priority" not in o:
                continue
            add = bonus if own.elite >= 2 else bonus // 2 if own.elite == 1 else 0
            if add:
                o["recruit_priority"] += add
                notes.append(f"[{grp['name']}] {o['name']} 招募优先级 +{add}")
    return out, notes


def write_override(resource_dir: Path, theme: str, box: Box, incremental_root: Path, bonus: int = 50) -> tuple[Path, list[str]]:
    data, notes = build_override(resource_dir, theme, box, bonus)
    f = incremental_root / "resource" / "roguelike" / theme / "recruitment.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f, notes


# ---------------------------------------------------------------------------
# 逐关战绩：哪一关最容易翻车
#
# 已从 MAA 源码确认（Task/Roguelike/RoguelikeBattleTaskPlugin.cpp、RoguelikeSettlementTaskPlugin.cpp）：
# - 每场战斗开始前回调 SubTaskExtraInfo{what: "StageInfo", details: {name}}
# - 每局结算回调 SubTaskExtraInfo{what: "RoguelikeSettlement", details: {game_pass}}
# 因此：一局里 game_pass=false 时，最后一个 StageInfo 就是翻车关，之前的都算通过。
# ---------------------------------------------------------------------------

def parse_run_events(events: list[tuple[str, dict]]) -> list[tuple[str, bool]]:
    """把一次 Roguelike 任务的回调序列解析成 [(关卡名, 是否死在这关)]，可能跨多局。"""
    out: list[tuple[str, bool]] = []
    current: list[str] = []
    for name, d in events:
        if name != "SubTaskExtraInfo":
            continue
        what = d.get("what")
        if what == "StageInfo":
            stage = (d.get("details") or {}).get("name")
            if stage:
                current.append(stage)
        elif what == "RoguelikeSettlement":
            passed = bool((d.get("details") or {}).get("game_pass"))
            for i, st in enumerate(current):
                out.append((st, (not passed) and i == len(current) - 1))
            current = []
    # 任务被中断、没有结算：只记为通过的关，不判死亡
    out += [(st, False) for st in current]
    return out


def record_stages(conn, theme: str, results: list[tuple[str, bool]], config_tag: str = "") -> None:
    conn.executemany("INSERT INTO roguelike_stages(theme, stage, died, config_tag) VALUES (?,?,?,?)",
                     [(theme, st, int(died), config_tag) for st, died in results])
    conn.commit()


def deadly_stages(conn, theme: str, min_samples: int = 3) -> list[dict]:
    """按翻车率排序。翻车率高的关卡就是下一步要调整 autopilot 部署的对象。"""
    rows = conn.execute(
        """SELECT stage, COUNT(*) AS n, SUM(died) AS deaths FROM roguelike_stages
           WHERE theme=? GROUP BY stage HAVING n >= ? ORDER BY 1.0*SUM(died)/COUNT(*) DESC, n DESC""",
        (theme, min_samples)).fetchall()
    return [{"stage": r["stage"], "samples": r["n"], "deaths": r["deaths"],
             "death_rate": r["deaths"] / r["n"]} for r in rows]


def compare_configs(conn, theme: str) -> list[dict]:
    """不同招募覆盖版本（--bonus）的平均翻车率，越低越好。"""
    rows = conn.execute(
        """SELECT config_tag, COUNT(*) AS n, SUM(died) AS deaths FROM roguelike_stages
           WHERE theme=? GROUP BY config_tag ORDER BY 1.0*SUM(died)/COUNT(*)""", (theme,)).fetchall()
    return [{"config": r["config_tag"] or "原版", "stages": r["n"], "deaths": r["deaths"]} for r in rows]
