"""百炼个人版 source（PLAN.md §2.1 / docs/bailian_gateway_spec.md）。

顺序：subscription → quota-config → usage → addon（addon 失败容错，不影响整体 ok）。
剩余公式：weekly × (1 − per1WeekPercentage) + Σ addon.remainingCredits。
5h 字段缺省时不出 5h 窗口（PLAN §7-Q5）。
凭据只经 auth.load_bailian_cookie()；错误 msg 不含 Cookie 值。
"""
from __future__ import annotations

import json
import time
import urllib.error
from datetime import datetime, timezone

from ..auth import load_bailian_cookie
from . import bailian_gateway as gw
from .base import ProviderSource, Usage, Window

# 结果进程内缓存 TTL（秒），供上层调度参考（规格 §6.6 建议 usage 60s）
CACHE_TTL_SECONDS = 60.0


def _ms_to_dt(v) -> datetime | None:
    """毫秒 epoch（<1e12 视为秒 ×1000，规格 §7）→ aware datetime。"""
    if not isinstance(v, (int, float)):
        return None
    ms = int(v) if v >= 1e12 else int(v) * 1000
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _norm_pct(v) -> float | None:
    """百分比归一 0..1；读取端防御：v>1 → v/100（规格 §7）。"""
    if not isinstance(v, (int, float)):
        return None
    return v / 100 if v > 1 else v


def _addon_items(payload) -> list[dict]:
    """items 在 items|list|records|data 任一键（规格 §7）。"""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in ("items", "list", "records", "data"):
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _fail(provider: str, code: str, msg: str) -> Usage:
    return Usage(provider=provider, ok=False, error_code=code, error_msg=msg)


class BailianSource(ProviderSource):
    name = "bailian"
    enabled_by_default = True

    CACHE_TTL = CACHE_TTL_SECONDS

    def __init__(self) -> None:
        self._cache: Usage | None = None
        self._cache_at: float = 0.0  # monotonic

    # ---- 对外接口 ----

    def fetch(self) -> Usage:
        """采集一次；TTL 内命中进程内缓存（供上层 60s+ 轮询调度）。"""
        now = time.monotonic()
        if self._cache is not None and now - self._cache_at < self.CACHE_TTL:
            return self._cache
        usage = self._fetch_fresh()
        self._cache, self._cache_at = usage, now
        return usage

    # ---- 内部实现 ----

    def _fetch_fresh(self) -> Usage:
        try:
            cookie = load_bailian_cookie()
        except OSError as e:
            return _fail(self.name, "NO_CREDENTIAL", f"Cookie 读取失败：{e}")
        self._sec_token, _src = gw.resolve_sec_token(cookie)
        self._token_retried = False

        # 1) subscription（档位）
        r_sub = self._call(cookie, f"{gw.API_PREFIX}/subscription")
        if err := r_sub.get("error"):
            return self._usage_error(err, r_sub)
        p_sub = r_sub.get("payload") or {}
        spec = p_sub.get("specCode") or p_sub.get("spec_code") or p_sub.get("planName")

        # 2) quota-config（档位总额）
        r_q = self._call(cookie, f"{gw.API_PREFIX}/quota-config")
        if err := r_q.get("error"):
            return self._usage_error(err, r_q)
        p_q = r_q.get("payload") or {}
        tier = p_q.get(str(spec), {}) if spec else {}
        weekly = tier.get("weekly") if isinstance(tier, dict) else None

        # 3) usage（窗口百分比；空窗口 3×400ms 重试在 gw.call_api 内）
        r_u = self._call(cookie, f"{gw.API_PREFIX}/usage", is_usage=True)
        if err := r_u.get("error"):
            return self._usage_error(err, r_u)
        if r_u.get("empty_window"):
            return _fail(self.name, "EMPTY_WINDOW", "usage 重试 3 次后仍无 per*Percentage 字段")
        p_u = r_u.get("payload") or {}
        wk_pct = _norm_pct(p_u.get("per1WeekPercentage"))
        wk_reset = _ms_to_dt(p_u.get("per1WeekResetTime"))
        h5_pct = _norm_pct(p_u.get("per5HourPercentage"))
        h5_reset = _ms_to_dt(p_u.get("per5HourResetTime"))

        # 4) addon（用量包；国内站路径未证实 → 失败容错，不影响整体 ok）
        addon_remaining = addon_total = 0.0
        addon_ok = False
        try:
            r_a = self._call(cookie, f"{gw.API_PREFIX}/addon/list", data_extra={
                "commodityCode": gw.ADDON_COMMODITY, "status": ["ACTIVE"],
                "pageNum": 1, "pageSize": 10})
            if not r_a.get("error"):
                items = _addon_items(r_a.get("payload"))
                addon_remaining = sum(x.get("remainingCredits") or 0 for x in items
                                      if isinstance(x.get("remainingCredits"), (int, float)))
                addon_total = sum(x.get("totalCredits") or 0 for x in items
                                  if isinstance(x.get("totalCredits"), (int, float)))
                addon_ok = True
        except gw.LoginExpired:
            pass  # 容错：addon 失败不升级为整体失败（也不误导为重贴 Cookie）

        if not isinstance(weekly, (int, float)) or wk_pct is None:
            return _fail(self.name, "PARSE_EMPTY",
                         f"关键字段缺失：weekly={weekly!r} per1WeekPercentage={p_u.get('per1WeekPercentage')!r}")

        # 剩余公式（规格 §7）：weekly×(1−pct) + Σaddon.remainingCredits
        weekly_left = weekly * (1 - wk_pct)
        remaining = weekly_left + (addon_remaining if addon_ok else 0)
        total = weekly + (addon_total if addon_ok else 0)

        windows = [Window(label="7d", pct_used=wk_pct, resets_at=wk_reset)]
        if h5_pct is not None:  # 5h 缺省时不出窗口（曾被临时下线）
            windows.append(Window(label="5h", pct_used=h5_pct, resets_at=h5_reset))

        return Usage(
            provider=self.name, ok=True, spec=spec, unit="credits",
            used=weekly * wk_pct, total=total, remaining=remaining,
            pct_used=wk_pct, resets_at=wk_reset, windows=windows,
            addon_remaining=addon_remaining if addon_ok else None,
        )

    def _call(self, cookie: str, api: str, data_extra: dict | None = None,
              is_usage: bool = False) -> dict:
        """网关调用；WORKSPACE_NOTAUTHORISED = 缺/错 sec_token → 重解析补 token 重试一次。"""
        try:
            r = gw.call_api(cookie, self._sec_token, api, data_extra, is_usage)
        except gw.LoginExpired as e:
            return {"error": "LOGIN_EXPIRED(Cookie 过期 → 重新抓取)", "detail": {"message": str(e)}}
        except urllib.error.URLError as e:
            return {"error": "NETWORK", "detail": {"message": str(e.reason)[:120]}}
        except ValueError as e:
            return {"error": "BAD_JSON", "detail": {"message": str(e)[:120]}}
        if str(r.get("error", "")).startswith("WORKSPACE") and not self._token_retried:
            self._token_retried = True
            self._sec_token, _ = gw.resolve_sec_token(cookie)
            try:
                r = gw.call_api(cookie, self._sec_token, api, data_extra, is_usage)
            except (gw.LoginExpired, urllib.error.URLError, ValueError):
                pass
        return r

    @staticmethod
    def _usage_error(err: str, r: dict) -> Usage:
        code = err.split("(", 1)[0]
        detail = r.get("detail") or {}
        msg = err + (" " + json.dumps(detail, ensure_ascii=False)[:200] if detail else "")
        return _fail("bailian", code, msg)  # detail 只含网关 code/message/requestId，无 Cookie
