"""把启动器恢复到「刚装好、还没建档」的状态。

和「卸载程序」的区别：卸载会删掉整个程序目录；这里只清数据，程序本身、
.venv、内核代码和安装信息都保留。清完会按 install.json 的端口重建 app.yaml。

不碰 logs/（留给诊断），不碰 entity/core、entity/brain 的代码与默认表。
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List

from ..core import config

log = logging.getLogger(__name__)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_EMPTY_REGISTRY = {"format": "bab-registry/1", "updated": "", "modules": {}}


def _count(path: Path) -> int:
    try:
        return sum(1 for p in path.rglob("*") if p.is_file() or p.is_symlink())
    except OSError:
        return 0


def _remove(path: Path, errors: List[str]) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    try:
        if path.is_dir() and not path.is_symlink():
            n = _count(path)
            shutil.rmtree(path)
            return n
        path.unlink()
        return 1
    except OSError as exc:
        errors.append(f"{path}: {exc}")
        return 0


def _clear(path: Path, errors: List[str], keep: Iterable[str] = ()) -> int:
    if not path.is_dir():
        return 0
    keep_set = set(keep)
    removed = 0
    for child in list(path.iterdir()):
        if child.name in keep_set:
            continue
        removed += _remove(child, errors)
    return removed


def _stop_core(app: Path) -> bool:
    script = Path(str(config.get("stop_all") or ""))
    if not script.is_file():
        script = app / "WiseEntity" / "source_code" / "scripts" / "stop-all.ps1"
    if not script.is_file():
        log.warning("找不到停止脚本，跳过停内核：%s", script)
        return False
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(app), timeout=30, creationflags=_NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("停止内核失败：%s", exc)
        return False


def _rebuild_app_yaml(app: Path, errors: List[str]) -> bool:
    """按安装时同样的模板和端口重建 app.yaml（launch.vbs 要求它存在）。"""
    cfg = app / "config"
    tpl = cfg / "app.yaml.template"
    if not tpl.is_file():
        errors.append(f"缺少模板：{tpl}")
        return False
    info = {}
    try:
        info = json.loads((cfg / "install.json").read_text(encoding="utf-8-sig"))
    except Exception:
        info = {}
    core = info.get("core") or info.get("base") or 40720
    asr = info.get("asr") or 40715
    try:
        text = tpl.read_text(encoding="utf-8-sig")
        text = (text.replace("{{APP_DIR}}", str(app).rstrip("\\"))
                .replace("{{CORE_PORT}}", str(core))
                .replace("{{ASR_PORT}}", str(asr)))
        (cfg / "app.yaml").write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"重建 app.yaml 失败：{exc}")
        return False
    return True


def reset_launcher_data(
    app_dir=None, entity=None, bundle=None, cache=None,
    *, stop: bool = True, reload: bool = True,
) -> dict:
    """清空用户数据与模组；返回 {"ok", "removed", "stopped", "errors"}。

    测试时传临时路径并 stop=False / reload=False，避免动到真安装。
    """
    root = Path(app_dir or config.APP_DIR)
    ent = Path(entity or config.entity_dir())
    bun = Path(bundle or config.bundle_dir())
    cac = Path(cache or config.get("modules_dir", config.DEFAULTS["modules_dir"]))
    errors: List[str] = []

    stopped = _stop_core(root) if stop else False
    removed = 0

    # 人格、记忆、自述、状态、注册表、情绪状态
    removed += _clear(ent / "persona", errors, keep=("persona.placeholder.md",))
    removed += _clear(ent / "memory", errors)
    removed += _clear(ent / "self", errors)
    removed += _clear(ent / "state", errors)
    removed += _clear(ent / "registry", errors)
    removed += _clear(ent / "emotion", errors, keep=("intensity_table.json",))
    removed += _clear(ent / "config", errors, keep=("llm.placeholder.json",))
    removed += _remove(ent / "brain" / "flybrain_state.json", errors)

    # 启动器配置：保留 install.json / 模板，端口和安装身份不变
    for name in ("app.yaml", "sense.json", "bridge_grants.json"):
        removed += _remove(root / "config" / name, errors)

    # 模组与缓存
    removed += _clear(bun, errors)
    try:
        bun.mkdir(parents=True, exist_ok=True)
        (bun / "registry.json").write_text(
            json.dumps(_EMPTY_REGISTRY, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"写空注册表失败：{exc}")
    removed += _clear(cac, errors)

    _rebuild_app_yaml(root, errors)

    if reload:
        try:
            config.load(force=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"重读配置失败：{exc}")

    return {"ok": not errors, "removed": removed, "stopped": stopped, "errors": errors}
