"""百炼个人版 source（PLAN.md §2.1 / docs/bailian_gateway_spec.md）。

传输（docs/bailian_auto_auth_plan.md §3，config.bailian_mode）：
- auto：helper 客户端可用 → poll；HELPER_ERROR/NO_CREDENTIAL/不可用 → 降级 legacy；
- helper：仅 helper（失败按协议错误码回 LOGIN_EXPIRED/NO_CREDENTIAL/HELPER_ERROR）；
- legacy：urllib + 粘贴 Cookie（原有路径，行为不变）。
两路共用 _parse_envelope/_compose：helper 信封文本经 gw.expand_json_strings/
find_fail_frame/classify_error/extract_payload，与 legacy 解析语义逐字段一致。

顺序：subscription → quota-config → usage → addon（addon 失败容错，不影响整体 ok）。
主窗口口径自适应（规格 §7，2026-09-23 实测：订阅临期时网关不下发 per1Week*，仅回
per1Month* 月度剩余额度）：**周优先、月兜底**——有 per1WeekPercentage → 主窗=周
（quota 取 tier.weekly，label "7d"，旧行为）；无周仅有 per1MonthPercentage → 主窗=月
（quota 取 tier.monthly，label "月"，reset 用 per1MonthResetTime）；两者皆无 →
PARSE_EMPTY。
剩余公式：主窗 quota × (1 − 主窗百分比) + Σ addon.remainingCredits。
5h 字段缺省时不出 5h 窗口（PLAN §7-Q5）。
凭据只经 auth.load_bailian_cookie()；错误 msg 不含 Cookie 值。
"""
from __future__ import annotations

import inspect
import json
import time
import urllib.error
from datetime import datetime, timezone

from ..auth import load_bailian_cookie
from . import bailian_gateway as gw
from .bailian_client import LOGIN_TIMEOUT_SECONDS, BailianHelperClient
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


def _pick_num(d, *keys) -> float | None:
    """dict 按序取首个数值键（防御非 dict/非数值/bool；规格 §7 tier 混合形态）。"""
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    return None


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

    # helper 事件文案（协议 §4；UI 侧仅暴露 last_event/event_text，ui.py 配色零改动）
    EVENT_TEXTS = {"login_required": "等待人工登录（助手已弹窗）",
                   "login_failed": "自动登录失败（助手已尝试）"}
    # auto 模式下触发降级 legacy 的 helper 级错误（基础设施态；plan §3.3）
    _FALLBACK_CODES = ("HELPER_ERROR", "NO_CREDENTIAL")

    def __init__(self, mode: str | None = None, client=None) -> None:
        self._cache: Usage | None = None
        self._cache_at: float = 0.0  # monotonic
        self._mode_override = mode
        self._client = client if client is not None else BailianHelperClient()
        # reauth 请求在途旗标：client 的 login_inflight 只认 login_interactive，
        # reauth 占用 helper 串行队列同样必须让 poll 闭嘴（协议 §6 看门狗红线）。
        self._reauth_inflight = False
        self.last_event: dict | None = None
        try:
            self._client.on_event = self._on_helper_event
        except Exception:
            self._client = None

    # ---- 对外接口 ----

    def fetch(self) -> Usage:
        """采集一次；TTL 内命中进程内缓存（供上层 60s+ 轮询调度）。"""
        now = time.monotonic()
        if self._cache is not None and now - self._cache_at < self.CACHE_TTL:
            return self._cache
        usage = self._fetch_fresh()
        self._cache, self._cache_at = usage, now
        return usage

    # ---- 传输选择（config.bailian_mode）----

    def _mode(self) -> str:
        if self._mode_override:
            return self._mode_override
        try:
            from .. import config as _config
            m = str(_config.load_config().get("bailian_mode", "auto")).strip().lower()
        except Exception:
            return "auto"
        return m if m in ("auto", "helper", "legacy") else "auto"

    def _fetch_fresh(self) -> Usage:
        mode = self._mode()
        if mode != "legacy":
            u = self._fetch_via_helper()
            if u is not None and (mode == "helper"
                                  or u.error_code not in self._FALLBACK_CODES):
                return u
            # auto + helper 基础设施错误/不可用 → 透明降级
        return self._fetch_legacy()

    # ---- helper 传输 ----

    def _on_helper_event(self, ev: dict) -> None:
        self.last_event = ev

    @property
    def event_text(self) -> str | None:
        ev = self.last_event or {}
        return self.EVENT_TEXTS.get(str(ev.get("event")))

    # ---- UI 侧 helper 感知入口（M25；探测不 spawn、永不抛异常）----

    @property
    def mode(self) -> str:
        """当前传输模式（_mode 的公开只读入口：auto|helper|legacy）。"""
        return self._mode()

    @property
    def helper_running(self) -> bool:
        """常驻 helper 进程活着（非阻塞探测；False=静默窗内/未启动/已死）。"""
        c = self._client
        if c is None or not c.available():
            return False
        proc = getattr(c, "_proc", None)
        return proc is not None and proc.poll() is None

    @property
    def has_saved_creds(self) -> bool:
        """CM 是否存有百炼账密（auto-renewal 判定用）。

        包装 auth.load_bailian_login()（CredReadW 快同步 ~ms）：存在凭据 → True；
        不存在（None）或任何读取异常 → False。凭据值绝不外泄、不落 UI。"""
        try:
            from .. import auth
            return auth.load_bailian_login() is not None
        except Exception:
            return False

    def interactive_login(self) -> dict | None:
        """透传 {"cmd":"login_interactive"}（协议 §2），阻塞等 helper 回包——
        调用方须放子线程。helper 不可用/无进程/异常 → None。

        看门狗用 LOGIN_TIMEOUT_SECONDS（660s，协议 §6 L3 人工等待 10min + 余量），
        避免弹窗期间被 45s 默认看门狗 kill+respawn；客户端 request 不支持
        timeout 形参时（替身/旧签名）回落默认看门狗。"""
        c = self._client
        if c is None or not self.helper_running:
            return None
        cmd = {"cmd": "login_interactive"}
        try:
            if self._request_accepts_timeout(c):
                return c.request(cmd, timeout=LOGIN_TIMEOUT_SECONDS)
            return c.request(cmd)
        except Exception:
            return None

    @staticmethod
    def _request_accepts_timeout(client) -> bool:
        try:
            return "timeout" in inspect.signature(client.request).parameters
        except (TypeError, ValueError):
            return False    # 无法内省 → 保守走旧签名

    def reauth_login(self) -> dict | None:
        """透传 {"cmd":"reauth"}（协议 §2 增补 2026-10-12）：与 interactive_login
        同看门狗/同 None 语义，但 helper 侧跳过「已 live 立即回包」短路——
        会话健康也强制走登录页提升 + L2/L3（显式重登/换账号入口）。调用方须放
        子线程。helper 不可用/无进程/异常 → None。在途期间 _reauth_inflight
        压制 poll（client.login_inflight 只认 login_interactive）。"""
        c = self._client
        if c is None or not self.helper_running:
            return None
        cmd = {"cmd": "reauth"}
        self._reauth_inflight = True
        try:
            if self._request_accepts_timeout(c):
                return c.request(cmd, timeout=LOGIN_TIMEOUT_SECONDS)
            return c.request(cmd)
        except Exception:
            return None
        finally:
            self._reauth_inflight = False

    def _fetch_via_helper(self) -> Usage | None:
        """poll 一次拿四信封；usage 空窗口按 gw 常量重试 3×400ms。None=不可用/降级。

        登录在途（login_inflight：login_interactive 请求中或 login_required 事件后、
        login_done/login_failed 前）→ 不写任何命令（helper 串行队列被人工登录占住，
        写 poll 会排队撞 45s 看门狗误杀 helper），直接回 LOGIN_EXPIRED 语义。"""
        client = self._client
        if client is None:
            return None
        if getattr(client, "login_inflight", False) or self._reauth_inflight:
            return _fail(self.name, "LOGIN_EXPIRED", "等待人工登录中")
        if not client.available():
            return None
        data: dict = {}
        r_u: dict = {"error": "HELPER_ERROR", "detail": {"message": "no poll data"}}
        for attempt in range(gw.USAGE_ATTEMPTS):
            resp = client.request({"cmd": "poll"})
            if not resp.get("ok"):
                return self._helper_error_usage(resp)
            data = resp.get("data") or {}
            r_u = self._parse_envelope(data.get("usage"))
            if r_u.get("error"):
                break
            if any("Percentage" in k for k in (r_u.get("payload") or {})):
                break                                # 与 gw.call_api(is_usage) 同判据
            r_u["empty_window"] = True
            if attempt < gw.USAGE_ATTEMPTS - 1:
                time.sleep(gw.USAGE_RETRY_DELAY)
        r_sub = self._parse_envelope(data.get("subscription"))
        r_q = self._parse_envelope(data.get("quota_config"))
        r_a = self._parse_envelope(data.get("addon"))  # null/缺失 → error 容错（同 legacy）
        return self._compose(r_sub, r_q, r_u, r_a)

    def _helper_error_usage(self, resp: dict) -> Usage:
        state = str(resp.get("state") or "")
        err = str(resp.get("error") or "HELPER_ERROR").split("(", 1)[0]
        detail = str(resp.get("detail") or "")[:200]
        if state == "need_login" or err == "LOGIN_EXPIRED":
            return _fail(self.name, "LOGIN_EXPIRED", detail or "helper 登录态失效")
        if state == "no_credential" or err == "NO_CREDENTIAL":
            return _fail(self.name, "NO_CREDENTIAL", detail or "凭据管理器无已存账密")
        return _fail(self.name, "HELPER_ERROR", detail or err)

    @staticmethod
    def _parse_envelope(env_text) -> dict:
        """helper 信封原始 JSON 字符串 → gw.call_api 同形 dict（error/detail/payload）。
        分类/取 payload 全部复用 gw 函数，保证与 legacy 语义一致（协议 §3）。"""
        if not isinstance(env_text, str) or not env_text.strip():
            return {"error": "HELPER_ERROR", "detail": {"message": "envelope 缺失"}}
        try:
            env = gw.expand_json_strings(json.loads(env_text))
        except ValueError:
            return {"error": "BAD_JSON", "detail": {"message": env_text[:120]}}
        fail = gw.find_fail_frame(env)
        if fail is not None:
            # 同 gateway_post：classify_error 入参取外层 code/message（无 Cookie 明文）
            outer_code = env.get("code", "") if isinstance(env, dict) else ""
            outer_msg = env.get("message", "") if isinstance(env, dict) else ""
            return {"error": gw.classify_error(fail, outer_code, outer_msg),
                    "detail": {k: fail.get(k) for k in
                               ("code", "message", "msg", "requestId") if k in fail},
                    "env": env}
        return {"payload": gw.extract_payload(env) or {}, "env": env}

    # ---- legacy 传输（原路径，行为不变）----

    def _fetch_legacy(self) -> Usage:
        try:
            cookie = load_bailian_cookie()
        except OSError as e:
            return _fail(self.name, "NO_CREDENTIAL", f"Cookie 读取失败：{e}")
        self._sec_token, _src = gw.resolve_sec_token(cookie)
        self._token_retried = False

        # 1) subscription（档位；错误短路，不发后续请求——与重构前逐字节同行为）
        r_sub = self._call(cookie, f"{gw.API_PREFIX}/subscription")
        if err := r_sub.get("error"):
            return self._usage_error(err, r_sub)
        # 2) quota-config（档位总额）
        r_q = self._call(cookie, f"{gw.API_PREFIX}/quota-config")
        if err := r_q.get("error"):
            return self._usage_error(err, r_q)
        # 3) usage（窗口百分比；空窗口 3×400ms 重试在 gw.call_api 内）
        r_u = self._call(cookie, f"{gw.API_PREFIX}/usage", is_usage=True)
        if err := r_u.get("error"):
            return self._usage_error(err, r_u)
        if r_u.get("empty_window"):
            return _fail(self.name, "EMPTY_WINDOW", "usage 重试 3 次后仍无 per*Percentage 字段")
        # 4) addon（用量包；国内站路径未证实 → 失败容错，不影响整体 ok）
        try:
            r_a = self._call(cookie, f"{gw.API_PREFIX}/addon/list", data_extra={
                "commodityCode": gw.ADDON_COMMODITY, "status": ["ACTIVE"],
                "pageNum": 1, "pageSize": 10})
        except gw.LoginExpired:
            r_a = {"error": "ADDON_SKIPPED"}  # 容错：addon 失败不升级为整体失败（也不误导为重贴 Cookie）
        return self._compose(r_sub, r_q, r_u, r_a)

    def _compose(self, r_sub: dict, r_q: dict, r_u: dict, r_a: dict) -> Usage:
        """两传输共用的组合逻辑（错误顺序 subscription→quota→usage；addon 容错；
        剩余公式与主窗口口径选择原样保留）。"""
        if err := r_sub.get("error"):
            return self._usage_error(err, r_sub)
        p_sub = r_sub.get("payload") or {}
        spec = p_sub.get("specCode") or p_sub.get("spec_code") or p_sub.get("planName")
        # M23：subscription.endTime（毫秒 epoch）→ 套餐到期时刻（缺失/坏型 → None=不显示）
        plan_end = _ms_to_dt(p_sub.get("endTime"))

        if err := r_q.get("error"):
            return self._usage_error(err, r_q)
        p_q = r_q.get("payload") or {}
        tier = p_q.get(str(spec), {}) if spec else {}

        if err := r_u.get("error"):
            return self._usage_error(err, r_u)
        if r_u.get("empty_window"):
            return _fail(self.name, "EMPTY_WINDOW", "usage 重试 3 次后仍无 per*Percentage 字段")
        p_u = r_u.get("payload") or {}
        wk_pct = _norm_pct(p_u.get("per1WeekPercentage"))
        wk_reset = _ms_to_dt(p_u.get("per1WeekResetTime"))
        mo_pct = _norm_pct(p_u.get("per1MonthPercentage"))
        mo_reset = _ms_to_dt(p_u.get("per1MonthResetTime"))
        h5_pct = _norm_pct(p_u.get("per5HourPercentage"))
        h5_reset = _ms_to_dt(p_u.get("per5HourResetTime"))

        # 主窗口口径选择：周优先、月兜底（两者都有按周=旧口径；都无 → PARSE_EMPTY）
        if p_u.get("per1WeekPercentage") is not None:
            q_keys, pct_key = ("weekly",), "per1WeekPercentage"
            main_label, main_pct, main_reset = "7d", wk_pct, wk_reset
        elif p_u.get("per1MonthPercentage") is not None:
            q_keys, pct_key = ("monthly",), "per1MonthPercentage"
            main_label, main_pct, main_reset = "月", mo_pct, mo_reset
        else:
            return _fail(self.name, "PARSE_EMPTY",
                         "关键字段缺失：per1WeekPercentage/per1MonthPercentage 均无"
                         f"（usage payload 键：{sorted(p_u) or '空'}）")

        # 4) addon（用量包；国内站路径未证实 → 失败容错，不影响整体 ok；
        #    helper 路 data.addon 为 null 亦走此容错分支）
        addon_remaining = addon_total = 0.0
        addon_ok = False
        if not r_a.get("error"):
            items = _addon_items(r_a.get("payload"))
            addon_remaining = sum(x.get("remainingCredits") or 0 for x in items
                                  if isinstance(x.get("remainingCredits"), (int, float)))
            addon_total = sum(x.get("totalCredits") or 0 for x in items
                              if isinstance(x.get("totalCredits"), (int, float)))
            addon_ok = True

        # quota 按主窗口口径取键（tier 可能缺失/非 dict/非数值 → None 走失败语义）
        quota = _pick_num(tier, *q_keys)
        if not isinstance(quota, (int, float)) or main_pct is None:
            return _fail(self.name, "PARSE_EMPTY",
                         f"关键字段缺失：{q_keys[0]}={quota!r} "
                         f"{pct_key}={p_u.get(pct_key)!r}")

        # 剩余公式（规格 §7）：主窗 quota×(1−pct) + Σaddon.remainingCredits
        main_left = quota * (1 - main_pct)
        remaining = main_left + (addon_remaining if addon_ok else 0)
        total = quota + (addon_total if addon_ok else 0)

        windows = [Window(label=main_label, pct_used=main_pct, resets_at=main_reset)]
        if h5_pct is not None:  # 5h 缺省时不出窗口（曾被临时下线）
            windows.append(Window(label="5h", pct_used=h5_pct, resets_at=h5_reset))

        return Usage(
            provider=self.name, ok=True, spec=spec, unit="credits",
            used=quota * main_pct, total=total, remaining=remaining,
            pct_used=main_pct, resets_at=main_reset, windows=windows,
            addon_remaining=addon_remaining if addon_ok else None,
            plan_end=plan_end,
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
