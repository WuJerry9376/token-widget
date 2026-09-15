"""M0 probe — 百炼控制台网关四接口实测（零依赖 stdlib）。

规格：docs/bailian_gateway_spec.md（lib-1 逐字节提取，并集最保守形态）。
用法（token-widget 目录）：
    python scripts/probe_api.py                # 按 subscription→quota-config→usage→addon 顺序全测
    python scripts/probe_api.py usage          # 单测：usage|quota-config|subscription|addon
"""
from __future__ import annotations

import json
import re
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from auth import cookie_value, load_bailian_cookie  # noqa: E402

# ---- 常量（规格 §0/§1）----
QUOTA_ORIGIN = "https://bailian-cs.console.aliyun.com"
DASHBOARD_ORIGIN = "https://bailian.console.aliyun.com"
DASHBOARD_URL = (f"{DASHBOARD_ORIGIN}/cn-beijing?tab=plan"
                 "#/efm/subscription/token-plan/personal")
PRODUCT = "sfm_bailian"
ACTION = "BroadScopeAspnGateway"
REGION = "cn-beijing"
COMMODITY = "sfm_tokenplansolo_public_cn"
ADDON_COMMODITY = "sfm_tokenplansoloaddon_public_cn"
API_PREFIX = "zeldaHttp.apikeyMgr./tokenplan/personal/api/v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")
TIMEOUT = 20

OPENER = urllib.request.build_opener(_NoRedirect := type(
    "NoRedirect", (urllib.request.HTTPRedirectHandler,),
    {"redirect_request": lambda *a, **k: None}))


class LoginExpired(Exception):
    pass


def _req(url: str, headers: dict, data: bytes | None = None) -> tuple[int, str, bytes]:
    r = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with OPENER.open(r, timeout=TIMEOUT) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            raise LoginExpired(f"HTTP {e.code} redirect -> Location={e.headers.get('Location','')[:80]}") from None
        body = e.read() if e.fp else b""
        return e.code, e.headers.get("content-type", ""), body


def base_headers(cookie: str) -> dict[str, str]:
    csrf = cookie_value(cookie, "login_aliyunid_csrf") or ""
    return {
        "Cookie": cookie,
        "x-xsrf-token": csrf,
        "x-csrf-token": csrf,
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": DASHBOARD_ORIGIN,
        "Referer": f"{DASHBOARD_ORIGIN}/",
    }


# ---- 规格 §5：sec_token 三级解析 ----
SEC_PATTERNS = [
    r'"secToken"\s*:\s*"([^"]+)"',
    r'"sec_token"\s*:\s*"([^"]+)"',
    r"secToken['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
    r"sec_token['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
    r"SEC_TOKEN['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
]


def _find_key(obj, keys: tuple[str, ...]) -> str | None:
    obj = expand_json_strings(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v:
                return v
        for v in obj.values():
            r = _find_key(v, keys)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, keys)
            if r:
                return r
    return None


def resolve_sec_token(cookie: str) -> tuple[str | None, str]:
    nav = dict(base_headers(cookie))
    nav.update({"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document"})
    try:
        st, _, raw = _req(DASHBOARD_URL, nav)
        html = raw.decode("utf-8", "replace")
        for pat in SEC_PATTERNS:
            m = re.search(pat, html)
            if m:
                return m.group(1), "dashboard-html"
    except (urllib.error.URLError, LoginExpired):
        pass
    try:
        st, _, raw = _req(f"{DASHBOARD_ORIGIN}/tool/user/info.json", base_headers(cookie))
        j = json.loads(raw)
        tok = _find_key(j, ("secToken", "sec_token"))
        if tok:
            return tok, "user-info.json"
    except (urllib.error.URLError, LoginExpired, ValueError):
        pass
    tok = cookie_value(cookie, "sec_token")
    if tok:
        return tok, "cookie"
    return None, "none(裸发)"


# ---- 规格 §6：信封展开与错误分类 ----
def expand_json_strings(obj):
    if isinstance(obj, str):
        s = obj.strip()
        if s[:1] in "{[" and s[-1:] in "}]":
            try:
                return expand_json_strings(json.loads(s))
            except ValueError:
                return obj
        return obj
    if isinstance(obj, dict):
        return {k: expand_json_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_json_strings(v) for v in obj]
    return obj


def find_fail_frame(obj) -> dict | None:
    if isinstance(obj, dict):
        if (obj.get("success") is False) or (obj.get("Success") is False):
            return obj
        if str(obj.get("successResponse", "")).lower() == "false":
            return obj
        for v in obj.values():
            f = find_fail_frame(v)
            if f:
                return f
    elif isinstance(obj, list):
        for v in obj:
            f = find_fail_frame(v)
            if f:
                return f
    return None


def classify_error(frame: dict | None, code: str = "", msg: str = "") -> str:
    blob = " ".join([str(code), str(msg), json.dumps(frame or {}, ensure_ascii=False)]).lower()
    if "workspace" in blob and ("notauthoris" in blob or "unauthorized" in blob):
        return "WORKSPACE_NOTAUTHORISED(缺/错 sec_token，勿重贴 Cookie → 检查规格§5 解析)"
    if re.search(r"needlogin|notlogined|login\.|postonly|tokenerror|has expired|refresh page|请求已经过期", blob):
        return "LOGIN_EXPIRED(Cookie 过期 → 重新抓取)"
    if re.search(r"notauthoris|unauthorized|access denied|forbidden", blob):
        return "AUTH_DENIED(鉴权失败)"
    return "UNKNOWN"


def extract_payload(env) -> dict | None:
    """{code,data:{DataV2:{data:{success,code,data:<payload>}}}} → payload"""
    try:
        frame = env["data"]["DataV2"]["data"]
        return frame.get("data")
    except (KeyError, TypeError):
        return None


# ---- 规格 §2/§3：网关调用 ----
def gateway_post(cookie: str, sec_token: str | None, api: str,
                 data_extra: dict | None = None) -> dict:
    cornerstone = {
        "feTraceId": str(uuid.uuid4()).lower(),
        "feURL": DASHBOARD_URL,
        "protocol": "V2",
        "console": "ONE_CONSOLE",
        "productCode": "p_efm",
        "switchUserType": 3,
        "domain": "bailian.console.aliyun.com",
        "consoleSite": "BAILIAN_ALIYUN",
        "userNickName": "",
        "userPrincipalName": "",
        "xsp_lang": "zh-CN",
    }
    cna = cookie_value(cookie, "cna")
    if cna:
        cornerstone["X-Anonymous-Id"] = cna
    data: dict = {"commodityCode": COMMODITY, **(data_extra or {}), "cornerstoneParam": cornerstone}
    params = {"Api": api, "V": "1.0", "Data": data}
    body: dict[str, str] = {
        "product": PRODUCT, "action": ACTION, "region": REGION,
        "language": "zh-CN", "params": json.dumps(params, ensure_ascii=False, separators=(",", ":")),
    }
    if sec_token:
        body["sec_token"] = sec_token
    url = (f"{QUOTA_ORIGIN}/data/api.json?" + urllib.parse.urlencode(
        {"action": ACTION, "product": PRODUCT, "api": api, "_v": "undefined"}))
    headers = base_headers(cookie)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    st, ctype, raw = _req(url, headers, urllib.parse.urlencode(body).encode())
    result = {"http": st, "api": api.rsplit("/", 1)[-1]}
    if "json" not in ctype:
        raise LoginExpired(f"HTTP {st} non-JSON ({ctype[:40]}) → 视为登出/HTML 拦截页")
    env = expand_json_strings(json.loads(raw))
    result["outer_code"] = env.get("code")
    fail = find_fail_frame(env)
    if fail is not None:
        result["error"] = classify_error(fail, env.get("code", ""), env.get("message", ""))
        result["detail"] = {k: fail.get(k) for k in ("code", "message", "msg", "requestId") if k in fail}
    result["env"] = env
    return result


def probe_api(cookie: str, sec_token: str | None, api: str,
              data_extra: dict | None = None, is_usage: bool = False) -> dict:
    attempts = 3 if is_usage else 1
    r: dict = {}
    for i in range(attempts):
        r = gateway_post(cookie, sec_token, api, data_extra)
        if r.get("error"):
            if i == attempts - 1:
                return r
        else:
            payload = extract_payload(r["env"]) or {}
            r["payload"] = payload
            if not is_usage or any("Percentage" in k for k in payload):
                return r
            r["empty_window"] = True
        time.sleep(0.4)
    return r


def ms_to_str(v) -> str:
    if not isinstance(v, (int, float)):
        return str(v)
    s = int(v) if v >= 1e12 else int(v) * 1000
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s / 1000))


def main() -> None:
    cookie = load_bailian_cookie()
    targets = sys.argv[1:] or ["subscription", "quota-config", "usage", "addon"]
    st, src = resolve_sec_token(cookie)
    print(f"[setup] cookie_chars={len(cookie)} sec_token={((st[:6]+'…') if st else None)!r} via={src}")

    spec = weekly = used_pct = reset = None
    results = {}
    for t in targets:
        api, extra, is_usage = {
            "usage": (f"{API_PREFIX}/usage", None, True),
            "quota-config": (f"{API_PREFIX}/quota-config", None, False),
            "subscription": (f"{API_PREFIX}/subscription", None, False),
            "addon": (f"{API_PREFIX}/addon/list",
                      {"commodityCode": ADDON_COMMODITY, "status": ["ACTIVE"],
                       "pageNum": 1, "pageSize": 10}, False),
        }[t]
        try:
            r = probe_api(cookie, st, api, extra, is_usage)
        except LoginExpired as e:
            print(f"\n===== {t} ===== LoginExpired? {e}")
            continue
        print(f"\n===== {t} ===== http={r['http']} outer_code={r.get('outer_code')}"
              + (f" ERROR={r['error']} {r.get('detail')}" if r.get("error") else "")
              + (" EMPTY_WINDOW(重试后仍空)" if r.get("empty_window") else ""))
        results[t] = r
        if r.get("payload") is not None:
            print(json.dumps(r["payload"], ensure_ascii=False, indent=1)[:1500])
        p = r.get("payload") or {}
        if t == "subscription":
            spec = p.get("specCode") or p.get("spec_code") or p.get("planName")
            print(f"  [spec]={spec!r} status={p.get('status')!r} end={ms_to_str(p.get('endTime'))}")
        if t == "quota-config" and spec:
            tier = p.get(str(spec), {})
            weekly = tier.get("weekly")
            print(f"  [weekly({spec})]={weekly}")
        if t == "usage":
            u = p.get("per1WeekPercentage")
            if isinstance(u, (int, float)):
                if u > 1:
                    u = u / 100
                used_pct = u
                print(f"  [1w used]={u:.1%} reset={ms_to_str(p.get('per1WeekResetTime'))}"
                      f" | 5h={p.get('per5HourPercentage')!r}(可能缺省)")
    if weekly and used_pct is not None:
        print(f"\n[剩余估算] 本周窗口 ≈ {weekly * (1 - used_pct):,.0f} / {weekly:,} Credits")
    print("\n[done] 原始信封 JSON 未全量打印；需要时去掉截断。")


if __name__ == "__main__":
    main()
