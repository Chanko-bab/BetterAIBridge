# -*- coding: utf-8 -*-
"""前置模组：命名、受控改文件、存档 Key 开关。"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("ok", msg)


def test_names():
    from app.core import pbab

    check(pbab.folder_name("pre_id", pre=True) == "pre-program_pre_id.pbab", "前置命名")
    check(pbab.folder_name("normal") == "program_normal.pbab", "普通命名")
    check(pbab.folder_is_pre("pre-program_x.pbab"), "识别前置文件夹")
    check(not pbab.folder_is_pre("program_x.pbab"), "普通文件夹不是前置")
    check(pbab.parse_folder_name("pre-program_x.pbab") == "x", "前置 id")

    tmp = Path(tempfile.mkdtemp(prefix="bab-pre-dir-"))
    try:
        good = tmp / "pre-program_x.pbab"
        good.mkdir()
        (good / "module.json").write_text(json.dumps({
            "format": "pbab/1", "api": 1, "id": "x", "name": "前置", "version": "1.0",
            "kind": "pre"}), encoding="utf-8")
        (good / "introduce.md").write_text("说明", encoding="utf-8")
        (good / "connection.json").write_text('{"provides": {}}', encoding="utf-8")
        pbab._validate_dir(good)
        check(True, "前置目录校验通过")

        bad = tmp / "program_x.pbab"
        bad.mkdir()
        (bad / "module.json").write_text(json.dumps({
            "format": "pbab/1", "api": 1, "id": "x", "name": "前置", "version": "1.0",
            "kind": "pre"}), encoding="utf-8")
        (bad / "introduce.md").write_text("说明", encoding="utf-8")
        (bad / "connection.json").write_text('{"provides": {}}', encoding="utf-8")
        try:
            pbab._validate_dir(bad)
        except pbab.PbabError:
            check(True, "kind=pre 但目录不是 pre- 前缀被拒绝")
        else:
            raise AssertionError("kind=pre 的普通目录应被拒绝")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pre_apply():
    from app.core import pre_bridge

    tmp = Path(tempfile.mkdtemp(prefix="bab-pre-"))
    try:
        root = tmp / "app"
        (root / "WiseEntity" / "entity" / "memory").mkdir(parents=True)
        (root / "WiseEntity" / "entity" / "state").mkdir(parents=True)
        (root / "app" / "ui").mkdir(parents=True)
        pre_bridge.config = SimpleNamespace(
            APP_DIR=root, entity_dir=lambda: root / "WiseEntity" / "entity")

        ops = [{"op": "write", "path": str(Path("app") / "ui" / "hello.py"),
                "content": "print('hi')\n"},
               {"op": "mkdir", "path": str(Path("app") / "ui" / "newdir")}]
        view = pre_bridge.preview(ops)
        check(view.get("ok"), "预览通过")
        res = pre_bridge.apply(ops, "pre_id", "测试")
        check(res.get("ok"), "落盘通过")
        check((root / "app" / "ui" / "hello.py").read_text() == "print('hi')\n", "写入内容")
        check((root / "app" / "ui" / "newdir").is_dir(), "创建目录")
        check(Path(res["backup"]).is_file(), "生成备份")

        # 按用户要求：记忆/配置/代码都不再是黑名单，前置模组可以改
        mem = pre_bridge.preview([{
            "op": "write", "path": str(Path("WiseEntity") / "entity" / "memory" / "x.json"),
            "content": "{}"}])
        check(mem.get("ok"), "记忆目录允许写")
        cfg = pre_bridge.preview([{
            "op": "write", "path": str(Path("WiseEntity") / "entity" / "config" / "llm.json"),
            "content": "{}"}])
        check(cfg.get("ok"), "config/llm.json 允许写")
        bad2 = pre_bridge.preview([{
            "op": "delete", "path": str(Path("app") / "ui" / "nope.py")}])
        check(not bad2.get("ok"), "删不存在的文件被拒绝")
        # 按用户要求：程序目录外也放开（绝对路径，Windows 用户有权限即可）
        out_path = tmp / "outside.py"
        out = pre_bridge.preview([{"op": "write", "path": str(out_path), "content": "x"}])
        check(out.get("ok"), "目录外路径允许")
        res2 = pre_bridge.apply([{"op": "write", "path": str(out_path), "content": "x"}],
                                "pre_id", "目录外测试")
        check(res2.get("ok") and out_path.read_text() == "x", "目录外落盘")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_start_order():
    from app.core import pbab

    rows = [
        {"id": "norm", "name": "普通", "kind": "bridge", "state": "enabled"},
        {"id": "pre", "name": "前置", "kind": pbab.KIND_PRE, "state": "enabled"},
    ]
    calls = []
    old_mods, old_enable = pbab.registry.modules, pbab.enable
    pbab.registry.modules = lambda: rows
    pbab.enable = lambda mid: calls.append(mid) or {"state": "enabled"}
    try:
        out = pbab.start_enabled()
    finally:
        pbab.registry.modules, pbab.enable = old_mods, old_enable
    check(calls == ["pre", "norm"], "启动时前置先于普通")
    check(len(out) == 2, "两个模组都处理")


def test_archive_key():
    from app.core import portable

    tmp = Path(tempfile.mkdtemp(prefix="bab-arc-"))
    try:
        entity = tmp / "entity"
        (entity / "config").mkdir(parents=True)
        (entity / "persona").mkdir()
        (entity / "persona" / "persona.md").write_text("她", encoding="utf-8")
        (entity / "config" / "llm.json").write_text(
            json.dumps({"api_key": "sk-secret", "model": "x"}, ensure_ascii=False),
            encoding="utf-8")
        no_key = tmp / "no-key.babpak"
        res = portable.write_archive(entity, "测试", target=no_key, include_key=False)
        check(res.get("ok") and not res.get("has_api_key"), "导出默认不带 Key")
        with zipfile.ZipFile(no_key) as zf:
            doc = json.loads(zf.read("entity/config/llm.json").decode("utf-8"))
            check(not doc.get("api_key"), "存档里的 llm.json 没有 Key")
        info = portable.read_archive(no_key)
        check(info.get("ok") and not info.get("has_api_key"), "读存档识别没 Key")

        with_key = tmp / "with-key.babpak"
        res2 = portable.write_archive(entity, "测试", target=with_key, include_key=True)
        check(res2.get("has_api_key"), "导出可选带 Key")
        info2 = portable.read_archive(with_key)
        check(info2.get("has_api_key"), "读存档识别有 Key")

        dest = tmp / "dest"
        dest.mkdir()
        restored = portable.restore_archive(no_key, dest, api_key="sk-new")
        check(restored.get("ok") and restored.get("has_api_key"), "导入补写 Key")
        doc = json.loads((dest / "config" / "llm.json").read_text(encoding="utf-8"))
        check(doc.get("api_key") == "sk-new", "补写的 Key 正确")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    test_names()
    test_pre_apply()
    test_start_order()
    test_archive_key()
    print("PASS 前置模组/存档 Key")


if __name__ == "__main__":
    main()
