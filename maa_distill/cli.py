"""命令行入口：python -m maa_distill <命令>

常用流程：
    python -m maa_distill update-maa              # 下载/更新 MAA 本体
    python -m maa_distill crawl                   # 增量同步作业站
    python -m maa_distill box --file mybox.json   # 导入 box（或 --scan 用 MAA 识别）
    python -m maa_distill stats TL-S-2            # 看这关大家怎么打
    python -m maa_distill plan TL-S-2             # 生成适配你 box 的方案
    python -m maa_distill run TL-S-2 --until-success 3   # 实跑并自动换方案
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import box as boxmod
from . import crawler, db, feedback, gamedata, planner, roguelike, updater
from .config import Config


def _ctx(args):
    cfg = Config.load(Path(args.config) if args.config else None)
    return cfg, db.connect(cfg.db_path)


def cmd_update_maa(args):
    cfg, _ = _ctx(args)
    if not args.skip_runtime:
        print("MAA 运行时版本：", updater.update_runtime(cfg, force=args.force))
    print("MAA 源码：", updater.update_source(cfg))


def cmd_crawl(args):
    cfg, conn = _ctx(args)
    client = crawler.CopilotSiteClient(cfg)
    print("关卡数：", crawler.sync_levels(conn, client))
    stage_id = None
    if args.stage:
        stage_id, _ = gamedata.stage_aliases(conn, args.stage)
    print("新增作业：", crawler.sync_index(conn, client, stage_id=stage_id, max_pages=args.max_pages))
    aliases = gamedata.stage_aliases(conn, args.stage)[1] if args.stage else None
    ids: list[int] = []
    for a in (aliases or [None]):
        ids += crawler.ids_missing_details(conn, a, top_per_stage=args.top)
    ids = sorted(set(ids))
    if args.no_details:
        print(f"跳过详情，待拉取 {len(ids)} 份")
        return
    print(f"拉取 {len(ids)} 份作业详情（约 {len(ids) * cfg.request_interval / 60:.0f} 分钟）")
    print("完成：", crawler.fetch_details(conn, client, ids))


def cmd_box(args):
    cfg, conn = _ctx(args)
    if args.scan:
        from .runner import MaaRunner
        with MaaRunner(cfg) as r:
            details = r.scan_box()
        Path(cfg.db_path.parent / "operbox.json").write_text(json.dumps(details, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
        b = boxmod.from_operbox_details(details)
    elif args.file:
        b = boxmod.from_json_file(Path(args.file))
    else:
        b = boxmod.load(conn)
        print(f"当前 box：{len(b)} 名干员")
        return
    boxmod.save(conn, b)
    print(f"已保存 {len(b)} 名干员")


def cmd_stats(args):
    cfg, conn = _ctx(args)
    sid, aliases = gamedata.stage_aliases(conn, args.stage)
    s = planner.stage_stats(conn, aliases)
    print(f"关卡 {args.stage}（{sid}）：作业 {s['copilots']} 份，已拉详情 {s['with_actions']} 份")
    print("常用干员：", ", ".join(f"{n}({w:.0f})" for n, w in s["top_opers"]))
    print("常用部署：", ", ".join(f"{n}@{tuple(l)}" for (n, l), _ in s["top_deploys"]))


def _plans(cfg, conn, stage, args=None):
    sid, aliases = gamedata.stage_aliases(conn, stage)
    b = boxmod.load(conn)
    if not b:
        sys.exit("box 为空，请先运行 `box --file` 或 `box --scan`")
    info = gamedata.load_opers(str(gamedata.find_battle_data(cfg.maa_dir, cfg.maa_source_dir)))
    return sid, planner.plans_for_stage(conn, aliases, b, info, cfg.prior_strength,
                                        min_risk=getattr(args, "min_risk", None),
                                        max_opers=getattr(args, "max_opers", None))


def _write_plan(cfg, stage, p) -> Path:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    f = cfg.output_dir / f"{stage}_{p.copilot_id}_{p.plan_hash}.json"
    f.write_text(json.dumps(p.content, ensure_ascii=False, indent=2), encoding="utf-8")
    return f


def cmd_plan(args):
    cfg, conn = _ctx(args)
    sid, plans = _plans(cfg, conn, args.stage, args)
    if not plans:
        print("没有可行方案。可尝试：crawl --stage 拉更多作业详情 / 检查 box / 等待作业站出新作业")
        return
    for i, p in enumerate(plans[: args.top], 1):
        f = _write_plan(cfg, args.stage, p)
        subs = "; ".join(s.note for s in p.substitutions) or "无需替补"
        print(f"#{i} 分数 {p.score:.3f} | 作业 {p.copilot_id} {p.base.title}\n   {subs}\n   {p.reasons[0]}\n   → {f}")


def cmd_run(args):
    cfg, conn = _ctx(args)
    from .runner import MaaRunner

    successes = 0
    with MaaRunner(cfg) as r:
        for attempt in range(args.max_attempts):
            sid, plans = _plans(cfg, conn, args.stage, args)  # 每次重新排序：上次失败的会掉下去
            if not plans:
                print("没有可行方案")
                return
            p = plans[0]
            f = _write_plan(cfg, args.stage, p)
            print(f"[{attempt + 1}] 执行 {f.name}（分数 {p.score:.3f}）")
            ok, detail = r.run_copilot(f, kind=args.kind)
            feedback.record_run(conn, p.plan_hash, sid or args.stage, ok, p.copilot_id, detail)
            print("   成功" if ok else f"   失败 {detail}")
            successes += ok
            if successes >= args.until_success:
                break


def cmd_record(args):
    """手动记录结果（例如你用 MAA 图形界面跑的）。"""
    cfg, conn = _ctx(args)
    from .schema import Copilot

    content = json.loads(Path(args.file).read_text(encoding="utf-8"))
    cp = Copilot.from_json(content)
    feedback.record_run(conn, cp.content_hash(), cp.stage_name, args.result == "win")
    print("已记录")


def cmd_roguelike(args):
    cfg, conn = _ctx(args)
    res = cfg.maa_dir / "resource"
    if not res.exists():
        res = cfg.maa_source_dir / "resource"
    c = roguelike.coverage(res, args.theme, boxmod.load(conn))
    print(f"{roguelike.THEMES.get(args.theme, args.theme)}：拥有核心干员 {len(c['key_owned'])}，缺 {len(c['key_missing'])}")
    print("缺少的核心干员（按招募优先级）：", ", ".join(n for n, _ in c["key_missing"][:20]))
    print("完全空缺的职能组：", ", ".join(c["empty_groups"][:20]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="maa_distill")
    ap.add_argument("--config")
    ap.add_argument("-v", "--verbose", action="store_true")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("update-maa", help="下载/更新 MAA 本体和源码")
    p.add_argument("--force", action="store_true")
    p.add_argument("--skip-runtime", action="store_true", help="只更新源码仓库")
    p.set_defaults(func=cmd_update_maa)

    p = sp.add_parser("crawl", help="增量同步作业站")
    p.add_argument("--stage", help="只同步某关（代号/中文名/stage_id）")
    p.add_argument("--top", type=int, default=5, help="每关拉取详情的作业数")
    p.add_argument("--max-pages", type=int)
    p.add_argument("--no-details", action="store_true")
    p.set_defaults(func=cmd_crawl)

    p = sp.add_parser("box", help="导入/查看干员 box")
    p.add_argument("--file")
    p.add_argument("--scan", action="store_true", help="用 MAA 在模拟器里识别")
    p.set_defaults(func=cmd_box)

    p = sp.add_parser("stats", help="关卡统计")
    p.add_argument("stage")
    p.set_defaults(func=cmd_stats)

    p = sp.add_parser("plan", help="生成适配 box 的方案")
    p.add_argument("stage")
    p.add_argument("--min-risk", type=int, help="危机合约：只要风险等级 ≥ N 的作业")
    p.add_argument("--max-opers", type=int, help="只要编队人数 ≤ N 的作业（如危机合约少人挑战）")
    p.add_argument("--top", type=int, default=5)
    p.set_defaults(func=cmd_plan)

    p = sp.add_parser("run", help="用 MAA 实跑，失败自动换方案")
    p.add_argument("stage")
    p.add_argument("--min-risk", type=int, help="危机合约：只要风险等级 ≥ N 的作业")
    p.add_argument("--max-opers", type=int, help="只要编队人数 ≤ N 的作业（如危机合约少人挑战）")
    p.add_argument("--kind", default="Copilot", choices=["Copilot", "SSSCopilot", "ParadoxCopilot"])
    p.add_argument("--until-success", type=int, default=1)
    p.add_argument("--max-attempts", type=int, default=5)
    p.set_defaults(func=cmd_run)

    p = sp.add_parser("record", help="手动记录一次结果")
    p.add_argument("file")
    p.add_argument("result", choices=["win", "lose"])
    p.set_defaults(func=cmd_record)

    p = sp.add_parser("roguelike", help="肉鸽策略覆盖度分析")
    p.add_argument("theme", choices=list(roguelike.THEMES))
    p.set_defaults(func=cmd_roguelike)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    args.func(args)
