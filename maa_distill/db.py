"""SQLite 本地数据库。

三类数据：
- copilots / levels：从作业站爬下来的原始数据（只增不改，方便重新蒸馏）
- box：你自己的干员练度
- runs：你每次用 MAA 跑作业的结果（用于"不断优化"）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS copilots (
    id            INTEGER PRIMARY KEY,
    stage_name    TEXT NOT NULL,
    type          TEXT,
    upload_time   TEXT,
    uploader      TEXT,
    views         INTEGER DEFAULT 0,
    likes         INTEGER DEFAULT 0,
    dislikes      INTEGER DEFAULT 0,
    hot_score     REAL DEFAULT 0,
    rating_ratio  REAL,
    content       TEXT NOT NULL,      -- 作业 JSON（含 actions 的完整版本）
    has_actions   INTEGER DEFAULT 0,
    fetched_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_copilots_stage ON copilots(stage_name);

CREATE TABLE IF NOT EXISTS levels (
    stage_id  TEXT PRIMARY KEY,
    level_id  TEXT,
    cat_one   TEXT,   -- 活动关卡 / 主题曲 / 悖论模拟 / 保全派驻 / 危机合约 ...
    cat_two   TEXT,
    cat_three TEXT,   -- 关卡代号，如 TL-S-2
    name      TEXT,
    width     INTEGER,
    height    INTEGER
);

CREATE TABLE IF NOT EXISTS box (
    name      TEXT PRIMARY KEY,
    elite     INTEGER,
    level     INTEGER,
    potential INTEGER,
    rarity    INTEGER,
    skill_level INTEGER DEFAULT -1,
    module    INTEGER DEFAULT -1
);

CREATE TABLE IF NOT EXISTS runs (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    copilot_id INTEGER,          -- 原作业 id；自己生成的方案为 NULL
    plan_hash  TEXT NOT NULL,    -- 实际执行的作业内容哈希
    stage_name TEXT NOT NULL,
    success    INTEGER NOT NULL,
    detail     TEXT,
    ran_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_runs_plan ON runs(plan_hash);

CREATE TABLE IF NOT EXISTS roguelike_stages (
    theme      TEXT NOT NULL,
    stage      TEXT NOT NULL,     -- 关卡名（MAA StageInfo 回调）
    died       INTEGER NOT NULL,  -- 1 = 本局在这一关结束且未通关
    config_tag TEXT,              -- 使用的招募覆盖版本，用于 A/B 对比
    ran_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
    conn.commit()
