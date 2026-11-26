"""跟随 MAA 官方更新。

两部分：
1. 运行时：从 GitHub Releases 下载对应平台的官方发布包解压到 maa/（含内核和资源）。
2. 源码参考：对 MaaAssistantArknights 源码仓库执行 git pull（只读参考 + Python 绑定）。

我们的代码只依赖 MAA 的公开接口和资源格式，所以更新 MAA 一般不会破坏本项目。
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)
RELEASE_API = "https://api.github.com/repos/MaaAssistantArknights/MaaAssistantArknights/releases/latest"


def _asset_suffix() -> str:
    sysname, arch = platform.system().lower(), platform.machine().lower()
    arm = arch in ("arm64", "aarch64")
    if sysname == "windows":
        return "win-arm64.zip" if arm else "win-x64.zip"
    if sysname == "linux":
        return "linux-aarch64.tar.gz" if arm else "linux-x86_64.tar.gz"
    if sysname == "darwin":
        return "macos-runtime-universal.zip"
    raise RuntimeError(f"不支持的平台：{sysname} {arch}")


def installed_version(cfg: Config) -> str | None:
    f = cfg.maa_dir / ".maa_version"
    return f.read_text().strip() if f.exists() else None


def latest_release(cfg: Config) -> tuple[str, str]:
    req = urllib.request.Request(RELEASE_API, headers={"User-Agent": cfg.user_agent})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    suffix = _asset_suffix()
    for a in data["assets"]:
        if a["name"].startswith("MAA-") and a["name"].endswith(suffix):
            return data["tag_name"], a["browser_download_url"]
    raise RuntimeError(f"最新版本 {data['tag_name']} 没有 {suffix} 发布包")


def update_runtime(cfg: Config, force: bool = False) -> str:
    tag, url = latest_release(cfg)
    if not force and installed_version(cfg) == tag:
        log.info("MAA 已是最新版本 %s", tag)
        return tag
    log.info("下载 MAA %s：%s", tag, url)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / url.rsplit("/", 1)[-1]
        req = urllib.request.Request(url, headers={"User-Agent": cfg.user_agent})
        with urllib.request.urlopen(req, timeout=600) as r, open(archive, "wb") as f:
            shutil.copyfileobj(r, f)
        staging = Path(tmp) / "x"
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                z.extractall(staging)
        else:
            with tarfile.open(archive) as t:
                t.extractall(staging, filter="data")
        # 有的包多套一层目录
        entries = list(staging.iterdir())
        root = entries[0] if len(entries) == 1 and entries[0].is_dir() else staging
        if cfg.maa_dir.exists():
            shutil.rmtree(cfg.maa_dir)
        shutil.move(str(root), str(cfg.maa_dir))
    (cfg.maa_dir / ".maa_version").write_text(tag)
    return tag


def update_source(cfg: Config) -> str:
    repo = cfg.maa_source_dir
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "--depth", "1",
                        "https://github.com/MaaAssistantArknights/MaaAssistantArknights.git", str(repo)], check=True)
    else:
        subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], check=True)
    out = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%h %cd"], capture_output=True, text=True)
    return out.stdout.strip()
