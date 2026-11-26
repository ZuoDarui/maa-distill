"""跟随 MAA 官方更新。

两部分：
1. 运行时：经 MAA 官方版本接口（api.maa.plus，国内可访问）获取最新版本，下载对应平台的官方发布包
   解压到 maa/。下载顺序：官方镜像 → GitHub → config.json 里的 github_proxy 加速前缀。
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
# MAA 官方版本接口（国内可访问；返回内容与 GitHub Release 相同，并带 mirrors 字段）
MAA_VERSION_APIS = (
    "https://api.maa.plus/MaaAssistantArknights/api/version/stable.json",
    "https://api2.maa.plus/MaaAssistantArknights/api/version/stable.json",
)


def _get_json(url: str, cfg: Config, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": cfg.user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _release_info(cfg: Config) -> dict:
    """先问 MAA 官方接口，再退回 GitHub API。"""
    errors = []
    for url in MAA_VERSION_APIS:
        try:
            return _get_json(url, cfg)["details"]
        except Exception as e:  # noqa: BLE001 网络错误种类很多，逐个回退即可
            errors.append(f"{url}: {e}")
    try:
        return _get_json(RELEASE_API, cfg)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{RELEASE_API}: {e}")
    raise RuntimeError("获取 MAA 版本信息失败：\n  " + "\n  ".join(errors))


def _with_proxy(cfg: Config, url: str) -> str | None:
    """config.json 中可设置 "github_proxy": "https://<加速站>/"，用于国内加速 GitHub 下载。"""
    proxy = cfg.extra.get("github_proxy")
    if proxy and url.startswith(("https://github.com/", "https://raw.githubusercontent.com/")):
        return proxy.rstrip("/") + "/" + url
    return None


def _download(cfg: Config, urls: list[str], dest: Path) -> str:
    """依次尝试多个地址下载，打印进度；返回成功的地址。"""
    import sys
    import time

    errors = []
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": cfg.user_agent})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done, t0, last = 0, time.monotonic(), 0.0
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last > 1 or (total and done == total):
                        last = now
                        speed = done / max(now - t0, 1e-6) / 1024
                        pct = f"{done * 100 / total:5.1f}%" if total else "   ?  "
                        sys.stderr.write(f"\r  {pct}  {done / 1e6:7.1f}/{total / 1e6:.1f} MB  {speed:7.0f} KB/s")
                        sys.stderr.flush()
                sys.stderr.write("\n")
            if total and done != total:
                raise RuntimeError(f"下载不完整 {done}/{total}")
            return url
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url}: {e}")
            log.warning("下载失败，换下一个地址：%s（%s）", url, e)
    raise RuntimeError("所有下载地址都失败：\n  " + "\n  ".join(errors)
                       + "\n可在 config.json 中设置 github_proxy（GitHub 加速前缀）后重试")


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


def latest_release(cfg: Config) -> tuple[str, list[str]]:
    """返回 (版本号, 按优先级排列的下载地址)：官方镜像 → GitHub → GitHub 加速。"""
    data = _release_info(cfg)
    suffix = _asset_suffix()
    for a in data["assets"]:
        if a["name"].startswith("MAA-") and a["name"].endswith(suffix):
            gh = a["browser_download_url"]
            urls = [m for m in (a.get("mirrors") or []) if isinstance(m, str)] + [gh]
            if p := _with_proxy(cfg, gh):
                urls.append(p)
            return data["tag_name"], urls
    raise RuntimeError(f"最新版本 {data['tag_name']} 没有 {suffix} 发布包")


def update_runtime(cfg: Config, force: bool = False) -> str:
    tag, urls = latest_release(cfg)
    if not force and installed_version(cfg) == tag:
        log.info("MAA 已是最新版本 %s", tag)
        return tag
    log.info("下载 MAA %s", tag)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / urls[-1].rsplit("/", 1)[-1]
        used = _download(cfg, urls, archive)
        log.info("下载完成（%s），解压中…", used)
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
    _ensure_python_binding(cfg, tag)
    _ensure_linux_libatomic(cfg)
    return tag


BINDING_FILES = ("__init__.py", "asst.py", "utils.py", "updater.py", "emulator.py", "downloader.py")


def _ensure_python_binding(cfg: Config, tag: str) -> None:
    """macOS 发布包不带 Python 绑定；按同一版本号从 GitHub 只下载 src/Python/asst 下几个文件，
    避免为此克隆 600MB 的源码仓库。绑定与内核版本严格一致。"""
    dst = cfg.maa_dir / "Python" / "asst"
    if (dst / "asst.py").exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    base = f"https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/{tag}/src/Python/asst/"
    for name in BINDING_FILES:
        url = base + name
        _download(cfg, [url] + ([p] if (p := _with_proxy(cfg, url)) else []), dst / name)
    log.info("已下载 MAA Python 绑定 %s 到 %s", tag, dst)


def _ensure_linux_libatomic(cfg: Config) -> None:
    """MaaCore(Linux) 依赖 libatomic.so.1，部分精简系统没有；无 root 时从 apt 下载 deb 解出放进 maa/。"""
    import ctypes.util

    if platform.system() != "Linux" or ctypes.util.find_library("atomic"):
        return
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(["apt-get", "download", "libatomic1"], cwd=tmp, check=True, capture_output=True)
            deb = next(Path(tmp).glob("libatomic1_*.deb"))
            subprocess.run(["dpkg-deb", "-x", str(deb), "x"], cwd=tmp, check=True)
            for f in Path(tmp, "x").rglob("libatomic.so.1*"):
                shutil.copy2(f, cfg.maa_dir / f.name, follow_symlinks=True)
            log.info("已补充 libatomic.so.1 到 %s", cfg.maa_dir)
        except (OSError, subprocess.CalledProcessError, StopIteration) as e:
            log.warning("缺少 libatomic.so.1，请手动安装（sudo apt install libatomic1）：%s", e)


def update_source(cfg: Config) -> str:
    repo = cfg.maa_source_dir
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "--depth", "1",
                        "https://github.com/MaaAssistantArknights/MaaAssistantArknights.git", str(repo)], check=True)
    else:
        subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], check=True)
    out = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%h %cd"], capture_output=True, text=True)
    return out.stdout.strip()
