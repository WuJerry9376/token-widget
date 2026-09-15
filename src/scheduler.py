"""M2 轮询调度器（PLAN §4/§1）：后台线程采集 → queue → 主线程消费。

规则：
- 周期 = config.poll_seconds（config.py 已钳 ≥60s）
- 单供应商连续失败 → 指数退避 poll×2^n，封顶 30min；恢复即复位
  （not_configured 视为"占位未启用"，不参与退避，避免拖累整轮）
- 任一供应商剩余 <low_yellow_pct → 本轮提速到 60s（PLAN §1 低余量提速）
- 事件经 queue.Queue 传主线程（tkinter 非线程安全，回调在 UI 侧用 root.after 消费）
- "立即刷新" kick()：源文件不可改，故在 scheduler 侧清空 bailian 的 _cache/_cache_at
  进程内缓存（60s TTL）实现绕过；属性不存在则静默跳过、行为退化为可能命中缓存。
"""
from __future__ import annotations

import queue
import threading
import time

from .sources.base import Usage

BACKOFF_CAP = 1800.0   # 指数退避封顶 30min
FAST_INTERVAL = 60.0   # 低余量提速周期（与 config.POLL_MIN_SECONDS 同值）


class Scheduler:
    def __init__(self, sources, poll_seconds: float = 300.0,
                 low_yellow_pct: float = 0.15) -> None:
        self.sources = list(sources)
        self.poll = max(FAST_INTERVAL, float(poll_seconds))
        self.low = float(low_yellow_pct)
        self.events: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._force = False
        self._streak: dict[str, int] = {getattr(s, "name", "?"): 0 for s in self.sources}
        self._thread: threading.Thread | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="token-widget-poll")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def kick(self) -> None:
        """立即刷新：唤醒线程并请求绕过源缓存。"""
        self._force = True
        self._wake.set()

    def set_sources(self, sources) -> None:
        """设置面板改启停后热替换（GIL 下单次赋值原子，线程下一轮生效）。"""
        self.sources = list(sources)
        for s in self.sources:
            self._streak.setdefault(getattr(s, "name", "?"), 0)

    # ---- 线程主体 ----

    def _run(self) -> None:
        # 等待形态：睡在 _wake 上，可被 kick() 唤醒，也可超时自然到期。
        # stop() 同时置 _stop 与 _wake → wait 立即返回、循环头判停退出，不引入竞态。
        # _force 为标志位（非队列）：等待期内多次 kick 合并为一轮；周期内被 kick
        # 则由 `if self._force: continue` 立即续轮，各窗口下 kick 均不丢失。
        while not self._stop.is_set():
            force, self._force = self._force, False
            delay = self._cycle(force=force)
            if self._force:              # kick 落在本周期内 → 跳过休眠立即下一轮
                continue
            self._wake.wait(timeout=delay)
            self._wake.clear()

    def _cycle(self, force: bool = False) -> float:
        self.events.put(("tick", None, {"ts": time.time()}))
        usages: list[Usage] = []
        for src in self.sources:
            if force:
                self._bypass_cache(src)
            try:
                u = src.fetch()
            except Exception as e:  # source 契约是返回 Usage，兜底防线程崩
                u = Usage(provider=getattr(src, "name", "?"), ok=False,
                          error_code="SOURCE_EXCEPTION", error_msg=str(e)[:200])
            usages.append(u)

        low = False
        for u in usages:
            n = u.provider
            if u.ok:
                self._streak[n] = 0
            elif u.error_code == "not_configured":
                self._streak[n] = 0
                continue
            else:
                self._streak[n] = self._streak.get(n, 0) + 1
            if u.ok:
                pr = None
                if u.pct_used is not None:
                    pr = 1.0 - u.pct_used
                elif u.total and u.remaining is not None:
                    pr = u.remaining / u.total
                if pr is not None and pr < self.low:
                    low = True

        # 退避语义：poll ≤ delay ≤ CAP，连续失败逐轮翻倍（600/1200/1800…封顶）。
        # 多源取最长退避（失败源背靠背保护最强）；无失败源时保持 poll。
        delay = self.poll
        for st in self._streak.values():
            if st > 0:
                delay = max(delay, min(BACKOFF_CAP,
                                       max(self.poll, self.poll * (2 ** st))))
        if low:
            delay = min(delay, FAST_INTERVAL)
        delay = max(delay, FAST_INTERVAL)

        self.events.put(("update", usages,
                         {"next_delay": delay, "ts": time.time(),
                          "streak": dict(self._streak), "low": low}))
        return delay

    # ---- "立即刷新"绕过源进程内缓存（不动 sources 文件的唯一途径） ----

    @staticmethod
    def _bypass_cache(src) -> None:
        try:
            if hasattr(src, "_cache") and hasattr(src, "_cache_at"):
                src._cache = None
                src._cache_at = 0.0
        except Exception:
            pass
