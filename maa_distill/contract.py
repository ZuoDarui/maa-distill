"""危机合约作业解析。

危机合约同一张图会有不同风险等级（tag 组合）的作业，作业 JSON 本身没有结构化的等级字段，
作者通常把它写在标题/描述里，例如：
    "危机合约#12 4/3日替 10级tag 迷雾战区 5人"
    "起源行动3.21每日轮替8三人迷雾战区"
这里从文本里提取风险等级和人数，供 plan / run 按 --min-risk / --max-opers 筛选。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Copilot

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_RISK = re.compile(r"(?:风险|等级|risk)?\s*(\d{1,2})\s*(?:级|tag|Tag|TAG|分)")
_ROTATION = re.compile(r"轮替\s*(\d{1,2})")
_PEOPLE = re.compile(r"(\d{1,2}|[一二两三四五六七八九十])\s*(?:人|干员)")


@dataclass
class ContractInfo:
    risk: int | None       # 风险等级；解析不到为 None
    opers: int             # 实际编队人数（opers + groups）
    declared_opers: int | None  # 标题里声明的人数


def is_contract_stage(stage_name: str) -> bool:
    return "rune" in stage_name


def parse(cp: Copilot) -> ContractInfo:
    doc = cp.raw.get("doc") or {}
    text = f"{doc.get('title', '')} {doc.get('details', '')}"
    risk = None
    m = _RISK.search(text) or _ROTATION.search(text)
    if m:
        v = int(m.group(1))
        risk = v if 0 < v <= 40 else None
    people = None
    m = _PEOPLE.search(text)
    if m:
        g = m.group(1)
        people = int(g) if g.isdigit() else _CN_NUM.get(g)
    return ContractInfo(risk=risk, opers=len(cp.opers) + len(cp.groups), declared_opers=people)


def accept(cp: Copilot, min_risk: int | None = None, max_opers: int | None = None) -> bool:
    if min_risk is None and max_opers is None:
        return True
    info = parse(cp)
    if min_risk is not None and (info.risk is None or info.risk < min_risk):
        return False
    if max_opers is not None and info.opers > max_opers:
        return False
    return True
