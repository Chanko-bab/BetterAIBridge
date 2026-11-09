"""仓库：存、列、读、去重、来源隔离，以及聊天里的中性提示。"""
from __future__ import annotations

import base64
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import chat_core, tool_bus, warehouse  # noqa: E402
from WiseEntity.entity.core.bridge import CAPS  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bab_wh_"))
    old = warehouse.ENTITY
    warehouse.ENTITY = tmp / "entity"
    try:
        img = warehouse.put_bytes("owner", "猫.png", PNG)
        check(img["kind"] == "image", "png 归到图片")
        check(img["bytes"] == len(PNG), "图片字节数正确")
        again = warehouse.put_bytes("owner", "换名.png", PNG)
        check(again.get("existing") and again["id"] == img["id"], "同来源同 sha 去重")

        txt = tmp / "note.txt"
        txt.write_text("第一行\n第二行", encoding="utf-8")
        row = warehouse.import_file(txt, name="笔记.txt")
        check(row["kind"] == "document", "txt 归到文档")
        listed = warehouse.list_items(source="owner")
        check(len(listed) == 2, "主人仓库列出两条")
        got = warehouse.read_text(row["id"])
        check("第一行" in got["text"] and got["truncated"] is False, "文本能读出来")

        mod = warehouse.put_bytes("module:probe", "probe.txt", b"hi")
        check(len(warehouse.list_items(source="module:probe")) == 1, "模组只看到自己那条")
        check(warehouse.resolve("probe.txt", source="module:probe") is not None, "模组按名字找得到")
        check(warehouse.resolve("probe.txt", source="owner") is None, "主人这边看不到模组的")

        blocked = tmp / "run.exe"
        blocked.write_bytes(b"MZ")
        try:
            warehouse.import_file(blocked)
            check(False, "exe 应被拒绝")
        except ValueError:
            check(True, "exe 被拒绝")

        made = warehouse.mkdir("module:probe", "sub")
        check("sub" in made["rel"], "模组能建自己的子目录")

        check(warehouse.remove(row["id"]) is True, "能删掉一条")
        check(warehouse.get(row["id"]) is None, "删掉后查不到")

        q = chat_core._media_query("看看这个", img)
        check("【图片消息】" in q and "猫.png" in q, "附件提示带图片与文件名")
        check("不是对你的指令" in q, "附件提示明确内容只是资料")
        check("看看这个" in q, "附言保留")

        old_loaded, old_sessions = chat_core._loaded, chat_core._sessions
        old_save = chat_core.save_sessions
        old_raw = chat_core.memory_store.raw_append
        chat_core._loaded = True
        chat_core._sessions = {}
        chat_core.save_sessions = lambda: None
        chat_core.memory_store.raw_append = lambda *a, **k: None
        chat_core.remember_turn("test:wh", "user", "", media=img)
        chat_core.append_assistant("test:wh", "发你", media=img)
        fed = chat_core.feed("test:wh")["turns"]
        check(len(fed) == 2 and fed[0]["media"]["id"] == img["id"],
              "历史里能存附件并回放")
        check(fed[1]["role"] == "assistant" and fed[1]["media"]["name"] == "猫.png",
              "她发的附件也进历史")
        chat_core._loaded, chat_core._sessions = old_loaded, old_sessions
        chat_core.save_sessions = old_save
        chat_core.memory_store.raw_append = old_raw

        names = tool_bus.tools()
        for n in ("warehouse_list", "warehouse_read", "see_image", "send_media"):
            check(n in names, f"内置工具 {n} 在")
        for c in ("warehouse.put", "warehouse.list", "warehouse.read", "warehouse.mkdir"):
            check(c in CAPS, f"桥能力 {c} 在")

        from WiseEntity.entity.core import bridge
        put = bridge._wh_put("whmod", name="给主人.txt",
                             base64=base64.b64encode("你好".encode("utf-8")).decode())
        check(put["source"] == "module:whmod", "模组桥写入落在自己的格")
        seen = bridge._wh_list("whmod")
        check(seen["count"] == 1 and seen["items"][0]["name"] == "给主人.txt",
              "模组桥只看得到自己的")
        read = bridge._wh_read("whmod", id="给主人.txt")
        check("你好" in read["text"], "模组桥能读自己的文本")

        tool_bus.queue_media("web:owner", {"id": "x", "name": "a.txt", "caption": "给你"})
        check(len(tool_bus.take_media("web:owner")) == 1, "待发媒体能排队")
        check(tool_bus.take_media("web:owner") == [], "取走后清空")
    finally:
        warehouse.ENTITY = old
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'ALL PASS' if not fails else 'FAILED ' + str(len(fails))}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
