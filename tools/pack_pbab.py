"""把「文件夹形态」的模组打成单个 `.pbab` 文件（zip），用来分发/备份。

用法：
    python tools/pack_pbab.py tools/modsrc/qq_bridge            # 输出 program_qq_bridge.pbab
    python tools/pack_pbab.py <模组文件夹> <输出.pbab>

打包规则：
  - 文件夹名建议 program_<id>.pbab；若叫别的，仍以 module.json 的 id 为准；
  - 必需 module.json / introduce.md / connection.json；
  - 自动生成 checksums.json（除它自己之外所有文件的 sha256）；
  - zip 内**不带**外层目录，导入时直接展开成 program_<id>.pbab\\。
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_SKIP_DIRS = {"__pycache__", "logs", ".git", ".idea", ".vscode", "data"}


def _packable(src: Path, p: Path, checksums: str) -> bool:
    """别把运行时垃圾打进包里：字节码、日志、编辑器目录，以及运行期数据（data/）。"""
    if not p.is_file() or p.name in (checksums, ".DS_Store", "Thumbs.db"):
        return False
    if p.suffix.lower() in (".pyc", ".pyo"):
        return False
    rel = p.relative_to(src)
    return not any(part in _SKIP_DIRS for part in rel.parts[:-1])


def pack(src: str | Path, out: str | Path | None = None) -> Path:
    from app.core import pbab  # 复用同一套校验，避免两份规则漂移

    src = Path(src)
    if not src.is_dir():
        raise SystemExit(f"不是文件夹：{src}")
    meta = pbab.validate(src)
    mid = str(meta["manifest"]["id"])
    man = meta["manifest"]
    if not str(man.get("author") or man.get("developer") or "").strip():
        print("hint: module.json 没写 author，模组卡片会显示「未标注」")

    out_path = Path(out) if out else src.parent / f"program_{mid}.pbab"
    files = [p for p in sorted(src.rglob("*")) if _packable(src, p, pbab.CHECKSUMS)]
    sums = {str(p.relative_to(src)).replace("\\", "/"): _sha256(p) for p in files}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, str(p.relative_to(src)).replace("\\", "/"))
        zf.writestr(pbab.CHECKSUMS, json.dumps(sums, ensure_ascii=False, indent=2))
    print(f"packed {mid} -> {out_path}  ({out_path.stat().st_size} bytes, {len(files)} files)")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    pack(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
