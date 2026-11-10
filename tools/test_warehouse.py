"""仓库：库、收藏、去重、来源隔离、inspect/keep、聊天里的中性提示。"""
from __future__ import annotations

import asyncio
import base64
import sys
import tempfile
import time
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
    warehouse.ENTITY = tmp / "WiseEntity" / "entity"
    try:
        img = warehouse.put_bytes("owner", "猫.png", PNG)
        check(img["kind"] == "image", "png 归到图片")
        check(img["library"] == warehouse.OWNER_LIB, "主人文件进 owner-main 库")
        check(img["bytes"] == len(PNG), "图片字节数正确")
        again = warehouse.put_bytes("owner", "换名.png", PNG)
        check(again.get("existing") and again["id"] == img["id"], "同库同 sha 去重")

        txt = tmp / "note.txt"
        txt.write_text("第一行\n第二行", encoding="utf-8")
        row = warehouse.import_file(txt, name="笔记.txt")
        check(row["kind"] == "document", "txt 归到文档")
        listed = warehouse.list_items(source="owner")
        check(len(listed) == 2, "主人仓库列出两条")
        got = warehouse.read_text(row["id"])
        check("第一行" in got["text"] and got["truncated"] is False, "文本能读出来")

        mod = warehouse.put_bytes("module:probe", "probe.txt", b"hi")
        check(mod["library"] == "mod-probe-main", "模组文件进自己的默认库")
        check(len(warehouse.list_items(source="module:probe")) == 1, "模组只看到自己那条")
        check(warehouse.resolve("probe.txt", source="module:probe") is not None, "模组按名字找得到")
        check(warehouse.resolve("probe.txt", source="owner") is None, "主人这边看不到模组的")

        libs = {x["id"]: x for x in warehouse.libraries()}
        check(warehouse.OWNER_LIB in libs and warehouse.AGENT_LIB in libs, "两个默认库都在")
        check("mod-probe-main" in libs, "模组默认库自动登记")

        kept = warehouse.keep(img["id"], title="白猫", desc="一只白猫", why="看着舒服",
                              tags=["猫", "表情包"])
        check(kept["library"] == warehouse.AGENT_LIB, "收藏复制进 agent-collection")
        check(warehouse.get(img["id"]) is not None, "收藏不删原条")
        check(warehouse.collection()[0]["id"] == kept["id"], "收藏列表能找到")
        frag = warehouse.fragment("猫")
        check("我收着的东西" in frag and "白猫" in frag and "表情包" in frag, "提示块带标题/标签")

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
        for n in ("warehouse_list", "warehouse_search", "warehouse_inspect",
                  "warehouse_keep", "warehouse_read", "warehouse_forget",
                  "see_image", "send_media"):
            check(n in names, f"内置工具 {n} 在")
        for c in ("warehouse.put", "warehouse.list", "warehouse.read",
                  "warehouse.mkdir", "warehouse.libraries"):
            check(c in CAPS, f"桥能力 {c} 在")

        # inspect 之前不能发
        sent = asyncio.run(tool_bus._call_impl("send_media", {"id": img["id"]}))
        check(sent.get("ok") is False and "inspect" in sent.get("error", ""),
              "没 inspect 不能发")
        warehouse.update_meta(img["id"], desc="一只白猫", inspected_at=time.time())
        sent = asyncio.run(tool_bus._call_impl("send_media", {"id": img["id"], "caption": "给你"}))
        check(sent.get("ok") is True and tool_bus.take_media("web:owner"), "inspect 后能发")
        found = asyncio.run(tool_bus._call_impl("warehouse_search", {"query": "白猫"}))
        check(found.get("ok") is True and found["result"]["count"] >= 1, "search 按描述找得到")

        # 模组多库：手工登记一个，再让 bridge 访问
        warehouse.ensure_library("mod-whmod-images", "module", "whmod",
                                 title="图片", purpose="模组自己放的图", quota_mb=64)
        from WiseEntity.entity.core import bridge
        put = bridge._wh_put("whmod", name="给主人.txt",
                             base64=base64.b64encode("你好".encode("utf-8")).decode(),
                             library="main")
        check(put["library"] == "mod-whmod-main", "模组桥默认库")
        seen = bridge._wh_list("whmod")
        check(seen["count"] == 1 and seen["items"][0]["name"] == "给主人.txt",
              "模组桥只看得到自己的")
        read = bridge._wh_read("whmod", id="给主人.txt")
        check("你好" in read["text"], "模组桥能读自己的文本")
        libs = bridge._wh_libraries("whmod")
        check(libs["count"] >= 2 and any(x["id"] == "mod-whmod-images" for x in libs["libraries"]),
              "桥能列自己的多个库")
        try:
            bridge._wh_put("whmod", name="x.txt", base64="aGk=", library="not-mine")
            check(False, "没申请的库应被拒绝")
        except Exception:
            check(True, "没申请的库被拒绝")

        # 全新根：模组在 module.json 里声明库，但 warehouse/ 还不存在
        fresh = Path(tempfile.mkdtemp(prefix="bab_wh_fresh_"))
        old_entity = warehouse.ENTITY
        try:
            warehouse.ENTITY = fresh / "WiseEntity" / "entity"
            bundle = fresh / "program_bundle" / "program_qq_bridge.pbab"
            bundle.mkdir(parents=True)
            (bundle / "module.json").write_text(
                '{"id":"qq_bridge","warehouse":{"libraries":'
                '[{"id":"media","title":"QQ 收到的图片和文件","quota_mb":512}]}}',
                encoding="utf-8")
            fresh_libs = {x["id"]: x for x in warehouse.module_libraries("qq_bridge")}
            check("mod-qq_bridge-media" in fresh_libs, "全新根能建模组声明的库")
            check((fresh / "WiseEntity" / "entity" / "warehouse" / "libraries.json").is_file(),
                  "全新根会写 libraries.json")
        finally:
            warehouse.ENTITY = old_entity
            shutil.rmtree(fresh, ignore_errors=True)

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
