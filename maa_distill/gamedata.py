"""游戏数据：干员职业/分支、关卡别名。

干员数据直接读 MAA 自带的 resource/battle_data.json，MAA 更新后这里自动跟着更新。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class OperInfo:
    name: str
    profession: str        # CASTER / SNIPER / ...
    sub_profession: str    # 分支，如 phalanx（阵法术师）
    position: str          # MELEE / RANGED
    rarity: int


@lru_cache(maxsize=4)
def load_opers(battle_data_path: str) -> dict[str, OperInfo]:
    data = json.loads(Path(battle_data_path).read_text(encoding="utf-8"))
    out: dict[str, OperInfo] = {}
    for cid, c in data["chars"].items():
        if not cid.startswith("char_"):
            continue  # 跳过召唤物、装置
        out[c["name"]] = OperInfo(
            name=c["name"],
            profession=c.get("profession", ""),
            sub_profession=c.get("subProfessionId", ""),
            position=c.get("position", ""),
            rarity=int(c.get("rarity", 0)),
        )
    return out


def find_battle_data(maa_dir: Path, maa_source_dir: Path) -> Path:
    for p in (maa_dir / "resource" / "battle_data.json", maa_source_dir / "resource" / "battle_data.json"):
        if p.exists():
            return p
    raise FileNotFoundError("找不到 battle_data.json，请先运行 `python -m maa_distill update-maa`")


def stage_aliases(conn: sqlite3.Connection, keyword: str) -> tuple[str | None, set[str]]:
    """把用户输入的关卡（代号 / 中文名 / stage_id）解析成作业里可能出现的所有写法。

    作业的 stage_name 字段写法不统一：有的写 stage_id（act55side_s02），
    有的写代号（TL-S-2），有的写"代号 中文名"。
    """
    rows = conn.execute(
        "SELECT * FROM levels WHERE stage_id=? OR level_id=? OR cat_three=? OR name=?",
        (keyword, keyword, keyword, keyword),
    ).fetchall()
    if not rows:
        return None, {keyword}
    # 突袭版 stage_id 带 "#f#" 后缀，作业写的是普通版 id，统一折叠到普通版
    def base(sid: str) -> str:
        return sid.split("#", 1)[0]

    # 有多个匹配时（复刻）取 stage_id 最大的那个
    canonical = sorted(base(r["stage_id"]) for r in rows)[-1]
    rows = [r for r in rows if base(r["stage_id"]) == canonical]
    aliases = {canonical, keyword}
    for r in rows:
        aliases |= {r["level_id"], r["cat_three"], r["name"], f"{r['cat_three']} {r['name']}"}
    return canonical, {a for a in aliases if a}
