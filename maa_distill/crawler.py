"""作业站（prts.maa.plus / zoot.plus）增量爬虫。

接口（已实测，2026-11）：
- GET /arknights/level                        全部关卡元数据
- GET /copilot/query?page=&limit=&order_by=id&desc=true[&level_keyword=<stage_id>]
      列表接口；返回的 content 不含 actions（只有 opers/groups）
- GET /copilot/get/{id}                       单个作业的完整 content（含 actions）

策略：
1. 列表按 id 倒序翻页，遇到已入库的 id 就停 → 增量更新只需要几次请求。
2. 详情（actions）按需拉取：只拉你关心的关卡，或每个关卡评分最高的前 N 个。
   全量 4.5 万份每秒 1 次也要十几个小时，没必要，也会给社区服务器添负担。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

from .config import Config
from .db import get_meta, set_meta

log = logging.getLogger(__name__)


class CopilotSiteClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._last = 0.0

    def _get(self, path: str, params: dict | None = None, retries: int = 3) -> dict:
        url = self.cfg.api_base.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(retries):
            wait = self.cfg.request_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.cfg.user_agent})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                if body.get("status_code") != 200:
                    raise RuntimeError(f"API error {body.get('status_code')}: {body.get('message')}")
                return body["data"]
            except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
                log.warning("GET %s failed (%s), retry %d", url, e, attempt + 1)
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"GET {url} failed after {retries} retries")

    def levels(self) -> list[dict]:
        return self._get("/arknights/level")

    def query(self, page: int, limit: int = 100, stage_id: str | None = None, order_by: str = "id") -> dict:
        params = {"page": page, "limit": limit, "order_by": order_by, "desc": "true"}
        if stage_id:
            params["level_keyword"] = stage_id
        return self._get("/copilot/query", params)

    def get(self, copilot_id: int) -> dict:
        return self._get(f"/copilot/get/{copilot_id}")


def _upsert(conn: sqlite3.Connection, item: dict, full: bool) -> None:
    content = item["content"]
    stage = json.loads(content).get("stage_name", "")
    if not full:
        # 列表接口没有 actions，已有完整版本时不要覆盖
        row = conn.execute("SELECT has_actions FROM copilots WHERE id=?", (item["id"],)).fetchone()
        if row and row["has_actions"]:
            conn.execute(
                "UPDATE copilots SET views=?, likes=?, dislikes=?, hot_score=?, rating_ratio=? WHERE id=?",
                (item.get("views", 0), item.get("like", 0), item.get("dislike", 0),
                 item.get("hot_score", 0), item.get("rating_ratio"), item["id"]),
            )
            return
    conn.execute(
        """INSERT OR REPLACE INTO copilots
           (id, stage_name, type, upload_time, uploader, views, likes, dislikes,
            hot_score, rating_ratio, content, has_actions)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (item["id"], stage, item.get("type"), item.get("upload_time"), item.get("uploader"),
         item.get("views", 0), item.get("like", 0), item.get("dislike", 0),
         item.get("hot_score", 0), item.get("rating_ratio"), content,
         1 if "actions" in json.loads(content) else 0),
    )


def sync_levels(conn: sqlite3.Connection, client: CopilotSiteClient) -> int:
    levels = client.levels()
    conn.executemany(
        "INSERT OR REPLACE INTO levels VALUES (?,?,?,?,?,?,?,?)",
        [(l["stage_id"], l["level_id"], l["cat_one"], l["cat_two"], l["cat_three"],
          l["name"], l.get("width"), l.get("height")) for l in levels],
    )
    conn.commit()
    return len(levels)


def sync_index(conn: sqlite3.Connection, client: CopilotSiteClient, stage_id: str | None = None,
               max_pages: int | None = None) -> int:
    """增量同步作业列表（不含 actions）。返回新入库数量。"""
    meta_key = f"max_id:{stage_id or '*'}"
    known_max = int(get_meta(conn, meta_key, "0"))
    new, page, top_id = 0, 1, known_max
    while True:
        data = client.query(page, stage_id=stage_id)
        items = data["data"]
        for it in items:
            top_id = max(top_id, it["id"])
            if it["id"] > known_max:
                new += 1
            _upsert(conn, it, full=False)
        conn.commit()
        log.info("page %d: %d items, %d new so far", page, len(items), new)
        reached_known = items and min(i["id"] for i in items) <= known_max
        if not data["has_next"] or reached_known or (max_pages and page >= max_pages):
            break
        page += 1
    set_meta(conn, meta_key, str(top_id))
    return new


def fetch_details(conn: sqlite3.Connection, client: CopilotSiteClient, ids: Iterable[int]) -> int:
    n = 0
    for cid in ids:
        try:
            _upsert(conn, client.get(cid), full=True)
            conn.commit()
            n += 1
        except RuntimeError as e:
            log.error("detail %s: %s", cid, e)
    return n


def ids_missing_details(conn: sqlite3.Connection, stage_name: str | None = None, top_per_stage: int = 5) -> list[int]:
    """每个关卡按点赞数取前 N 个尚未拉详情的作业。"""
    sql = """
      SELECT id FROM (
        SELECT id, has_actions,
               ROW_NUMBER() OVER (PARTITION BY stage_name ORDER BY likes - dislikes DESC, views DESC) AS rk
        FROM copilots {where}
      ) WHERE rk <= ? AND has_actions = 0
    """
    if stage_name:
        rows = conn.execute(sql.format(where="WHERE stage_name = ?"), (stage_name, top_per_stage)).fetchall()
    else:
        rows = conn.execute(sql.format(where=""), (top_per_stage,)).fetchall()
    return [r["id"] for r in rows]
