"""Codex（ChatGPT 订阅 Plan 窗口限额）source —— M10 实验性第 4 家。

规格唯一事实来源：docs/codex_chatgpt_wire_spec.md。**非官方前端接口，ToS 灰区，
可能随时失效**（UI/README 均标实验性）；与 OpenAI 平台（api.openai.com）完全独立，
不共用任何凭据。

- GET https://chatgpt.com/backend-api/codex/usage  Bearer <ChatGPT OAuth access_token>
  必带 `originator: codex_cli_rs`（M10b：CF 边缘指纹放行开关，缺→challenge 403/HTML）
  + Sec-Fetch-Mode: cors / Sec-Fetch-Dest: empty 加固；UA 保留 token-widget 身份不伪装；
  **绝不发 Accept-Encoding**（H1 教训：声明后 gzip 体 urllib 不解码必炸，见 BASE_HEADERS 注）。
- token 来源（M10b）：DPAPI secret codex_access_token 优先，否则 auth.find_codex_auth()
  按序搜 local\\auth.json → 项目根/exe 同级 auth.json → ~/.codex/auth.json
  （auth_mode=chatgpt 的 tokens.access_token；只读、绝不回显；source_path 仅面板显示）。
- 窗口（spec 判读规则 1）：按 limit_window_seconds 匹配——18000→"5h"、604800→"周"、
  其余值→"other:<sec>"；primary/secondary 同一规则收集，**绝不按位置写死**。
  windows 排序=最紧窗在前（spec Usage 映射「pct_used 取最紧窗」，与主行 label 一致）。
- used_percent 0..100 → 0..1（>1 才 /100，同 Go 防御）；rate_limit.allowed==False
  → 该组窗口 pct 钳 1.0（spec 规则 5 的窗口语义）。
- reset（spec 规则 2）：reset_at（epoch 秒）优先，reset_after_seconds 倒计时兜底。
- credits（spec 规则 4）：has_credits 时 balance（十进制串）→ float 放 Usage.
  addon_remaining 复用位（tooltip 注明「积分余额 $x.xx（实验性源）」）；否则 None。
- rate_limit_reset_credits（M10b 新字段）：available_count>0 → Usage.note
  「窗口重置券：可用 x」（tooltip 有则显）；PII（user_id/account_id/email）零采集。
- spec=plan_type（PLUS/PRO 徽章由 ui 大写化）；unit="percent"（Go 同型多窗渲染）。
- 错误：401→KEY_INVALID（登录已过期→续期流，语义=百炼 Cookie 档）；403/HTML→NETWORK
  （Cloudflare 拦截按网络档退避加大，防重试轰炸）；429→RATE_LIMITED；
  其余非 200→HTTP_<st>（body detail/error.message 文案源）；缺 rate_limit/窗口→PARSE_EMPTY。
- 无 token → not_configured（零网络）。60s 进程内缓存 + fetch_now（保存即验证）。
- M8 代理复用：chatgpt.com 亦需海外出口，netconfig.proxy_for("codex", cfg)；
  连接失败 msg 带代理/直连语境并先脱敏。
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

USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"
UA = "codex_cli_rs/0.44.0 (token-widget)"        # spec：社区实现常用固定值
TIMEOUT = 20

# M10b CF 边缘指纹层（spec「CF 边缘指纹层」节，403 矩阵实测）：
# - **originator: codex_cli_rs 是放行开关**——缺它 → CF challenge 403（HTML，非 401，
#   与 token 无关）；J1 实证：产品 UA（不伪装）+ originator 即 200。
# - Sec-Fetch-Mode: cors + Sec-Fetch-Dest: empty 为加固对（J2 实证同样通）。
# - **绝不发 Accept-Encoding**（H1 教训：显式声明 → 响应体 gzip 而 urllib 不解码，
#   JSON 解析必炸；不发则 urllib 不带该头，服务端给 identity，实测正常）。
# - UA 保留 token-widget 身份标识，不伪装真实 CLI。
BASE_HEADERS = {"Accept": "application/json",
                "User-Agent": UA,
                "originator": "codex_cli_rs",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty"}

# 窗口秒数 → 显示 label（spec 规则 1：按秒数匹配，禁按 primary/secondary 位置）
WINDOW_LABELS = {18000: "5h", 604800: "周"}

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
    """0..100 → 0..1；读取端防御：v>1 → v/100（与 bailian/go 同构）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v / 100 if v > 1 else float(v)


def _epoch_dt(v) -> datetime | None:
    """reset_at：epoch 秒（>1e12 视作毫秒兼容）→ aware UTC。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    secs = v / 1000.0 if v >= 1e12 else float(v)
    try:
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _win_label(w: dict) -> str:
    sec = w.get("limit_window_seconds")
    if isinstance(sec, (int, float)) and not isinstance(sec, bool):
        s = int(sec)
        return WINDOW_LABELS.get(s, f"other:{s}")
    return "other:unknown"                        # 缺秒数字段也不丢数据，显式标注


def _parse_window(w: dict, exhausted: bool) -> Window:
    """单窗口 → Window(label, pct, resets_at)。allowed=False → pct 钳 1.0。"""
    pct = _norm_pct(w.get("used_percent"))
    if exhausted:
        pct = 1.0
    reset = _epoch_dt(w.get("reset_at"))
    if reset is None:
        s = w.get("reset_after_seconds")
        if isinstance(s, (int, float)) and not isinstance(s, bool):
            reset = datetime.now(timezone.utc) + timedelta(seconds=float(s))
    return Window(label=_win_label(w), pct_used=pct, resets_at=reset)


def _body_hint(raw: bytes) -> str:
    """错误文案源（spec 规则 6）：detail / error.message / message，或 HTML title ≤80。"""
    try:
        j = json.loads(raw)
    except ValueError:
        j = None
    if isinstance(j, dict):
        for k in ("detail", "message"):
            v = j.get(k)
            if isinstance(v, str) and v:
                return v[:80]
        e = j.get("error")
        if isinstance(e, dict) and isinstance(e.get("message"), str) and e["message"]:
            return e["message"][:80]
        if isinstance(e, str) and e:
            return e[:80]
    m = re.search(rb"<title[^>]*>(.*?)</title>", raw[:4096], re.I | re.S)
    if m:
        return m.group(1).decode("utf-8", "replace").strip()[:80]
    return ""


def _credits_balance(resp: dict) -> float | None:
    """spec 规则 4：has_credits 时 balance（十进制串）→ float；否则 None。"""
    cr = resp.get("credits")
    if not isinstance(cr, dict) or not bool(cr.get("has_credits")):
        return None
    b = cr.get("balance")
    if isinstance(b, bool):
        return None
    if isinstance(b, (int, float)):
        return float(b)
    if isinstance(b, str):
        try:
            return float(b.strip())
        except ValueError:
            return None
    return None


def _reset_note(resp: dict) -> str | None:
    """M10b：rate_limit_reset_credits{available_count, applicable_available_count}
    → Usage.note「窗口重置券：可用 x」（无字段/非 int/≤0 → None 不显）。

    仅取计数展示；applicable_available_count 已采集但暂不进文案（无适用场景时
    与 available 混淆）。PII（user_id/account_id/email）在解析层天然零采集。
    """
    rc = resp.get("rate_limit_reset_credits")
    if not isinstance(rc, dict):
        return None
    n = rc.get("available_count")
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        return None
    return f"窗口重置券：可用 {n}"


def _fail(code: str, msg: str) -> Usage:
    return Usage(provider="codex", ok=False, unit="percent",
                 error_code=code, error_msg=msg)


class CodexSource(ProviderSource):
    name = "codex"
    enabled_by_default = False                     # 实验性：不默认启用

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
        # token 解析序（不变）：手动 DPAPI secret > find_codex_auth 自动搜索
        # （local\auth.json → 项目根/exe 同级 auth.json → ~/.codex/auth.json）
        found = auth.find_codex_auth()
        key = _secret("codex_access_token") or (found[0] if found else None)
        if not key:
            return _fail("not_configured",
                         "未绑定 Codex token：放置 auth.json 到 local\\ 或登录 Codex CLI"
                         "（写 ~/.codex/auth.json）；异机可在设置页手动粘贴 access_token")
        # M8：代理路由（chatgpt.com 亦需海外出口；spec 实现备忘）
        proxy = netconfig.proxy_for(self.name, cfg)
        opener = netconfig.build_opener(proxy) if proxy else None
        net_hint = "（代理已启用，检查地址/软件）" if proxy else "（未配置代理，直连失败）"
        headers = dict(BASE_HEADERS, Authorization=f"Bearer {key}")   # 不发 Accept-Encoding
        try:
            st, ct, raw = _req(USAGE_URL, headers, opener=opener)
        except (urllib.error.URLError, OSError) as e:
            return _fail("NETWORK", netconfig.sanitize_proxy_msg(
                f"网络错误：{str(getattr(e, 'reason', e))[:120]}") + net_hint)
        if st == 401:
            return _fail("KEY_INVALID", "登录已过期，重新获取 access token"
                                        "（Codex CLI 重新登录或设置页重贴）")
        if st == 429:
            return _fail("RATE_LIMITED", "源限流（429），下一轮自动退避")
        if st == 403 or "json" not in ct.lower():
            # spec 规则 6：403/HTML = Cloudflare 拦截 → 网络档，退避加大防重试轰炸
            hint = _body_hint(raw)
            return _fail("NETWORK", "疑似 Cloudflare 拦截（403/HTML，非官方接口常态）"
                                    "，已自动退避" + (f"：{hint}" if hint else ""))
        if st != 200:
            return _fail(f"HTTP_{st}", _body_hint(raw) or f"HTTP {st}")
        try:
            j = json.loads(raw)
        except ValueError:
            return _fail("PARSE_EMPTY", "usage 响应非 JSON")
        if not isinstance(j, dict):
            return _fail("PARSE_EMPTY", "usage 响应非 JSON 对象")
        rl = j.get("rate_limit")
        if not isinstance(rl, dict):
            return _fail("PARSE_EMPTY", "响应缺少 rate_limit（字段漂移？实验性源）")

        exhausted = bool(rl.get("allowed") is False)   # spec 规则 5：allowed=false → 耗尽
        windows: list[Window] = []
        for pos in ("primary_window", "secondary_window"):
            w = rl.get(pos)
            if isinstance(w, dict):
                windows.append(_parse_window(w, exhausted))
        if not windows:
            return _fail("PARSE_EMPTY", "primary/secondary 窗口均缺失（套餐无数据？）")
        # 最紧窗在前（spec Usage 映射「pct_used 取最紧窗」；pct None 殿后；同紧短窗优先）
        windows.sort(key=lambda w: (-(w.pct_used if w.pct_used is not None else -1.0),
                                    0 if w.label == "5h" else (1 if w.label == "周" else 2)))
        main = windows[0]

        plan = j.get("plan_type")
        return Usage(provider=self.name, ok=True,
                     spec=plan if isinstance(plan, str) and plan else None,
                     unit="percent", pct_used=main.pct_used, resets_at=main.resets_at,
                     windows=windows, addon_remaining=_credits_balance(j),
                     note=_reset_note(j))
