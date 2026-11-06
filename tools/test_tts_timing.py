"""语速 → 时长：关掉朗读时她每句占多久，全靠这几个数。

钉住的是公式本身（纯函数，不开窗、不联网）：
    秒数 = 字数 / (5.0 * (1 + 语速%/100))
    关朗读时的窗口 = 秒数 * 0.6，夹在 0.8–8.0 秒之间

    .venv\\Scripts\\python.exe tools\\test_tts_timing.py
退出码 0 = 全过；1 = 有断言失败。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import speech_time as st  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def near(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(a - b) <= tol


SENT = "明天昆明晴，十四到二十五度，风不大。"  # 19 字（标点算字）


def main() -> int:
    # --- 语速解析
    check(st.rate_pct("+20%") == 20.0, f"'+20%' 认成 20（实际 {st.rate_pct('+20%')}）")
    check(st.rate_pct("-30%") == -30.0, f"'-30%' 认成 -30（实际 {st.rate_pct('-30%')}）")
    check(st.rate_pct("+0%") == 0.0, "'+0%' 是 0")
    check(st.rate_pct("") == 0.0, "空串当 0（拿不到配置也不至于算错）")
    check(st.rate_pct("随便写的") == 0.0, "认不出就当 0，不抛")

    # --- 字数
    check(st.char_count("你好 呀\n") == 3, f"空白不算字（实际 {st.char_count('你好 呀')}）")
    check(st.char_count("") == 0, "空串 0 字")

    # --- 说话时长：语速直接改这个数
    n = st.char_count(SENT)
    base = st.speech_seconds(SENT, "+0%")
    fast = st.speech_seconds(SENT, "+50%")
    slow = st.speech_seconds(SENT, "-30%")
    check(near(base, n / 5.0), f"{n} 字 +0% ≈ {n / 5.0:.2f} 秒（实际 {base:.2f}）")
    check(near(fast, base / 1.5), f"+50% 快 1/3 ≈ {base / 1.5:.2f} 秒（实际 {fast:.2f}）")
    check(near(slow, base / 0.7), f"-30% 慢到 ≈ {base / 0.7:.2f} 秒（实际 {slow:.2f}）")
    check(fast < base < slow, "越快越短、越慢越长")

    # --- 关朗读时的窗口：读比听快，乘 0.6，但有上下限
    win = st.text_window_seconds(SENT, "+0%")
    check(near(win, base * 0.6), f"关朗读时窗口 = 说话时长 × 0.6（实际 {win:.2f}）")
    check(near(st.text_window_seconds("嗯。", "+0%"), 0.8), "再短的句子也留 0.8 秒")
    check(near(st.text_window_seconds(SENT, "+100%"), max(0.8, base / 2 * 0.6), 0.1),
          f"+100% 时窗口更短（实际 {st.text_window_seconds(SENT, '+100%'):.2f}）")
    check(near(st.text_window_seconds("很长" * 200, "-50%"), 8.0), "超长句封顶 8 秒，不至于干等")

    # --- 极端值保护
    check(st.speech_seconds("嗯", "-100%") >= 0.4, "语速被拉到 -100% 也不炸（下限 0.4 秒）")
    check(st.text_window_seconds("嗯", "-100%") >= 0.8, "窗口下限 0.8 秒")

    print(f"\n{len(fails)} 条失败" if fails else "\nPASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
