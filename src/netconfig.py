"""M8 网络代理：仅境外源（OpenAI / OpenCode Go）走 HTTP/CONNECT 代理。

硬边界：**百炼永不经过本模块**（bailian.py / bailian_gateway.py 零改动，直连行为
与 v1.1.0 一致）；scheduler / ui / registry / main 亦不感知代理。

- 配置节 config.network：proxy_enabled / proxy_url（原始用户输入）/
  proxy_targets（M11a 默认 ["opencode_go","codex"]，UI 不出现百炼）。
- normalize_proxy_url()：接受 "127.0.0.1:7890"、"http://127.0.0.1:7890"、
  "host 空格 port" 两段式（均可带 http://user:pass@ 认证段）→ "http://host:port"；
  空/无端口/socks 等非法 → None（即直连）。socks 明确不支持。
- build_opener()：ProxyHandler({http,https}→proxy) + HTTPSHandler（CONNECT 隧道为
  urllib 内建）+ 与两源一致的「不跟随重定向」策略；无代理/未启用 → None（源走默认直连）。
- 凭据纪律：代理 URL 可含 user:pass → sanitize_proxy_msg() 把 "://user:pass@" 脱敏为
  "://user:***@"；**错误 msg/tooltip/日志一律先过脱敏**。
- classify_openai_http()：OpenAI 401/403 子类判定（M8 缺陷修复）——Cloudflare 地理封锁
  （403 + error.code=unsupported_country_region_territory，含 body 子串兜底）单独归
  REGION_BLOCKED，不再误报 KEY_INVALID（地区问题≠密钥问题）。境外两家专用，百炼不调用。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import config as _config

PROBE_URL = "https://api.openai.com/v1/models"   # 零凭据连通性探测点（401 也算通）
PROBE_TIMEOUT = 10.0

# OpenAI Cloudflare 地理封锁码（对 /v1/models 与 /v1/organization/costs 一致）
_REGION_CODES = ("unsupported_country_region_territory",)
REGION_MSG = "代理出口地区不被 OpenAI 支持，请在代理软件切换海外节点后重试"  # 不含 key/密钥字样

_SCHEMES = ("http", "https")                     # socks 明确不支持（README 文案同步）

# "host:port" / "host port" 两段式（无 scheme 输入；host 允许 [] IPv6 与 user:pass@ 前缀）
_TWO_PART = re.compile(r"^(\S+?)[:\s]+(\d{1,5})$")
# 文本中的 URL 认证段：scheme://user[:pass]@  → 密码替换为 ***
_AUTH_TEXT = re.compile(r"([A-Za-z][\w+.\-]*)://([^\s/@:]*)(?::([^\s/@]*))?@")


def network_section(cfg: dict | None) -> dict:
    """config.network 节读取（DEFAULTS 兜底合并；老 config 缺节安全）。"""
    d = dict(_config.DEFAULTS.get("network") or {})
    v = cfg.get("network") if isinstance(cfg, dict) else None
    if isinstance(v, dict):
        d.update(v)
    return d


def normalize_proxy_url(s: str | None) -> str | None:
    """用户输入 → 规范 "http://[user[:pass]@]host[:port]"；空/非法 → None。

    接受："127.0.0.1:7890"、"http://127.0.0.1:7890"、"127.0.0.1 7890"（两段式）、
    "http://user:pass@host:port"（认证段保留，展示需 sanitize）。**端口必选**。
    拒绝：无端口裸 host（含 "http://host"）、socks 等协议、非法字符、端口越界。
    """
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if "://" not in t:
        m = _TWO_PART.fullmatch(t)               # host[:| ]port 宽进
        if not m:
            return None
        t = "http://" + m.group(1) + ":" + m.group(2)
    try:
        p = urllib.parse.urlsplit(t)
        port = p.port                            # 越界/非数字 → ValueError
    except ValueError:
        return None
    scheme = (p.scheme or "").lower()
    if scheme not in _SCHEMES or not p.hostname:
        return None                              # socks/裸主机名缺失等 → 不支持
    if p.path not in ("", "/") or p.query or p.fragment:
        return None                              # 路径/查询段视为输入错误
    if not port:
        return None                              # 返回形态固定 http://host:port，端口必选
    userinfo = ""
    if p.username is not None:
        userinfo = urllib.parse.unquote(p.username)
        if p.password is not None:
            userinfo += ":" + urllib.parse.unquote(p.password)
        userinfo += "@"
    host = p.hostname
    hb = f"[{host}]" if ":" in host else host    # IPv6 保持括号
    out = f"{scheme}://{userinfo}{hb}"
    if port:
        out += f":{port}"
    return out


def proxy_for(provider: str, cfg: dict | None) -> str | None:
    """proxy_enabled ∧ provider∈proxy_targets ∧ URL 合法 → 代理 URL；否则 None。

    百炼从不调用本函数（UI 作用域也只有境外两家）；targets 非 list 视为无目标。
    """
    net = network_section(cfg)
    if not bool(net.get("proxy_enabled", False)):
        return None
    targets = net.get("proxy_targets")
    if not isinstance(targets, list) or provider not in targets:
        return None
    return normalize_proxy_url(net.get("proxy_url"))


def build_opener(cfg: dict | str | None):
    """启用且 URL 合法 → 带 ProxyHandler 的 OpenerDirector；否则 None（源走直连默认）。

    cfg 可传完整配置 dict（读 network 节）或已规范化的代理 URL 字符串。
    https 目标经 CONNECT 隧道（urllib ProxyHandler 内建），TLS 端到端仍由源校验。
    """
    if isinstance(cfg, str):
        proxy = normalize_proxy_url(cfg)
    elif isinstance(cfg, dict):
        net = network_section(cfg)
        proxy = normalize_proxy_url(net.get("proxy_url")) if bool(net.get("proxy_enabled")) else None
    else:
        proxy = None
    if not proxy:
        return None
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
        urllib.request.HTTPSHandler(),
        type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
             {"redirect_request": lambda *a, **k: None})())


def sanitize_proxy_msg(text) -> str:
    """脱敏文本中的代理认证段：scheme://user:pass@ → scheme://user:***@。永不抛。"""
    if not isinstance(text, str):
        return str(text or "")
    if "@" not in text:
        return text

    def _repl(m):
        user, pw = m.group(2), m.group(3)
        return f"{m.group(1)}://{user}:***@" if pw is not None else f"{m.group(1)}://{user}@"
    return _AUTH_TEXT.sub(_repl, text)


def classify_openai_http(status: int, body_text: str) -> tuple[str, str]:
    """OpenAI 401/403 响应 → (error_code, 用户文案)（M8 缺陷修复：地区封锁单独分类）。

    决策表（区域判定优先——地区封锁会掩盖真实 key 状态，按封锁链路报「密钥无效」是误导）：
    - body JSON error.code ∈ _REGION_CODES，或（JSON 解析失败/无 code 字段时）
      body 子串含该 code 字符串 → ("REGION_BLOCKED", REGION_MSG)——不含 key/密钥字样；
    - 401（任意 body）→ ("KEY_INVALID", "需要 Organization Admin key…")（维持 wire spec 文案）；
    - 其余 403 → ("KEY_INVALID", "需要 Organization Admin key…")（维持）；
    - 其他状态码 → ("HTTP_<status>", "")（兜底；调用方仅在 401/403 处接入，理论不达）。
    """
    body = body_text or ""
    code = None
    try:
        j = json.loads(body)
        if isinstance(j, dict):
            e = j.get("error")
            if isinstance(e, dict) and isinstance(e.get("code"), str):
                code = e.get("code")
    except ValueError:
        pass
    low = body.lower()
    if code in _REGION_CODES or any(rc.lower() in low for rc in _REGION_CODES):
        return ("REGION_BLOCKED", REGION_MSG)
    if status == 401:
        return ("KEY_INVALID", "需要 Organization Admin key（401：key 无效或非 Admin）")
    if status == 403:
        return ("KEY_INVALID", "需要 Organization Admin key（403：非 Admin 或权限不足）")
    return (f"HTTP_{status}", "")


def probe_channel(proxy_url: str | None, timeout: float = PROBE_TIMEOUT,
                  opener=None) -> tuple[int | None, str, bool]:
    """测试连通（零凭据依赖）：拿到任意 HTTP 状态码即通道可达；
    仅 TCP/TLS/DNS/代理连接失败算失败。M8 缺陷修复：三态化——

    返回 (状态码|None, 已脱敏原因, region_blocked)：
    - (None, detail, False)：通道未建立（连接层失败）；
    - (403, "", True)：通道通但 Cloudflare 地理封锁（需换海外节点）；
    - (st, "", False)：通道正常（含 401 / 非地区 403）。

    opener 参数供测试注入；None 时按 proxy_url 现场构建。
    """
    try:
        op = opener
        if op is None:
            op = (build_opener(proxy_url) if proxy_url else None) \
                or urllib.request.build_opener()   # 非法 URL 兜底为直连探测
        req = urllib.request.Request(PROBE_URL, method="GET",
                                     headers={"User-Agent": "token-widget/1.0",
                                              "Accept": "application/json"})
        try:
            with op.open(req, timeout=timeout) as resp:
                return int(getattr(resp, "status", 200) or 200), "", False
        except urllib.error.HTTPError as e:
            st = int(e.code)
            blocked = False
            if st == 403:                          # 仅 403 读 body 判地区封锁（≤4KB）
                try:
                    body = (e.read(4096) or b"").decode("utf-8", "replace")
                except Exception:                  # noqa: BLE001  读不到就按普通 403
                    body = ""
                blocked = classify_openai_http(403, body)[0] == "REGION_BLOCKED"
            return st, "", blocked
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or e
        return None, sanitize_proxy_msg(str(reason))[:120], False
