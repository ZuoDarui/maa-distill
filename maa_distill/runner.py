"""通过 MAA 官方 Python 绑定驱动模拟器：扫描 box、执行作业、收集结果。

我们不修改 MAA 的任何 C++ 代码，只调用它的公开接口：
    Asst.load(...) → Asst() → connect(adb) → append_task("Copilot", {...}) → start()
所以 MAA 升级（update-maa）后，这里不用改就能用上新功能。
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import time
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)


def _import_asst(cfg: Config):
    binding = cfg.maa_source_dir / "src" / "Python"
    if not (binding / "asst" / "asst.py").exists():
        raise FileNotFoundError(f"找不到 MAA Python 绑定：{binding}。请确认 maa_source_dir 配置正确")
    if str(binding) not in sys.path:
        sys.path.insert(0, str(binding))
    from asst.asst import Asst  # type: ignore
    from asst.utils import InstanceOptionType, Message  # type: ignore
    return Asst, InstanceOptionType, Message


class MaaRunner:
    """一个 MAA 实例。用法：

        with MaaRunner(cfg) as r:
            box = r.scan_box()
            ok, detail = r.run_copilot(Path("plan.json"))
    """

    def __init__(self, cfg: Config, incremental_resource: Path | None = None):
        self.cfg = cfg
        Asst, self._Opt, self._Msg = _import_asst(cfg)
        if not Asst.load(path=cfg.maa_dir, incremental_path=incremental_resource,
                         user_dir=cfg.db_path.parent / "maa_user"):
            raise RuntimeError(f"MAA 资源加载失败：{cfg.maa_dir}")
        self._events: "queue.Queue[tuple[str, dict]]" = queue.Queue()

        @Asst.CallBackType
        def _cb(msg, details, _arg):
            try:
                name = self._Msg(msg).name
            except ValueError:
                name = str(msg)
            self._events.put((name, json.loads(details.decode("utf-8"))))

        self._cb = _cb  # 必须保存引用，否则会被 GC 导致崩溃
        self.asst = Asst(callback=_cb)
        self.asst.set_instance_option(self._Opt.touch_type, cfg.touch_type)

    def __enter__(self):
        if not self.asst.connect(self.cfg.adb_path, self.cfg.adb_address):
            raise RuntimeError(f"连接模拟器失败：{self.cfg.adb_address}")
        return self

    def __exit__(self, *exc):
        self.asst.stop()

    def _run(self, task: str, params: dict, timeout: float = 3600) -> tuple[bool, list[tuple[str, dict]]]:
        while not self._events.empty():
            self._events.get_nowait()
        if not self.asst.append_task(task, params):
            raise RuntimeError(f"append_task 失败：{task} {params}")
        self.asst.start()
        events, ok, deadline = [], False, time.time() + timeout
        while time.time() < deadline:
            try:
                name, d = self._events.get(timeout=1)
            except queue.Empty:
                continue
            events.append((name, d))
            if name == "TaskChainError":
                ok = False
            elif name == "TaskChainCompleted":
                ok = True
            elif name == "AllTasksCompleted":
                break
        self.asst.stop()
        return ok, events

    def scan_box(self) -> dict:
        """运行 OperBox 识别，返回 OperBoxInfo 的 details（可交给 box.from_operbox_details）。"""
        _, events = self._run("OperBox", {}, timeout=900)
        for name, d in reversed(events):
            if name == "SubTaskExtraInfo" and d.get("what") == "OperBoxInfo" and d["details"].get("done"):
                return d["details"]
        raise RuntimeError("没有收到 OperBox 识别结果")

    def run_task(self, task: str, params: dict, timeout: float = 4 * 3600) -> tuple[bool, list[tuple[str, dict]]]:
        """执行任意 MAA 任务（Roguelike / Fight / Infrast ...），即 MAA 的全部功能。"""
        return self._run(task, params, timeout)

    def run_copilot(self, plan_file: Path, formation: bool = True, kind: str = "Copilot") -> tuple[bool, str]:
        """执行一份作业。kind 可为 Copilot（普通/活动/危机合约）、SSSCopilot（保全派驻）、ParadoxCopilot（悖论模拟）。"""
        params = {"filename": str(Path(plan_file).resolve())}
        if kind == "Copilot":
            params.update({"formation": formation, "use_sanity_potion": False})
        ok, events = self._run(kind, params)
        errors = [d for n, d in events if n in ("TaskChainError", "SubTaskError")]
        return ok, json.dumps(errors[-3:], ensure_ascii=False)
