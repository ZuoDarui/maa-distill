"""全局配置：所有路径和可调参数集中在这里。

用户配置文件为项目根目录下的 `config.json`（可选），字段会覆盖下面的默认值。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    # MAA 官方发布包解压目录（含 libMaaCore / MaaCore.dll 和 resource/）
    maa_dir: Path = PROJECT_ROOT / "maa"
    # MAA 源码仓库（只用里面的 src/Python/asst 绑定和 resource/battle_data.json）
    maa_source_dir: Path = PROJECT_ROOT.parent / "MaaAssistantArknights"
    # 本地数据库：爬下来的作业、你的 box、你的运行记录
    db_path: Path = PROJECT_ROOT / "data" / "copilot.db"
    # 生成的作业 JSON 输出目录
    output_dir: Path = PROJECT_ROOT / "data" / "plans"

    # 作业站 API
    api_base: str = "https://prts.maa.plus"
    # 两次请求之间的最小间隔（秒）。作业站是社区公益服务，请不要调小
    request_interval: float = 1.0
    user_agent: str = "maa-distill/0.1"

    # 模拟器连接
    adb_path: str = "adb"
    adb_address: str = "127.0.0.1:5555"
    touch_type: str = "maatouch"

    # 排序时站内评分和你自己的运行记录的先验强度
    prior_strength: float = 4.0

    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or PROJECT_ROOT / "config.json"
        cfg = cls()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for k, v in data.items():
                if not hasattr(cfg, k):
                    cfg.extra[k] = v
                    continue
                cur = getattr(cfg, k)
                if isinstance(cur, Path):
                    v = Path(v)
                    v = v if v.is_absolute() else (PROJECT_ROOT / v).resolve()
                setattr(cfg, k, v)
        return cfg

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in d.items()}, ensure_ascii=False, indent=2)
