"""BreezeBlue 的 HTTP 形状：请求打到哪、带什么头、发什么体。

为什么单开一套：0.3.24 把它当「OpenAI 兼容」——`POST /audio/speech` + `Bearer`。
它家真实接口是 `POST /v1/text-to-speech/{voice_id}` + `xi-api-key` + `{text, model_id}`。
发错时服务端不是报错，而是**不回话**（一直等到超时），界面上就是「试听没声音」。
所以路径、头、请求体这三处必须钉死，不能靠联调发现。

不联网：httpx.AsyncClient 整个换成假的。
    WiseEntity\\entity\\.venv\\Scripts\\python.exe tools\\test_tts_http.py
退出码 0 = 全过；1 = 有断言失败。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WiseEntity.entity.core import tts  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


class FakeResp:
    def __init__(self, status: int = 200, content: bytes = b"", doc: dict | None = None):
        self.status_code = status
        self.content = content
        self._doc = doc
        self.text = "" if doc is None else str(doc)

    def json(self):
        if self._doc is None:
            raise ValueError("not json")
        return self._doc


class FakeClient:
    """记住这次请求长什么样，然后回一段假音频。"""

    last: dict = {}
    resp = FakeResp(content=b"\xff\xf3" + b"0" * 4000)
    raise_exc: BaseException | None = None

    def __init__(self, **kw):
        self.kw = kw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, params=None, json=None, headers=None, **kw):
        FakeClient.last = {"url": url, "params": params, "json": json, "headers": headers,
                           "timeout": self.kw.get("timeout")}
        if FakeClient.raise_exc is not None:
            raise FakeClient.raise_exc
        return FakeClient.resp


def cfg(**over) -> dict:
    c = {"bb_base": "https://api.breezeblue.ai/v1", "bb_key": "brz_test",
         "bb_voice": "voc_test", "bb_model": "breeze-tts-2"}
    c.update(over)
    return c


def synth(tmp: Path, c: dict, text: str = "你好") -> Path:
    return asyncio.run(tts._synth_http(text, tmp / "say.mp3", c))


def main() -> int:
    import httpx  # noqa: PLC0415

    orig = httpx.AsyncClient
    httpx.AsyncClient = FakeClient
    tmp = Path(tempfile.mkdtemp(prefix="bab_ttshttp_"))
    try:
        # --- 1. 地址归一
        check(tts.api_base("https://api.breezeblue.ai/v1") == "https://api.breezeblue.ai/v1",
              "带 /v1 的地址原样用")
        check(tts.api_base("https://api.breezeblue.ai/") == "https://api.breezeblue.ai/v1",
              "不带 /v1 的地址补上")
        check(tts.api_base("  ") == "", "空地址还是空")

        # --- 2. 请求形状
        p = synth(tmp, cfg())
        last = FakeClient.last
        check(last["url"] == "https://api.breezeblue.ai/v1/text-to-speech/voc_test",
              f"打到 /v1/text-to-speech/{{voice_id}}（实际 {last['url']}）")
        check((last["params"] or {}).get("output_format") == "mp3",
              f"要 mp3（实际 {last['params']}）")
        check((last["headers"] or {}).get("xi-api-key") == "brz_test",
              f"用 xi-api-key 头（实际 {last['headers']}）")
        check("Authorization" not in (last["headers"] or {}), "不要再用 Bearer")
        check((last["json"] or {}).get("text") == "你好", "请求体是 text")
        check((last["json"] or {}).get("model_id") == "breeze-tts-2", "请求体是 model_id")
        check("input" not in (last["json"] or {}) and "voice" not in (last["json"] or {}),
              "别再发 OpenAI 的 input/voice")
        check(p.exists() and p.stat().st_size > 800, f"音频落盘了（{p}）")

        # 地址没写 /v1 也能用
        synth(tmp, cfg(bb_base="https://api.breeze.blue"))
        check(FakeClient.last["url"] == "https://api.breeze.blue/v1/text-to-speech/voc_test",
              f"没写 /v1 也拼对（实际 {FakeClient.last['url']}）")

        # --- 3. 出错时要说人话
        FakeClient.resp = FakeResp(status=401, doc={"detail": "invalid api key", "code": "unauthorized"})
        try:
            synth(tmp, cfg())
            check(False, "401 应该抛错")
        except RuntimeError as e:
            check("401" in str(e) and "invalid api key" in str(e),
                  f"401 带上服务端说明（实际 {e}）")
        FakeClient.resp = FakeResp(status=200, content=b"\xff" * 10)
        try:
            synth(tmp, cfg())
            check(False, "回得太小应该抛错")
        except RuntimeError as e:
            check("没返回音频" in str(e), f"太小的响应报「没返回音频」（实际 {e}）")

        # --- 4. 超时的空异常不能变成「合成失败：」
        FakeClient.raise_exc = httpx.ReadTimeout("")
        try:
            synth(tmp, cfg())
            check(False, "超时应该抛错")
        except RuntimeError as e:
            msg = str(e)
            check("没回应" in msg and "ReadTimeout" in msg,
                  f"超时也说得清（实际 {msg!r}）")
        finally:
            FakeClient.raise_exc = None

        # --- 5. 缺参数时说清楚缺哪个
        for field, word in (("bb_key", "API Key"), ("bb_voice", "音色")):
            try:
                synth(tmp, cfg(**{field: ""}))
                check(False, f"缺 {field} 应该抛错")
            except RuntimeError as e:
                check(word in str(e), f"缺 {field} 时点名（实际 {e}）")

        # --- 6. 朗读 / 试听各选各的引擎（0.3.26：BreezeBlue 只留给试听）
        import json  # noqa: PLC0415

        keep_path = tts.VOICE_PATH
        cfg_file = tmp / "tts.json"
        tts.VOICE_PATH = cfg_file
        try:
            # 老配置：只有一个 engine=breezeblue
            cfg_file.write_text(json.dumps({"engine": "breezeblue"}), encoding="utf-8")
            c0 = tts.cfg()
            check(tts.engine("chat") == "edge",
                  f"老配置里朗读回落 edge（实际 {tts.engine('chat')}）")
            check(tts.engine("preview") == "breezeblue",
                  f"老配置里原来的选择挪给试听（实际 {tts.engine('preview')}）")
            check(c0.get("preview_engine") == "breezeblue", "cfg() 里能读到迁移后的试听引擎")

            # 新配置：两路各选各的
            cfg_file.write_text(json.dumps({"engine": "edge", "preview_engine": "breezeblue"}),
                                encoding="utf-8")
            check(tts.engine("chat") == "edge" and tts.engine("preview") == "breezeblue",
                  "朗读/试听互不影响")
            check(tts.engine("chat") != tts.engine("preview"), "两路确实是两个引擎")
            # 两个引擎的缓存不能混（同一个文本、不同引擎要各存一份）
            check(tts.cache_path("同一句", "v", "+0%", "chat")
                  != tts.cache_path("同一句", "v", "+0%", "preview"),
                  "两路引擎的缓存键要分开")
        finally:
            tts.VOICE_PATH = keep_path
    finally:
        httpx.AsyncClient = orig

    print("")
    if fails:
        print(f"失败 {len(fails)} 条：")
        for f in fails:
            print("  - " + f)
        return 1
    print("全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
