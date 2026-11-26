"""实跑结果记录：每次用 MAA 执行方案后写一条，下次排序时自动参考。"""

from __future__ import annotations

import sqlite3


def record_run(conn: sqlite3.Connection, plan_hash: str, stage_name: str, success: bool,
               copilot_id: int | None = None, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO runs(copilot_id, plan_hash, stage_name, success, detail) VALUES (?,?,?,?,?)",
        (copilot_id, plan_hash, stage_name, 1 if success else 0, detail),
    )
    conn.commit()


def own_stats(conn: sqlite3.Connection, plan_hash: str) -> tuple[int, int]:
    row = conn.execute(
        "SELECT COALESCE(SUM(success),0) AS s, COUNT(*) - COALESCE(SUM(success),0) AS f FROM runs WHERE plan_hash=?",
        (plan_hash,),
    ).fetchone()
    return int(row["s"]), int(row["f"])
