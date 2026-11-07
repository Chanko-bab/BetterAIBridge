"""独立更新助手。

启动器退出后，这个脚本负责：等父进程结束、停内核、备份、解压、覆盖、重新拉起。
它只依赖标准库，由安装目录里的 pythonw.exe 启动，不经过 PowerShell 执行策略。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

ALLOWED = (
    "main.py",
    "launch.vbs",
    "BetterAIBridge.vbs",
    "start.cmd",
    "VERSION.txt",
    "app/",
    "assets/",
    "WiseEntity/entity/core/",
    "WiseEntity/entity/brain/",
    "WiseEntity/source_code/scripts/",
)
BACKUP = (
    "main.py",
    "launch.vbs",
    "BetterAIBridge.vbs",
    "start.cmd",
    "VERSION.txt",
    "app",
    "assets",
    "WiseEntity/entity/core",
    "WiseEntity/entity/brain",
    "WiseEntity/source_code/scripts",
)
WINDOWS_NO_WINDOW = 0x08000000


def _log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "BetterAIBridge" / "logs" / "update.log"


def _state_path() -> Path:
    return _log_path().with_name("update_state.json")


def _write_state(state: str, **extra) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"state": state, "pid": os.getpid(), "at": datetime.now().isoformat(timespec="seconds")}
        payload.update(extra)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _log(message: str) -> None:
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass


def _wait_parent(pid: int, timeout: float = 60.0) -> None:
    if pid <= 0 or os.name != "nt":
        time.sleep(1.0)
        return
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))
    if not handle:
        time.sleep(1.0)
        return
    try:
        ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    time.sleep(0.8)


def _stop_kernel(install_dir: Path) -> None:
    stop = install_dir / "WiseEntity" / "source_code" / "scripts" / "stop-all.ps1"
    if not stop.exists():
        return
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(stop)],
            cwd=str(install_dir),
            timeout=30,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )
        _log("stop-all finished")
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"stop-all failed: {exc}")


def _safe_member(name: str) -> bool:
    norm = name.replace("\\", "/")
    path = PurePosixPath(norm)
    if path.is_absolute() or ".." in path.parts:
        return False
    return any(norm == item or norm.startswith(item) for item in ALLOWED)


def _extract(zip_path: Path, staging: Path, install_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not _safe_member(name):
                _log(f"skip unexpected {name}")
                continue
            target = staging / PurePosixPath(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    if not (staging / "VERSION.txt").exists():
        raise RuntimeError("更新包缺少 VERSION.txt")
    for src in staging.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(staging)
        dst = install_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _backup(install_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for rel in BACKUP:
        src = install_dir / rel
        if not src.exists():
            continue
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def _restore(install_dir: Path, backup_dir: Path) -> None:
    if not backup_dir.exists():
        return
    for rel in BACKUP:
        src = backup_dir / rel
        if not src.exists():
            continue
        dst = install_dir / rel
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def _launcher(install_dir: Path) -> Path | None:
    candidates = [install_dir / "BetterAIBridge.vbs", install_dir / "launch.vbs"]
    candidates += sorted(install_dir.glob("BetterAIBridgeLauncher *.vbs"))
    for path in candidates:
        if path.exists():
            return path
    return None


def _launch(install_dir: Path) -> None:
    launcher = _launcher(install_dir)
    if not launcher:
        raise RuntimeError("更新完成，但找不到 launch.vbs / BetterAIBridgeLauncher*.vbs")
    wscript = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x01000000
    try:
        subprocess.Popen(
            [str(wscript), str(launcher)],
            cwd=str(install_dir),
            close_fds=True,
            creationflags=flags,
        )
    except OSError:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [str(wscript), str(launcher)],
            cwd=str(install_dir),
            close_fds=True,
            creationflags=flags,
        )
    _log(f"launched {launcher.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)

    install_dir = Path(args.dir)
    zip_path = Path(args.zip)
    version = args.version
    _write_state("ready", version=version)
    _log(f"helper start pid={os.getpid()} parent={args.parent_pid} version={version}")
    backup_dir = install_dir / "backups" / f"update-{version}-{datetime.now():%Y%m%d-%H%M%S}"
    staging = Path(tempfile.mkdtemp(prefix="bab-update-stage-"))
    try:
        _wait_parent(args.parent_pid)
        _stop_kernel(install_dir)
        _log(f"extract {zip_path} -> {install_dir}")
        _backup(install_dir, backup_dir)
        _extract(zip_path, staging, install_dir)
        _log(f"update ok, backup={backup_dir}")
        _launch(install_dir)
        _write_state("done", version=version, backup=str(backup_dir))
        return 0
    except Exception as exc:  # 更新助手不能静默失败
        _log(f"FAILED: {exc!r}")
        try:
            _restore(install_dir, backup_dir)
            _log("rollback done")
        except OSError as rollback_exc:
            _log(f"rollback failed: {rollback_exc!r}")
        _write_state("failed", version=version, error=str(exc))
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
