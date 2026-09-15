"""百炼控制台网关底层协议（国内站个人版）。

逐字节移植自 scripts/probe_api.py（M0 已实测通过），规格：
docs/bailian_gateway_spec.md §0–§6。stdlib-only。

⚠️ 两条硬禁令（规格 §3）：
- cornerstoneParam 不得带硬编码 switchAgent（→Workspace.NotAuthorised）
- 不得把国内 Cookie 配国际身份（→Login.NotLogined）
"""
from __future__ import annotations

import json
import re
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request

from ..auth import cookie_value

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

# usage 空窗口重试（规格 §6.4）：最多 3 次 × 400ms
USAGE_ATTEMPTS = 3
USAGE_RETRY_DELAY = 0.4

OPENER = urllib.request.build_opener(_NoRedirect := type(
    "NoRedirect", (urllib.request.HTTPRedirectHandler,),
    {"redirect_request": lambda *a, **k: None}))


class LoginExpired(Exception):
    """重定向/非 JSON 拦截页 → 视为登出（Cookie 过期，需重贴）。"""


def _req(url: str, headers: dict, data: bytes | None = None) -> tuple[int, str, bytes]:
    r = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with OPENER.open(r, timeout=TIMEOUT) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            raise LoginExpired(
                f"HTTP {e.code} redirect -> Location={e.headers.get('Location', '')[:80]}") from None
        body = e.read() if e.fp else b""
        return e.code, e.headers.get("content-type", ""), body


def base_headers(cookie: str) -> dict[str, str]:
    """规格 §2：POST 打到 bailian-cs，但 Origin/Referer 填 bailian（dashboard 域）。"""
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


# ---- 规格 §5：sec_token 三级解析（全失败则裸发）----
SEC_PATTERNS = [
    r'"secToken"\s*:\s*"([^"]+)"',
    r'"sec_token"\s*:\s*"([^"]+)"',
    r"secToken['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
    r"sec_token['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
    r"SEC_TOKEN['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
]


def expand_json_strings(obj):
    """规格 §6.1：递归展开内嵌 JSON 字符串（网关常双重 stringify）。"""
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


def find_key(obj, keys: tuple[str, ...]) -> str | None:
    obj = expand_json_strings(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v:
                return v
        for v in obj.values():
            r = find_key(v, keys)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, keys)
            if r:
                return r
    return None


def resolve_sec_token(cookie: str) -> tuple[str | None, str]:
    """三级：dashboard HTML（带导航头）→ user/info.json → Cookie 现成值。"""
    nav = dict(base_headers(cookie))
    nav.update({"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document"})
    try:
        _, _, raw = _req(DASHBOARD_URL, nav)
        html = raw.decode("utf-8", "replace")
        for pat in SEC_PATTERNS:
            m = re.search(pat, html)
            if m:
                return m.group(1), "dashboard-html"
    except (urllib.error.URLError, LoginExpired):
        pass
    try:
        _, _, raw = _req(f"{DASHBOARD_ORIGIN}/tool/user/info.json", base_headers(cookie))
        j = json.loads(raw)
        tok = find_key(j, ("secToken", "sec_token"))
        if tok:
            return tok, "user-info.json"
    except (urllib.error.URLError, LoginExpired, ValueError):
        pass
    tok = cookie_value(cookie, "sec_token")
    if tok:
        return tok, "cookie"
    return None, "none(裸发)"


# ---- 规格 §6：信封判定与错误分类 ----
def find_fail_frame(obj) -> dict | None:
    """递归任一 frame success|Success===false（或 successResponse===false）→ 失败。"""
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
    """错误分类（对 code+message 小写启发）。

    ⚠️ Workspace.NotAuthorised 是缺/错 sec_token 的信号 → 补 token 重试，
       绝不能提示用户重贴 Cookie（规格 §6.3）。
    """
    blob = " ".join([str(code), str(msg), json.dumps(frame or {}, ensure_ascii=False)]).lower()
    if "workspace" in blob and ("notauthoris" in blob or "unauthorized" in blob):
        return "WORKSPACE_NOTAUTHORISED(缺/错 sec_token，勿重贴 Cookie → 补 token 重试)"
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
    result: dict = {"http": st, "api": api.rsplit("/", 1)[-1]}
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


def call_api(cookie: str, sec_token: str | None, api: str,
             data_extra: dict | None = None, is_usage: bool = False) -> dict:
    """单接口调用；usage 空窗口最多 3 次 × 400ms 重试（规格 §6.4）。"""
    attempts = USAGE_ATTEMPTS if is_usage else 1
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
        if i < attempts - 1:
            time.sleep(USAGE_RETRY_DELAY)
    return r
