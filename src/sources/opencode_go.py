"""OpenCode Go source（M6 真采集；线路规格：docs/openai_go_wire_spec.md §2，仅线路 A）。

- GET https://opencode.ai/zen/go/v1/usage  Header: Authorization: Bearer <Go key>
  Accept: application/json + User-Agent【spec §2.1】。
- key 来源（spec §2.3）：DPAPI secret opencode_go_key 优先；否则（config
  opencode_go.auto_detect=true）经 auth.detect_go_key() 读 opencode auth.json 的
  "opencode-go" 条目——**绝不回退用 Zen（"opencode"）key**（打此端点必 403）。
- 字段（spec §2.2 API 变体，双形态兼容）：usage.rolling（必有）/ weekly / monthly（有则进
  windows）；percent 0..100 → 0..1（>1 才 /100，与百炼同款），dashboard 变体 usagePercent
  兼容兜底；status=="rate-limited" → 100%；resetsAt ISO 带小数秒 / epoch 数字（>1e12 毫秒、
  >1e9 秒）双兼容，dashboard 变体 resetInSec（倒计时秒）亦兼容。
- 语义：unit="percent"；服务端不下发绝对额 → total/remaining=None；主行=rolling（UI 文案"~5h"）。
- 错误映射（spec §2.4，403 必须解析 body）：401→KEY_INVALID；
  403 且 body error.type=="EntitlementError"→NO_SUBSCRIPTION（其他 403→HTTP_403"不可用"）；
  429→RATE_LIMITED；≠200 读 body message/error/detail 或 HTML <title> 前 80 字符。
- 无任何 key → not_configured（附绑定指引，不做网络调用）；结果缓存 60s；msg 永不含 key 值。
- M8 网络代理：按 config.network（proxy_enabled ∧ "opencode_go"∈proxy_targets）经
  netconfig.build_opener 走 HTTP/CONNECT 代理；未启用/不在作用域 → 默认直连；
  连接失败 NETWORK msg 带代理/直连提示，代理认证段先脱敏。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from .. import auth, netconfig
from .base import ProviderSource, Usage, Window

CACHE_TTL_SECONDS = 60.0

USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
UA = "token-widget/1.0"
TIMEOUT = 20

_OPENER = urllib.request.build_opener(type(
    "NoRedirect", (urllib.request.HTTPRedirectHandler,),
    {"redirect_request": lambda *a, **k: None}))


def _req(url: str, headers: dict, opener=None) -> tuple[int, str, bytes]:
    """GET 传输层（仿 gw._req，不跟随重定向；模块级，测试可 monkeypatch）。

    opener：M8 代理 OpenerDirector；None → 直连默认。
    """
    r = urllib.request.Request(url, headers=headers, method="GET")
    target = opener if opener is not None else _OPENER
    try:
        with target.open(r, timeout=TIMEOUT) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.code, "", b""
        return e.code, e.headers.get("content-type", ""), (e.read() if e.fp else b"")


def _load_cfg() -> dict:
    from .. import config as config_mod
    return config_mod.load_config()


def _secret(name: str) -> str | None:
    try:
        return auth.load_secret(name) or None
    except OSError:
        return None


def _norm_pct(v) -> float | None:
    """0..100 → 0..1；读取端防御：v>1 → v/100（与 bailian._norm_pct 同构）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v / 100 if v > 1 else float(v)


def _to_dt(v) -> datetime | None:
    """resetsAt 双兼容：epoch 数字（>1e12 毫秒 / >1e9 秒）或 ISO8601（带小数秒、Z 尾缀）。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        secs = v / 1000.0 if v >= 1e12 else float(v)
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, str):
        s = v.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            try:
                return _to_dt(float(s))
            except ValueError:
                return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def _parse_window(w: dict) -> tuple[float | None, datetime | None]:
    """单窗口 → (pct_used 0..1, resets_at)。percent|usagePercent、resetsAt|resetInSec 双形态。"""
    if str(w.get("status", "")).lower() == "rate-limited":
        pct = 1.0                                # spec §2.2："rate-limited" 视为 100%
    else:
        v = w.get("percent")
        if v is None:
            v = w.get("usagePercent")            # dashboard 变体兼容兜底（风险②）
        pct = _norm_pct(v)
    reset = _to_dt(w.get("resetsAt"))
    if reset is None:
        s = w.get("resetInSec")
        if isinstance(s, (int, float)) and not isinstance(s, bool):
            reset = datetime.now(timezone.utc) + timedelta(seconds=float(s))
    return pct, reset


def _body_err(raw: bytes) -> tuple[str | None, str]:
    """(error.type, 提示语)：JSON error.type + message/error/detail，或 HTML <title> ≤80 字符。"""
    etype: str | None = None
    try:
        j = json.loads(raw)
    except ValueError:
        j = None
    if isinstance(j, dict):
        e = j.get("error")
        if isinstance(e, dict):
            if isinstance(e.get("type"), str):
                etype = e["type"]
            if isinstance(e.get("message"), str) and e["message"]:
                return etype, e["message"][:80]
        for k in ("message", "error", "detail"):
            v = j.get(k)
            if isinstance(v, str) and v:
                return etype, v[:80]
    m = re.search(rb"<title[^>]*>(.*?)</title>", raw[:4096], re.I | re.S)
    if m:
        return etype, m.group(1).decode("utf-8", "replace").strip()[:80]
    return etype, ""


def _fail(code: str, msg: str) -> Usage:
    return Usage(provider="opencode_go", ok=False, unit="percent",
                 error_code=code, error_msg=msg)


class OpenCodeGoSource(ProviderSource):
    name = "opencode_go"
    enabled_by_default = False

    CACHE_TTL = CACHE_TTL_SECONDS

    def __init__(self) -> None:
        self._cache: Usage | None = None
        self._cache_at: float = 0.0  # monotonic

    # ---- 对外接口 ----

    def fetch(self) -> Usage:
        now = time.monotonic()
        if self._cache is not None and now - self._cache_at < self.CACHE_TTL:
            return self._cache
        usage = self._fetch_fresh()
        self._cache, self._cache_at = usage, now
        return usage

    def fetch_now(self) -> Usage:
        """忽略缓存立即采集并回填（设置页「保存即验证」用）。"""
        usage = self._fetch_fresh()
        self._cache, self._cache_at = usage, time.monotonic()
        return usage

    # ---- 内部实现 ----

    def _fetch_fresh(self) -> Usage:
        cfg = _load_cfg()
        sec = cfg.get("opencode_go") or {}
        key = _secret("opencode_go_key")
        if key is None and bool(sec.get("auto_detect", True)):
            key = auth.detect_go_key()           # 只认 "opencode-go" 条目；Zen 必不采用
        if not key:
            return _fail("not_configured",
                         "未绑定 OpenCode Go key：在设置页粘贴 Go key，或先登录 opencode 自动检测")
        # M8：代理路由（仅本境外源；未启用/不在作用域 → None → 直连现状）
        proxy = netconfig.proxy_for(self.name, cfg)
        opener = netconfig.build_opener(proxy) if proxy else None
        net_hint = "（代理已启用，检查地址/软件）" if proxy else "（未配置代理，直连失败）"
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json",
                   "User-Agent": UA}
        try:
            st, _ct, raw = _req(USAGE_URL, headers, opener=opener)
        except (urllib.error.URLError, OSError) as e:
            # reason 可能内嵌代理 URL（含 user:pass）→ 先脱敏再拼提示
            return _fail("NETWORK", netconfig.sanitize_proxy_msg(
                f"网络错误：{str(getattr(e, 'reason', e))[:120]}") + net_hint)
        if st == 401:
            return _fail("KEY_INVALID", "Go key 无效（401）→ 请在设置页重新绑定")
        if st == 403:
            # spec §2.4：必须解析 403 body 的 error.type，不能只看 status
            etype, hint = _body_err(raw)
            if etype == "EntitlementError":
                return _fail("NO_SUBSCRIPTION", "此 key 无 OpenCode Go 订阅（EntitlementError）")
            return _fail("HTTP_403", hint or "不可用（403，可能被代理/WAF 拦截）")
        if st == 429:
            return _fail("RATE_LIMITED", "源限流（429），下一轮自动退避")
        if st != 200:
            _t, hint = _body_err(raw)
            return _fail(f"HTTP_{st}", hint or f"HTTP {st}")
        try:
            j = json.loads(raw)
        except ValueError:
            return _fail("PARSE_EMPTY", "usage 响应非 JSON")
        usage = j.get("usage") if isinstance(j, dict) else None
        rolling = usage.get("rolling") if isinstance(usage, dict) else None
        if not isinstance(rolling, dict):
            return _fail("PARSE_EMPTY", "响应缺少 usage.rolling（校验：rolling 必须存在）")

        windows: list[Window] = []
        pct, reset = _parse_window(rolling)
        windows.append(Window(label="rolling", pct_used=pct, resets_at=reset))
        for label in ("weekly", "monthly"):     # 缺省则不进 windows、不渲染（spec §2.2）
            w = usage.get(label) if isinstance(usage, dict) else None
            if isinstance(w, dict):
                p, r = _parse_window(w)
                windows.append(Window(label=label, pct_used=p, resets_at=r))

        return Usage(provider=self.name, ok=True, unit="percent",
                     pct_used=pct, resets_at=reset, windows=windows)
