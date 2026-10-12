"""百炼常驻 Helper（bailian_helper_protocol v1 · 车道 B）。

架构：docs/bailian_auto_auth_plan.md §3（常驻进程 + WebView2 隐藏窗口 + 页内
fetch 搬运）。协议：docs/bailian_helper_protocol.md（stdin/stdout 行分隔 JSON）。

启动：``python main.py --bailian-helper --profile-dir <dir>``（webview 在 main()
内延迟导入；模块本身可在无 webview 环境下 import，供纯函数单测）。

安全红线（协议 §7）：cookie 值/账密明文绝不进 stderr、日志、事件、响应、异常
文本；账密明文只出现在两处——save_creds 命令的 stdin 管道内、以及页内
autofill JS 的 evaluate_js 载荷里。
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.sources import bailian_gateway as gw   # 只引用常量；不得修改该模块

# 车道 A（src/auth.py CM 账密契约，协议 §8）可能尚未实现——容错导入
try:
    from src import auth as _auth
except ImportError:      # pragma: no cover - 环境缺 auth 时走 HELPER_ERROR
    _auth = None

# ---------------------------------------------------------------- 常量

CONSOLE_URL = "https://bailian.console.aliyun.com/"
LOGIN_URL = "https://account.aliyun.com/login/login.htm"
#: L2 账密填充专用页（2026-10-10 实探 selector_probe/2.json）：account 登录页顶层
#: **零输入元素**，表单在跨源 iframe（#alibaba-login-box → passport.aliyun.com，
#: contentDocument 被同源策略挡死，无 document.domain 桥接）。该 iframe 的账密
#: entrance URL 可独立顶层渲染（探针实证：fm-* 选择器全命中、假标记填充回读通过），
#: 因此 L2 不再尝试在 account 页填表，而是先导航到此页。
#: **降级为 fallback（2026-10-10 17:11 实证修订）**：helper.log 显示提交动作已
#: 执行但窗口全程泊在 passport（parked x1→x6，从未进入 login_aliyun.htm 握手）
#: ——静态 URL 携带探针时刻捕获的 returnUrl/rnd，会过期使重定向链死胡同。主路径
#: 改为在 account 页实时抓取 iframe 新鲜 src（_promote_to_pwd_entrance）；本常量
#: 只在抓取失败时兜底（有过期 URL 也胜过无 entrance 可填）。
PWD_LOGIN_URL = (
    "https://passport.aliyun.com/havanaone/login/login.htm"
    "?lang=zh_CN&appName=aliyun&appEntrance=aliyun_pc_pwd"
    "&styleType=vertical&bizParams=&notLoadSsoView=true"
    "&notKeepLogin=true&isMobile=false&targetId=alibaba-login-iframe"
    "&regUrl=https%3A%2F%2Faccount.aliyun.com%2Fregister%2Fqr_register.htm"
    "&returnUrl=https%3A%2F%2Faccount.aliyun.com%2Flogin%2Flogin_aliyun.htm"
    "%3Fft%3Dpc_pwd_m%26log_channel%3Dindep%26log_platform%3Dpc"
    "%26login_log_entrance%3Dofficial%26login_method%3Dpwd_login%26log_biz%3Daliyun"
    "&newSmsLoginReg=true"
    "&cssUrl=https%3A%2F%2Fg.alicdn.com%2Fdawn%2Faliyun-account-styles"
    "%2F0.0.1%2Flogin-embedder.css"
    "&bizPassParams=%7B%22tenantName%22%3A%22%22%7D")
PWD_LOGIN_HOST = "passport.aliyun.com"
ACCOUNT_LOGIN_HOST = "account.aliyun.com"
WINDOW_TITLE = "百炼 Helper（登录时可操作）"   # Win32 弹窗/隐藏按此标题定位

KNOWN_CMDS = frozenset({"poll", "login_interactive", "reauth", "status",
                        "shutdown", "save_creds"})

#: 四接口端点（协议 §5）。helper 内自组 data_extra，同 gateway_post 的 Data 合并规则。
API_ENDPOINTS = {
    "subscription": (f"{gw.API_PREFIX}/subscription", None),
    "quota_config": (f"{gw.API_PREFIX}/quota-config", None),
    "usage": (f"{gw.API_PREFIX}/usage", None),
    "addon": (f"{gw.API_PREFIX}/addon/list",
              {"commodityCode": gw.ADDON_COMMODITY, "status": ["ACTIVE"],
               "pageNum": 1, "pageSize": 10}),
}
KINDS = ("subscription", "quota_config", "usage", "addon")
LOGIN_GATE_KINDS = ("subscription", "quota_config", "usage")   # addon 不参与登录判定

#: 登录表单 DOM 选择器集中常量表（协议 §6；DOM 改版只改这里，失效自动降级 L3）。
#: 元素位于 PWD_LOGIN_URL 顶层帧——2026-10-10 local/selector_probe2.json 实证：
#: #fm-login-id / #fm-login-password / form#login-form 提交按钮均可见且假标记
#: 填充回读通过；#fm-login-checkcode 常态隐藏，出现即可见态风控验证码。
#: "tab" 仅在 account 登录页有形态（div.tabs-nav-item，文本"账密登录"），配合
#: LOGIN_TAB_TEXTS 文本匹配点击；passport 页无 tab，找不到即跳过、不阻塞。
LOGIN_SELECTORS = {
    "tab": [".tabs-nav-item", "[role=\"tab\"]", ".login-tab-item"],
    "username": ["#fm-login-id",
                 "input[name=\"fm-login-id\"]",
                 "input.fm-text:not(.fm-checkcode)"],
    "password": ["#fm-login-password",
                 "input[name=\"fm-login-password\"]",
                 "input[type=\"password\"]"],
    "submit": ["form#login-form button[type=\"submit\"]",
               "button.fm-button.fm-submit.password-login",
               "button.fm-submit",
               "button[type=\"submit\"]"],
    "checkcode": ["#fm-login-checkcode",
                  "input.fm-checkcode"],            # 可见 = 风控，L2 弃权
}

#: 账密/密码 tab 的按钮文案（探针在 account 页实测文本"账密登录"）
LOGIN_TAB_TEXTS = ("账密登录", "密码登录", "账号密码登录")

#: 时间预算（协议 §2/§6/§7；§6 修订 2026-10-10）
REPORT_TIMEOUT = 15.0        # 单接口等待页内 report（静默轮内再按 deadline 收窄）
SILENT_RETRY_WAIT = 3.0      # 导航登录页后等 SPA 静默续登（仅交互路径）
#: L2 提交后轮询 fetch 预算（45→90，2026-10-10 16:46 实证：passport 提交后
#: SSO 握手 + SPA 重定向链常 >45s，预算内全泊航直接烧光、误触 L3）
AUTOFILL_BUDGET = 90.0
MANUAL_BUDGET = 600.0        # L3 人工登录预算（10min）
POLL_INTERVAL = 3.0
DETAIL_MAX = 200             # 响应 detail ≤200 字符安全摘要
#: Bug I-1 修订：静默 poll 全程硬 deadline（必回，绝不给 45s 看门狗把柄）。
#: 13→20（2026-10-10 16:46:23/37 实证：console 重载后首轮页面极重，13s 内
#: fetch 回不来 → 每次重启白烧一轮交互周期）；20s + 回包开销仍 ≪ 45s。
POLL_DEADLINE = 20.0
INTERACTIVE_ROUND_BUDGET = 12.0   # 交互路径单轮 fetch 预算（L3 弹窗须在 ~20s 内现身）
RELOAD_SETTLE_BUDGET = 10.0  # console 首页重载 settle 预算（协议 §6 修订）
ABOUT_BLANK = "about:blank"  # 落不了 console 时的最终稳定停泊页（§6 红线）
L3_RECHECK_SECONDS = 20.0    # L3 人工等待期间 fetch 最小间隔（禁 fetch 风暴）
L2_RECHECK_SECONDS = 10.0    # L2 提交后 fetch 最小间隔
TAB_SETTLE_SECONDS = 0.8     # 点击账密 tab 后等待渲染
AUTOFILL_INPUTS_BUDGET = 8.0 # passport 顶层页三要素（用户/密码/提交）可见等待预算
AUTOFILL_INPUTS_POLL = 0.5   # 三要素可见性轮询间隔
PARK_LOG_INTERVAL = 60.0     # await 泊航登录 host 的 INFO 节流（至多一次/60s）
#: 提交后诊断探针（2026-10-10 16:46 实证：submit 后零可观测——错密码/风控静默
#: 拦截/returnUrl 过期三种失败形态无法区分）。点击提交后等待 ≤ 该预算再做一次
#: 只读探针；硬上限 5s（min 保护）。探针结果经 autofill 返回值上抛，
#: 驱动 L2 fast-escalate 判定（inconclusive/err 不再烧满 AUTOFILL_BUDGET）。
SUBMIT_VERIFY_WAIT = 3.0
SUBMIT_VERIFY_WAIT_MAX = 5.0
#: L2 fast-escalate 宽限窗（2026-10-10 17:25 实证：风控静默拦截下 submit 被
#: 吞、程序化不可信事件——等满 90s 泊航轮纯属白烧，早该升级 L3）。非 cleared/
#: 非"握手在途"形态先宽限 L2_FAST_GRACE_SECONDS，仅在 ~5s/~10s 做两次廉价
#: URL 重探：捞到"慢 redirect 离开登录 host"=真在握手 → 回正常全量 await；
#: 仍泊登录 host → 直接 L3（弹窗人工），不再消耗 AUTOFILL park 预算。
L2_FAST_GRACE_SECONDS = 10.0
L2_FAST_GRACE_PROBE_INTERVAL = 5.0
GOTO_TIMEOUT = 5.0           # load_url 单次调用护栏（UI Invoke 可能卡死）
POPUP_STEP_TIMEOUT = 3.0     # L3 弹窗脉冲单步（restore/show/on_top）护栏
#: L3 人工等待期间的窗口标题提示（关闭≠成功，见 _notify_login_window_closed）
MANUAL_LOGIN_TITLE = "阿里云登录窗口 — 登录成功后会自动隐藏，请不要关闭！"

# ---------------------------------------------------------------- 流与日志


def _out_stream():
    return sys.stdout if sys.stdout is not None else open(os.devnull, "w",
                                                           encoding="utf-8")


def _err_stream():
    return sys.stderr if sys.stderr is not None else open(os.devnull, "w",
                                                           encoding="utf-8")


_out_lock = threading.Lock()


def emit(obj, stream=None) -> None:
    """行分隔 JSON 写出（UTF-8，无 pretty print）；stdout 为 None 时静默。"""
    try:
        txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        txt = json.dumps({"event": "bye"}, separators=(",", ":"))
    s = stream if stream is not None else _out_stream()
    try:
        with _out_lock:
            s.write(txt + "\n")
            s.flush()
    except UnicodeEncodeError:
        try:
            with _out_lock:
                s.write(json.dumps(obj, separators=(",", ":")) + "\n")
                s.flush()
        except Exception:                                # noqa: BLE001
            pass
    except Exception:                                    # noqa: BLE001
        pass


def use_utf8_stdio() -> None:
    """管道下 Windows 默认 GBK；协议 §1 要求 UTF-8 行——尽力重配置。"""
    for name in ("stdin", "stdout"):
        s = getattr(sys, name, None)
        if s is not None and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:                            # noqa: BLE001
                pass


def log(level: str, msg: str) -> None:
    """stderr 日志：``[helper] ts level msg``；严禁含 cookie 值/账密明文。"""
    try:
        _err_stream().write(f"[helper] {time.strftime('%Y-%m-%dT%H:%M:%S')} "
                            f"{level} {msg}\n")
    except Exception:                                   # noqa: BLE001
        pass


# ---------------------------------------------------------------- 纯函数：命令

class CommandError(ValueError):
    """stdin 行不是合法命令对象。"""


def parse_command(line: str) -> dict | None:
    """解析一行 JSONL 命令；空行 → None；非法 → CommandError。"""
    s = (line or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except ValueError:
        raise CommandError("line is not valid JSON") from None
    if not isinstance(obj, dict):
        raise CommandError("command must be a JSON object")
    cmd = obj.get("cmd")
    if not isinstance(cmd, str) or not cmd:
        raise CommandError("missing cmd field")
    return obj


def error_response(cmd_id, code: str, detail: str = "") -> dict:
    return {"id": cmd_id, "ok": False, "state": "error", "error": code,
            "detail": safe_detail(detail)}


def safe_detail(text) -> str:
    """≤200 字符安全摘要（协议 §3）。调用方保证传入内容无明文凭证。"""
    return (re.sub(r"\s+", " ", str(text)).strip())[:DETAIL_MAX]


# ---------------------------------------------------------------- 纯函数：请求构造

def build_request(api: str, sec_token: str = "", data_extra: dict | None = None,
                  trace_id: str | None = None, x_anon_id: str = ""):
    """逐字段复刻 bailian_gateway.gateway_post 的表单体/URL 构造（协议 §5）。

    返回 (url, body)。cornerstone 同构；feTraceId = "helper|" + 随机；
    sec_token 为空则裸发（v11 实证可行）；X-Anonymous-Id 仅在取到 cna 时附带
    （与 gateway 的 cna 分支同构，helper 无 cookie 串、通常为空）。
    """
    if trace_id is None:
        trace_id = f"{uuid.uuid4().hex}"
    cornerstone = {
        "feTraceId": f"helper|{trace_id}",
        "feURL": gw.DASHBOARD_URL,
        "protocol": "V2",
        "console": "ONE_CONSOLE",
        "productCode": "p_efm",
        "switchUserType": 3,
        "domain": gw.DASHBOARD_ORIGIN.split("://", 1)[1],
        "consoleSite": "BAILIAN_ALIYUN",
        "userNickName": "",
        "userPrincipalName": "",
        "xsp_lang": "zh-CN",
    }
    if x_anon_id:
        cornerstone["X-Anonymous-Id"] = x_anon_id
    data = {"commodityCode": gw.COMMODITY, **(data_extra or {}),
            "cornerstoneParam": cornerstone}
    params = {"Api": api, "V": "1.0", "Data": data}
    body: dict = {
        "product": gw.PRODUCT, "action": gw.ACTION, "region": gw.REGION,
        "language": "zh-CN",
        "params": json.dumps(params, ensure_ascii=False,
                             separators=(",", ":")),
    }
    if sec_token:
        body["sec_token"] = sec_token
    url = (f"{gw.QUOTA_ORIGIN}/data/api.json?" + urllib.parse.urlencode(
        {"action": gw.ACTION, "product": gw.PRODUCT, "api": api,
         "_v": "undefined"}))
    return url, body


def build_fetch_js(kind: str, url: str, body: dict) -> str:
    """页内 fetch（credentials:'include'），原始信封文本经 api.report 回传（§5）。"""
    body_str = urllib.parse.urlencode(body)
    return """
(async () => {
  try {
    const r = await fetch(%s, {method:'POST', credentials:'include',
      headers:{'Content-Type':'application/x-www-form-urlencoded',
               'X-Requested-With':'XMLHttpRequest'},
      body: %s});
    const t = await r.text();
    window.pywebview.api.report(%s, JSON.stringify({status:r.status, text:t}));
  } catch(e) {
    window.pywebview.api.report(%s, JSON.stringify({fetch_err:String(e)}));
  }
})()
""" % (json.dumps(url), json.dumps(body_str), json.dumps(kind),
       json.dumps(kind))


INFO_JS_TEMPLATE = """
(async () => {
  try {
    const r = await fetch('/tool/user/info.json', {credentials:'include'});
    const t = await r.text();
    window.pywebview.api.report(%s, t);
  } catch(e) { window.pywebview.api.report(%s, JSON.stringify({fetch_err:String(e)})); }
})()
"""


def build_info_js(key: str = "info") -> str:
    """user/info.json 页内 fetch；key 为轮次唯一 report 键（防僵尸轮迟到串号）。"""
    return INFO_JS_TEMPLATE % (json.dumps(key), json.dumps(key))

SEC_TOKEN_JS = ("(window.ALIYUN_CONSOLE_CONFIG && "
                "window.ALIYUN_CONSOLE_CONFIG.SEC_TOKEN) || ''")


def parse_report(data) -> dict:
    """js report 的 payload → {status, text, err}。"""
    if data is None:
        return {"status": None, "text": None, "err": "no report"}
    if isinstance(data, dict):
        d = data
    elif isinstance(data, str):
        try:
            d = json.loads(data)
        except ValueError:
            return {"status": None, "text": data, "err": None}
    else:
        return {"status": None, "text": None, "err": "bad payload"}
    if not isinstance(d, dict):
        return {"status": None, "text": None, "err": "bad payload"}
    if d.get("fetch_err"):
        return {"status": None, "text": None, "err": str(d["fetch_err"])[:120]}
    return {"status": d.get("status"), "text": d.get("text"), "err": None}


# ---------------------------------------------------------------- 纯函数：登录态判定

def classify_envelope(text) -> str:
    """协议 §5 子串判定（不区分大小写）；NotLogined/needlogin 优先于 SUCCESS。

    已知局限：纯 HTTP 码信封含 \"NotLogined\" 子串才判登出；信封里 `"success":false`
    这类业务失败仍归 live（登录态无恙），业务错误由 widget 侧 gateway 函数解析。
    """
    if text is None:
        return "error"
    low = str(text).lower()
    if not low:
        return "error"
    if "notlogined" in low or "needlogin" in low:
        return "need_login"
    if "success" in low:
        return "live"
    return "other"


def round_state(texts: dict) -> str:
    """一轮 fetch 后的整体判定：live | need_login | error | other。"""
    states = {k: classify_envelope(texts.get(k)) for k in KINDS}
    if any(states[k] == "need_login" for k in LOGIN_GATE_KINDS):
        return "need_login"
    if any(states[k] == "live" for k in LOGIN_GATE_KINDS):
        return "live"
    if all(states[k] == "error" for k in LOGIN_GATE_KINDS):
        return "error"
    return "other"


def extract_sec_token(info_text) -> str:
    """user/info.json 文本里找 sec_token/secToken（协议 §5 尽力而为，允许空）。"""
    m = re.search(r'"sec[_tT]?[tT]oken"\s*:\s*"([^"]+)"', str(info_text or ""))
    return m.group(1) if m else ""


def envelope_payload(text):
    """信封文本 → 内层业务 JSON（字符串或解析后的 dict）；失败回原文。"""
    if text is None:
        return None
    try:
        env = gw.expand_json_strings(json.loads(text))
    except ValueError:
        return text
    return env.get("data", env) if isinstance(env, dict) else env


# ---------------------------------------------------------------- 单实例锁

class AlreadyLocked(Exception):
    """webview_profile 已被其他活体 helper 锁定（协议 §7 → HELPER_ERROR）。"""


LOCK_NAME = "helper.lock"
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED = 0x1000


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":                                   # pragma: no cover
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        kernel32 = ctypes.windll.kernel32
    except AttributeError:
        return True                                       # 判不了就当活，保守
    h = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == _STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(h)


def acquire_instance_lock(profile_dir: Path):
    """O_EXCL + PID 锁文件；PID 已死 → 陈旧锁接管。返回 (fd, path)。"""
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / LOCK_NAME
    for attempt in (1, 2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            return fd, path
        except FileExistsError:
            if attempt == 1 and _lock_stale(path):
                log("WARN", f"takeover stale lock {path.name}")
                try:
                    os.unlink(str(path))
                except FileNotFoundError:
                    pass
                continue
            raise AlreadyLocked(_lock_pid(path)) from None
    raise AlreadyLocked(None)                              # pragma: no cover


def _lock_pid(path: Path):
    try:
        txt = Path(path).read_text(encoding="ascii", errors="replace").strip()
        return int(txt.split()[0]) if txt else None
    except (OSError, ValueError, IndexError):
        return None


def _lock_stale(path: Path) -> bool:
    pid = _lock_pid(path)
    return pid is None or not pid_alive(pid)


def release_instance_lock(fd, path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(str(path))
    except OSError:
        pass


# ---------------------------------------------------------------- autofill 选择器逻辑

#: 可见性探针：元素存在 **且** 可见才算命中（passport 页的 #fm-login-checkcode
#: 常态隐藏于 DOM，只按存在性判定会把风控态误当可填充）。
_VISIBLE_PROBE_JS = """
(function (sel) {
  try {
    var el = document.querySelector(sel);
    return !!(el && (el.offsetParent !== null ||
      (el.getClientRects && el.getClientRects().length)));
  } catch (e) { return false; }
})("""

#: tab 步骤 JS：在 LOGIN_SELECTORS["tab"] 候选里找文案匹配 LOGIN_TAB_TEXTS、
#: 可见且**尚未 active** 的元素点击一次；已 active / 找不到 → no-op 返回 false。
_TAB_CLICK_JS = """
(function (sels, texts) {
  var nodes = [];
  for (var i = 0; i < sels.length; i++) {
    try {
      nodes = nodes.concat([].slice.call(document.querySelectorAll(sels[i])));
    } catch (e) {}
  }
  for (var j = 0; j < nodes.length; j++) {
    var el = nodes[j];
    var t = (el.textContent || '').trim();
    if (!t || t.length > 12) continue;
    var want = false;
    for (var k = 0; k < texts.length; k++)
      if (t.indexOf(texts[k]) >= 0) { want = true; break; }
    if (!want) continue;
    if (String(el.className || '').indexOf('active') >= 0) continue;
    var vis = el.offsetParent !== null ||
      (el.getClientRects && el.getClientRects().length);
    if (!vis) continue;
    try { el.click(); return true; } catch (e) {}
  }
  return false;
})"""

#: 填充 + 回读校验（native value setter 触发框架受控更新；任一失败返回非 'OK'，
#: 调用方绝不提交）。账密明文只出现在此 evaluate_js 载荷内（协议 §7 红线）。
_FILL_VERIFY_JS = """
(function (uSel, uVal, pSel, pVal) {
  function setVal(sel, v) {
    var el = document.querySelector(sel);
    if (!el) return false;
    var proto = el.ownerDocument.defaultView.HTMLInputElement.prototype;
    var d = Object.getOwnPropertyDescriptor(proto, 'value');
    if (d && d.set) { d.set.call(el, v); } else { el.value = v; }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return el.value === v;
  }
  return (setVal(uSel, uVal) && setVal(pSel, pVal)) ? 'OK' : 'FAIL';
})"""

#: 提交后只读诊断探针（READ-ONLY：不点击、不改值、不 fetch、不读任何输入**值**
#: 进返回值——inputs 只回"是否已清空"的布尔）。三项信号区分失败形态：
#:   inputs_cleared=true            → 提交已被页面接受（等待重定向/SSO 链）
#:   inputs_cleared=false + err_text非空 → 错密码/账号错误等**可见**报错
#:   inputs_cleared=false + 仍泊 pwd 页 + err_text 空 → 风控静默拦截（无反馈）
#:   url 已离开 passport 域          → 提交成功、重定向链在途
#: 输入"值是否非空"按 LOGIN_SELECTORS 的 username/password 候选选择器逐一检查。
_SUBMIT_VERIFY_JS = """
(function () {
  function visible(el) {
    if (!el) return false;
    try {
      return el.offsetParent !== null ||
        (el.getClientRects && el.getClientRects().length);
    } catch (e) { return false; }
  }
  var out = {inputs_cleared: true, url: '', err_text: ''};
  try { out.url = String(location.href || ''); } catch (e) {}
  var keep = %s;
  for (var i = 0; i < keep.length; i++) {
    try {
      var el = document.querySelector(keep[i]);
      if (el && visible(el) && String(el.value || '') !== '') {
        out.inputs_cleared = false; break;
      }
    } catch (e) {}
  }
  var tips = %s;
  for (var j = 0; j < tips.length; j++) {
    var nodes = [];
    try { nodes = [].slice.call(document.querySelectorAll(tips[j])); }
    catch (e) {}
    for (var k = 0; k < nodes.length; k++) {
      if (!visible(nodes[k])) continue;
      var t = (nodes[k].textContent || '').trim();
      if (t) { out.err_text = t.slice(0, 120); j = tips.length; break; }
    }
  }
  return JSON.stringify(out);
})()"""

#: err_text 抓取选择器候选序：先专有报错类（fm-tips/password-login .error，
#: 命中最精确），再泛化 [class*=err]/[class*=tip]（DOM 改版兜底）。
SUBMIT_VERIFY_TIP_SELECTORS = [".fm-tips", ".password-login .error",
                               "[class*=\"err\"]", "[class*=\"tip\"]"]


def _scrub_url_for_log(url: str) -> str:
    """剥 query/fragment（重定向链可能携带一次性 token），≤120 字符。"""
    try:
        sp = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((sp.scheme, sp.netloc, sp.path, "",
                                        ""))[:120]
    except Exception:                                    # noqa: BLE001
        return str(url)[:120]


def _parse_probe_payload(value):
    """提交后探针返回值 → dict 或 None。

    真桥 return 形态不可控（17:11 实证：fake-bridge 太宽容、真桥下 "bad probe
    payload" 丢了 err_text 诊断）：dict 原样、JSON 字符串一次 loads、双重编码
    字符串两次 loads；其余一律 None（调用方走 raw 兜底日志）。"""
    v = value
    for _ in range(3):
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return None
        else:
            return None
    return v if isinstance(v, dict) else None


def _scrub_probe_raw(value, username: str = "") -> str:
    """不可解析返回值 → 可日志形态：URL 剥 query、空白折叠、用户名脱敏、≤200。"""
    t = re.sub(r"https?://\S+", lambda m: _scrub_url_for_log(m.group(0)),
               str(value))
    t = re.sub(r"\s+", " ", t).strip()
    if username and username in t:
        t = t.replace(username, "<user>")                # §7 明文纪律
    return t[:200]


def _submit_verify(window, username: str = "",
                   wait: float = SUBMIT_VERIFY_WAIT) -> str:
    """autofill 提交后的只读诊断（绝不含账密明文——输入值只以"已清空"布尔返回，
    err_text/raw 里若碰巧含用户名则脱敏）。全程吞异常：诊断失败不影响瀑布主流程。

    返回 verify 分类（17:25 实证：静默拦截下等满 90s 纯属白烧 → 驱动 fast-escalate）：
    'cleared'       —— inputs_cleared=true：submit 被接受、握手在途，等待有回报；
    'err'           —— 可见报错（错密码等），继续等待无意义；
    'inconclusive'  —— 未清栏且无报错（含探针异常/不可解析——无法证实被接受），
                       疑似风控静默拦截（INFO 日志仍只在精确签名
                       "未清栏+泊 passport+无报错"时打，异常路径只分类不冒认）。"""
    delay = min(float(wait), SUBMIT_VERIFY_WAIT_MAX)
    if delay > 0:
        time.sleep(delay)
    try:
        raw = window.evaluate_js(
            _SUBMIT_VERIFY_JS % (
                json.dumps(LOGIN_SELECTORS["username"]
                           + LOGIN_SELECTORS["password"], ensure_ascii=False),
                json.dumps(SUBMIT_VERIFY_TIP_SELECTORS, ensure_ascii=False)))
    except Exception as e:                                # noqa: BLE001
        log("WARN", f"submit-verify: probe failed: {type(e).__name__}")
        return "inconclusive"
    parsed = _parse_probe_payload(raw)
    if parsed is None:
        # 真桥 return 契约彻底对不上：至少把原始值（脱敏截断）留在日志里，
        # 不再只报无信息量的 "bad probe payload"。
        log("WARN", f"submit-verify: raw={_scrub_probe_raw(raw, username)}")
        return "inconclusive"
    cleared = bool(parsed.get("inputs_cleared"))
    url = _scrub_url_for_log(str(parsed.get("url") or ""))
    err = str(parsed.get("err_text") or "")[:120]
    if username and username in err:
        err = err.replace(username, "<user>")            # §7 明文纪律兜底
    rec = json.dumps({"inputs_cleared": cleared, "url": url, "err_text": err},
                     ensure_ascii=False, separators=(",", ":"))
    log("INFO", f"submit-verify: {rec}")
    if cleared:
        return "cleared"
    if err:
        return "err"
    if _url_host(url) == PWD_LOGIN_HOST:
        log("INFO", "submit-verify: inconclusive "
                     "(likely risk-control silent block)")
    return "inconclusive"


def selector_visible(window, sel: str) -> bool:
    """元素存在且可见（offsetParent/getClientRects）；JS 异常 → False。"""
    try:
        return bool(window.evaluate_js(
            _VISIBLE_PROBE_JS + json.dumps(sel) + ")"))
    except Exception:                                   # noqa: BLE001
        return False


def first_visible(window, key: str):
    """按 LOGIN_SELECTORS[key] 候选序找首个**可见**选择器；全无 → None。"""
    for sel in LOGIN_SELECTORS.get(key, []):
        if selector_visible(window, sel):
            return sel
    return None


def _click_password_tab(window) -> bool:
    """可选步骤：account 页切到"账密登录"tab（已 active 或 passport 页 → no-op）。
    返回 True 仅表示**点击了**非 active 的 tab（需要等待渲染）。"""
    try:
        return bool(window.evaluate_js(
            _TAB_CLICK_JS + "(%s, %s)" % (
                json.dumps(LOGIN_SELECTORS.get("tab", []), ensure_ascii=False),
                json.dumps(list(LOGIN_TAB_TEXTS), ensure_ascii=False))))
    except Exception:                                   # noqa: BLE001
        return False


def autofill_login(window, username: str, password: str,
                   inputs_budget: float | None = None,
                   verify_wait: float | None = None) -> dict:
    """L2 账密自动填充（协议 §6 修订 2026-10-10：在 PWD_LOGIN_URL 顶层页执行）。

    有序步骤：①确保账密 tab（可选）→ ②等三要素可见（≤inputs_budget）→
    ③验证码门控（风控出现即弃权）→ ④填充用户/密码并回读校验 → ⑤全部就绪
    才点击提交 → ⑥提交后 ≤5s 只读诊断探针（submit-verify），探针分类经
    返回值上抛（17:25 实证修订：不再"仅日志"——静默拦截形态必须驱动
    _interactive_login 的 fast-escalate，免烧 90s park 预算）。

    返回 ``{"submitted": bool, "verify": str}``：
    submitted=False（任一前置步失败/异常，**绝不发出含凭据的脚本、绝不含
    提交动作**）→ verify='prefail'；submitted=True → verify ∈
    'cleared'|'err'|'inconclusive'（见 _submit_verify）。
    账密明文只进第④步 evaluate_js 载荷。
    """
    budget = AUTOFILL_INPUTS_BUDGET if inputs_budget is None else float(inputs_budget)
    vwait = SUBMIT_VERIFY_WAIT if verify_wait is None else float(verify_wait)
    prefail = {"submitted": False, "verify": "prefail"}
    try:
        # 1) tab（点动了才等待渲染；passport 顶层页无 tab，no-op 不阻塞）
        if _click_password_tab(window):
            time.sleep(TAB_SETTLE_SECONDS)
        # 2) 三要素可见性等待（passport 页 SPA 渲染可能晚于 ready 事件）
        deadline = time.monotonic() + budget
        u_sel = p_sel = s_sel = None
        while True:
            u_sel = first_visible(window, "username")
            p_sel = first_visible(window, "password")
            s_sel = first_visible(window, "submit")
            if u_sel and p_sel and s_sel:
                break
            if time.monotonic() >= deadline:
                log("INFO", "autofill: selectors missing -> L3")
                return prefail
            time.sleep(AUTOFILL_INPUTS_POLL)
        # 3) 验证码门控：图片验证码可见 = 风控场景，自动填充必败 → 交人工
        if any(selector_visible(window, sel)
               for sel in LOGIN_SELECTORS.get("checkcode", [])):
            log("INFO", "autofill: captcha visible -> L3")
            return prefail
        # 4) 填充 + 回读校验（任一失败绝不提交）
        ok = window.evaluate_js(
            _FILL_VERIFY_JS + "(%s, %s, %s, %s)" % (
                json.dumps(u_sel), json.dumps(username),
                json.dumps(p_sel), json.dumps(password)))
        if ok != "OK":
            log("WARN", "autofill: value verification failed -> L3")
            return prefail
        # 5) 提交（唯一可达的 click(submit) 点；表单自带风控/滑块时由页面接管）
        log("INFO", f"autofill: submitting via {s_sel}")
        window.evaluate_js(
            "try { var b = document.querySelector(%s); if (b) b.click(); } "
            "catch(e) {}" % json.dumps(s_sel))
        # 6) 提交后诊断（只读探针，≤5s；绝不回传输入值——失败形态靠分类区分，
        #    经返回值驱动 fast-escalate）
        return {"submitted": True,
                "verify": _submit_verify(window, username, wait=vwait)}
    except Exception as e:                              # noqa: BLE001
        log("ERROR", f"autofill failed: {type(e).__name__}")
        return prefail


def _normalize_autofill_result(raw) -> dict:
    """autofill_login 返回值归一：旧 bool 形态（测试替身/历史兼容）——
    True 视为 'cleared'（维持全量 await 旧行为）、False 视为 prefail；
    dict 形态直通（verify 缺失时按 submitted 兜底）。"""
    if isinstance(raw, dict):
        submitted = bool(raw.get("submitted"))
        verify = str(raw.get("verify") or
                     ("inconclusive" if submitted else "prefail"))
        return {"submitted": submitted, "verify": verify}
    ok = bool(raw)
    return {"submitted": ok, "verify": "cleared" if ok else "prefail"}


# ---------------------------------------------------------------- L2 提升：新鲜 entrance

#: 只读抓取 account 登录页上账密 iframe 的**实时** src（17:11 实证修订主路径）：
#: #alibaba-login-box 优先，泛化 iframe 兜底（src 含 havanaone 才算账密 entrance）。
#: 单表达式 IIFE，返回字符串；不点击、不改值、不 fetch——纯读取。
_ENTRANCE_SCRAPE_JS = """
(() => {
  try {
    const box = document.querySelector('#alibaba-login-box');
    if (box && box.src) return String(box.src);
  } catch (e) {}
  try {
    for (const f of document.querySelectorAll('iframe')) {
      const s = f.src || f.getAttribute('src') || '';
      if (s.indexOf('passport.aliyun.com/havanaone') >= 0) return s;
    }
  } catch (e) {}
  return '';
})()"""


def _scrape_pwd_entrance(window) -> str:
    """抓取实时 entrance URL；异常/空/非字符串/非 passport https 一律 → ''
    （调用方走静态兜底）。"""
    try:
        src = window.evaluate_js(_ENTRANCE_SCRAPE_JS)
    except Exception as e:                                # noqa: BLE001
        log("WARN", f"L2: entrance scrape raised: {type(e).__name__}")
        return ""
    if not isinstance(src, str) or not src.strip():
        return ""
    src = src.strip()
    if not src.lower().startswith("https://") or _url_host(src) != PWD_LOGIN_HOST:
        log("WARN", f"L2: scraped entrance rejected "
                    f"(host={_url_host(src) or '-'})")
        return ""
    return src


def _promote_to_pwd_entrance(window) -> None:
    """L2 提升（17:11 实证修订）：静态 PWD_LOGIN_URL 的 returnUrl/rnd 是探针
    时刻的快照——过期后提交被页面吃掉、重定向链死胡同，窗口泊在 passport 烧光
    AUTOFILL_BUDGET。改为：account 登录页 → 等 ready → 只读抓取 #alibaba-login-box
    实时 src → 顶层导航（新鲜 returnUrl/rnd）；抓取失败才兜底静态 URL。
    已在 passport 顶层页则 no-op（不打断在途填充/重定向）。"""
    if _url_host(_url_for_log(window)) == PWD_LOGIN_HOST:
        return
    log("INFO", "L2: promote passport pwd entrance to top-level")
    _goto(window, LOGIN_URL)
    _wait_page_ready(window, RELOAD_SETTLE_BUDGET)
    src = _scrape_pwd_entrance(window)
    if src:
        log("INFO", "L2: fresh entrance from iframe")
        _goto(window, src)
    else:
        log("INFO", "L2: iframe src unavailable, static entrance fallback")
        _goto(window, PWD_LOGIN_URL)
    _wait_page_ready(window, RELOAD_SETTLE_BUDGET)


def load_login_creds():
    """CM 账密（车道 A 契约）；缺模块/缺函数/读取失败 → None。"""
    if _auth is None or not hasattr(_auth, "load_bailian_login"):
        log("WARN", "auth lane missing load_bailian_login")
        return None
    try:
        return _auth.load_bailian_login()
    except Exception:                                   # noqa: BLE001
        log("WARN", "load_bailian_login failed")
        return None


def store_login_creds(username, password) -> dict:
    """save_creds 命令处理（协议 §6.3）：明文只走 stdin 管道。"""
    if _auth is None or not hasattr(_auth, "save_bailian_login"):
        return error_response(None, "HELPER_ERROR",
                              "auth lane missing save_bailian_login")
    if not isinstance(username, str) or not isinstance(password, str) \
            or not username or not password:
        return error_response(None, "HELPER_ERROR", "invalid creds payload")
    try:
        _auth.save_bailian_login(username, password)
    except ValueError as e:
        # 只取异常类型做摘要：CM blob 512B 上限等 detail 可能带敏感上下文
        return error_response(None, "HELPER_ERROR",
                              f"rejected: {type(e).__name__}")
    except Exception as e:                              # noqa: BLE001
        return error_response(None, "HELPER_ERROR", f"save failed: {type(e).__name__}")
    return {"ok": True}


# ---------------------------------------------------------------- 运行时：Api（js_api）


class Api:
    """暴露给页内 JS 的回调面：window.pywebview.api.report(kind, data)。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._reports: dict = {}

    def report(self, kind, data):
        with self._lock:
            self._reports[str(kind)] = (time.time(), data)

    def take(self, kind: str):
        with self._lock:
            rec = self._reports.get(kind)
        return rec[1] if rec else None

    def wait_report(self, kind: str, timeout: float = REPORT_TIMEOUT):
        """轮询等待某 kind 的最新 report；返回原始 data 或 None。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.take(kind)
            if data is not None:
                return data
            time.sleep(0.2)
        return self.take(kind)


# ---------------------------------------------------------------- 运行时：fetch 轮

def _round_timeout(wait: float, deadline: float | None) -> float:
    """有整轮 deadline 时把单接口等待收窄到剩余预算内。"""
    if deadline is None:
        return wait
    return max(0.05, min(wait, deadline - time.monotonic()))


def get_sec_token(window, api: Api, seq: int = 0,
                  deadline: float | None = None) -> str:
    """三级尽力而为（协议 §5）：ALIYUN_CONSOLE_CONFIG → user/info.json → 空。

    任何 evaluate_js 异常（毒化窗口 WebViewException 等）静默降级为空 token，
    绝不让取 token 炸穿命令线程。"""
    try:
        tok = window.evaluate_js(SEC_TOKEN_JS)
        if isinstance(tok, str) and tok.strip():
            return tok.strip()
    except Exception:                                   # noqa: BLE001
        return ""
    try:
        key = f"info@{seq}" if seq else "info"
        window.evaluate_js(build_info_js(key))
        data = api.wait_report(key, timeout=_round_timeout(8.0, deadline))
        if data is not None:
            tok = extract_sec_token(data if isinstance(data, str)
                                     else json.dumps(data))
            if tok:
                return tok
    except Exception:                                   # noqa: BLE001
        pass
    return ""


def _fetch_kind(window, api: Api, kind: str, sec_token: str,
                report_key: str | None = None,
                deadline: float | None = None):
    key = report_key or kind
    url, body = build_request(API_ENDPOINTS[kind][0], sec_token,
                              API_ENDPOINTS[kind][1])
    try:
        window.evaluate_js(build_fetch_js(key, url, body))
    except Exception as e:                              # noqa: BLE001
        # 协议 §6 修订：evaluate_js 异常（Main window failed to start 等）
        # 必须捕获并标记该轮失败——调用方立即回 error，绝不吞响应。
        log("WARN", f"evaluate_js '{kind}' failed: {type(e).__name__}")
        return {"status": None, "text": None, "err": "evaluate_js failed",
                "eval_failed": True}
    return parse_report(api.wait_report(
        key, timeout=_round_timeout(REPORT_TIMEOUT, deadline)))


def fetch_all(window, api: Api, sec_token: str, seq: int = 0,
              deadline: float | None = None):
    """串行四接口。信封报 Workspace.NotAuthorised 且尚无 sec_token → 补取一次
    再试（协议 §5）。返回 ({kind: {"status","text","err"[,"eval_failed"]}},
    sec_token)。deadline 耗尽 → 余下接口直接记 eval_failed（error 轮）。"""
    out: dict = {}
    for kind in KINDS:
        if deadline is not None and time.monotonic() >= deadline:
            out[kind] = {"status": None, "text": None, "err": "round deadline",
                         "eval_failed": True}
            continue
        res = _fetch_kind(window, api, kind, sec_token,
                          report_key=f"{kind}@{seq}" if seq else kind,
                          deadline=deadline)
        text = (res.get("text") or "").lower()
        if "notauthoris" in text and not sec_token:
            sec_token = get_sec_token(window, api, seq=seq, deadline=deadline)
            if sec_token:
                log("INFO", f"{kind}: NotAuthorised -> sec_token acquired, retry")
                res = _fetch_kind(window, api, kind, sec_token,
                                  report_key=f"{kind}@{seq}.r" if seq else kind,
                                  deadline=deadline)
        out[kind] = res
    return out, sec_token


def round_texts(results: dict) -> dict:
    return {k: (v.get("text") if v.get("err") is None else None)
            for k, v in results.items()}


def build_poll_data(results: dict | None) -> dict:
    """响应 data：网关原始信封文本（JSON 字符串），addon 可为 null（协议 §3）。"""
    out: dict = {}
    for k in KINDS:
        r = (results or {}).get(k) or {}
        out[k] = r.get("text") if r.get("err") is None else None
    return out


def poll_once(window, api: Api, sec_box: list, seq: int = 0,
              deadline: float | None = None):
    """一次静默 fetch 轮（sec_token 跨轮复用）。返回 (rs, results)。"""
    if not sec_box:
        sec_box.append("")
    results, sec_box[0] = fetch_all(window, api, sec_box[0], seq=seq,
                                     deadline=deadline)
    return round_state(round_texts(results)), results


def _sleep_until(stop, deadline=None, interval=POLL_INTERVAL) -> bool:
    """分段 sleep；返回 False 表示 stop 置位（提前结束）。"""
    while True:
        if stop.is_set():
            return False
        if deadline is not None and time.monotonic() >= deadline:
            return True
        time.sleep(interval)


def _call_with_timeout(fn, timeout: float, label: str = "") -> bool:
    """UI 调用护栏：在独立 daemon 线程跑 fn，最多等 timeout 秒。

    Lane I 实证（14:13）：pywebview WinForms 的同步 Invoke / TopMost 赋值在
    WebView2 UI 线程忙时可能**无限**卡死——若直接跑在命令线程上会吞掉
    login_required/bye/响应，最终被看门狗杀进程。卡死即弃线程，绝不拖垮主流程。"""
    done = threading.Event()
    box: dict = {}

    def run():
        try:
            fn()
        except Exception as e:                          # noqa: BLE001
            box["exc"] = type(e).__name__
        finally:
            done.set()

    threading.Thread(target=run, daemon=True, name=f"ui-{label or 'call'}").start()
    if not done.wait(max(0.05, float(timeout))):
        log("WARN", f"ui call '{label}' blocked >{timeout:.1f}s -> abandoned")
        return False
    if "exc" in box:
        log("WARN", f"ui call '{label}' failed: {box['exc']}")
        return False
    return True


def _goto(window, url: str) -> bool:
    return _call_with_timeout(lambda: window.load_url(url),
                              GOTO_TIMEOUT, label="load_url")


# ------------------------------------------------- 页面稳定态探针（§6 修订 2026-10-10）
#
# pywebview 6.x：evaluate_js 由 _pywebviewready 事件门控（wait 20s 不成即抛
# WebViewException）；load_url 会 clear loaded/_pywebviewready。因此
# window.events.* 的 wait/is_set 是**不抛异常**的低成本稳定探针——窗口是否
# 还能执行 JS，问事件、不问 evaluate_js。

def _ready_event(window):
    ev = getattr(window, "events", None)
    if ev is None:
        return None
    ready = getattr(ev, "_pywebviewready", None)
    if ready is None:
        ready = getattr(ev, "loaded", None)
    return ready


def _page_ready_now(window) -> bool:
    ev = _ready_event(window)
    if ev is None:                        # 假 window / 无事件面 → 视为可用
        return True
    try:
        return bool(ev.is_set())
    except Exception:                     # noqa: BLE001
        return False


def _wait_page_ready(window, budget: float) -> bool:
    ev = _ready_event(window)
    if ev is None:
        return True
    try:
        return bool(ev.wait(max(0.0, float(budget))))
    except Exception:                     # noqa: BLE001
        return False


def _land_stable(st: dict) -> bool:
    """协议 §6 修订红线：任何导航过登录页的路径，离开前必须落回稳定页——
    console 首页（预算 10s），落不住退 about:blank。返回是否落回 console。"""
    window = st["window"]
    if not st.get("page_poisoned"):
        return True
    st["page_poisoned"] = False
    log("INFO", "landing window on stable page (console reload)")
    if _goto(window, CONSOLE_URL) and _wait_page_ready(window,
                                                        RELOAD_SETTLE_BUDGET):
        return True
    log("WARN", "console did not settle -> park about:blank")
    if _goto(window, ABOUT_BLANK):
        _wait_page_ready(window, 2.0)
    return False


# ------------------------------------------------- origin 护栏（Fix 1，2026-10-10 §7 实证）
#
# 车道 J 日志（15:07-15:10）：L3 用户完成登录后 passport 链把窗口落在
# home.console origin；页内 fetch 的目标网关只放行 bailian(.cs).console——跨源
# 一律被 CORS 拒绝，JS catch 报 fetch_err → evalfail=False、rs=error 无限循环。
# 因此 fetch 轮发起前先问一句"窗口在正确的源上吗"，不在就拉回 CONSOLE_URL 一次。

CONSOLE_ALLOWED_HOSTS = frozenset({"bailian.console.aliyun.com",
                                   "bailian-cs.console.aliyun.com"})
#: 登录页是用户正在输入的等待区（account/passport）：导航打断 = L2/L3 不可用，
#: 护栏刻意豁免这些 host（登录完成后窗口会移向 home.console，正由护栏接管）。
LOGIN_WAIT_HOSTS = frozenset({"account.aliyun.com", "passport.aliyun.com"})
ORIGIN_GUARD_COOLDOWN = 15.0   # 至多一次/15s：防与 SPA 重定向链 ping-pong


def _url_host(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:                                   # noqa: BLE001
        return ""


def _ensure_console_origin(window, st: dict) -> bool:
    """当前 host ∉ CONSOLE_ALLOWED_HOSTS（且非登录豁免区）→ _goto(CONSOLE_URL)
    一次并等 ready ≤ RELOAD_SETTLE_BUDGET；ORIGIN_GUARD_COOLDOWN 内至多一次。
    返回 True=本次调用完成了回跳导航。URL 探针不可得（无 get_current_url / UI
    停摆返回 ''）视为未知、不导航——假 window 与卡死 UI 均保持良性不变。"""
    url = _url_for_log(window)
    if not url:
        return False
    host = _url_host(url)
    if host in CONSOLE_ALLOWED_HOSTS or host in LOGIN_WAIT_HOSTS:
        return False
    cooldown = float(st.get("origin_guard_cooldown", ORIGIN_GUARD_COOLDOWN))
    last = st.get("og_last_nav")
    now = time.monotonic()
    if last is not None and now - last < cooldown:
        return False
    log("INFO", f"origin-guard: return to console from {host or url}")
    st["og_last_nav"] = now
    if _goto(window, CONSOLE_URL):
        _wait_page_ready(window, RELOAD_SETTLE_BUDGET)
        return True
    return False


def _hide_window(st: dict) -> None:
    """异步隐藏：先纯 Win32 SW_HIDE（不经 .NET 桥、不抢 UI 泵），找不到窗口
    再退回 pywebview hide()——两者都在独立线程里跑，绝不把命令线程搭进去。"""
    if st.get("hidden", True):
        return
    st["hidden"] = True
    window = st["window"]

    def _quiet():
        try:
            if not _win32_show_hide(False):
                window.hide()
        except Exception as e:                          # noqa: BLE001
            log("WARN", f"hide failed: {type(e).__name__}")

    threading.Thread(target=_quiet, daemon=True, name="helper-hide").start()


# ------------------------------------------------- 纯 Win32 弹窗链（Lane I 取证后加）
#
# pywebview 的 show/restore/hide/on_top 全部经 WinForms Invoke——WebView2 重定向
# 风暴下 UI 线程停摆时，pythonnet 调用可攥着 GIL 无限阻塞，把**整个解释器**一起
# 掐死（14:20 复现 2 实证：L3 脉冲期间栈转储线程都跑不上）。弹窗/隐藏是 OS 级
# 操作，用 ctypes ShowWindow/SetWindowPos 直达（CDLL 调用释放 GIL），.NET 桥仅作
# 兜底。

_SW_HIDE, _SW_SHOW, _SW_RESTORE = 0, 5, 9
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0040


def _win32_find_helper_windows(title: str = WINDOW_TITLE) -> list:
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    found: list = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _lparam):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title in buf.value:
                found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return found


def _win32_show_topmost(title: str = WINDOW_TITLE) -> bool:
    """restore + show + TopMost/NotTopMost 脉冲；返回是否命中窗口。"""
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    hwnds = _win32_find_helper_windows(title)
    for hwnd in hwnds:
        user32.ShowWindow(wt.HWND(hwnd), _SW_RESTORE)
        user32.ShowWindow(wt.HWND(hwnd), _SW_SHOW)
        user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-1), 0, 0, 0, 0,
                            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_SHOWWINDOW)
        user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-2), 0, 0, 0, 0,
                            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_SHOWWINDOW)
    return bool(hwnds)


def _win32_show_hide(show: bool, title: str = WINDOW_TITLE) -> bool:
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    hwnds = _win32_find_helper_windows(title)
    for hwnd in hwnds:
        user32.ShowWindow(wt.HWND(hwnd), _SW_SHOW if show else _SW_HIDE)
    return bool(hwnds)


def _popup_pulse(window, st: dict) -> None:
    """L3：restore + show + on_top 脉冲（协议 §6 修订）。主路径纯 Win32；
    未命中窗口（或 Win32 调用被卡弃线程）才降级 .NET 桥——同样每步限时。
    弹窗失败只降级为事件传达，login_required 必须照发。"""
    step = float(st.get("popup_step_budget", POPUP_STEP_TIMEOUT))
    box: dict = {}

    def _win32():
        box["found"] = _win32_show_topmost()

    if _call_with_timeout(_win32, step, label="popup_win32") and box.get("found"):
        st["hidden"] = False
        return
    log("WARN", "win32 popup miss -> .NET pulse fallback")
    for name in ("restore", "show"):
        fn = getattr(window, name, None)
        if fn is not None:
            _call_with_timeout(fn, step, label=f"popup_{name}")

    def _top_pulse():
        window.on_top = True
        window.on_top = False

    _call_with_timeout(_top_pulse, step, label="popup_on_top")
    st["hidden"] = False


# ------------------------------------------------- L3 标题语义（Fix 2a，2026-10-10）

def _set_window_title(window, title) -> bool:
    """标题读写同样经 UI 桥（可卡死）——限时护栏，失败不阻塞登录流程。"""
    if title is None:
        return False

    def apply():
        window.title = title

    return _call_with_timeout(apply, POPUP_STEP_TIMEOUT, label="set_title")


def _restore_login_title(st: dict) -> None:
    title = st.pop("orig_title", None)
    if title is not None:
        _set_window_title(st["window"], title)


def _login_done(st: dict, method: str) -> None:
    """成功出口（§6 修订）：先落稳定页 → 隐藏 → 才发 login_done 事件。"""
    _land_stable(st)
    st["login_phase"] = None
    _hide_window(st)
    emit({"event": "login_done", "method": method, "cred_saved": False})


def window_ref(st: dict):
    return st["window"]


# ---------------------------------------------------------------- 运行时：fetch 轮护栏

def _guarded_round(st: dict, budget: float):
    """在独立线程跑一轮 fetch_all，join(budget) 硬护栏（协议 §6 修订 Bug I-1）：

    - 预算耗尽 → 弃轮（僵尸线程自生自灭，report 键按轮次隔离不串号），
      立即以 ("error", None, "fetch-timeout") 让调用方回包，绝不给 45s
      看门狗杀进程的理由；
    - 轮内出现 evaluate_js 异常（毒化窗口）→ ("error", results, "fetch-timeout")。
    返回 (rs, results, detail)，rs ∈ live | need_login | other | error。"""
    budget = float(budget)
    if budget <= 0.2:
        return "error", None, "fetch-timeout"
    seq = st.get("round_seq", 0) + 1
    st["round_seq"] = seq
    window, api, sec_box = st["window"], st["api"], st["sec_box"]
    deadline = time.monotonic() + budget
    box: dict = {}

    def run():
        try:
            box["rs"], box["results"] = poll_once(window, api, sec_box,
                                                  seq=seq, deadline=deadline)
        except Exception as e:                          # noqa: BLE001
            log("ERROR", f"round {seq} crashed: {type(e).__name__}")

    t = threading.Thread(target=run, daemon=True, name=f"helper-round-{seq}")
    t.start()
    t.join(budget)
    if t.is_alive():
        log("WARN", f"round {seq} exceeded {budget:.1f}s budget -> abandoned")
        return "error", None, "fetch-timeout"
    if "rs" not in box:
        return "error", None, "fetch-timeout"
    rs, results = box["rs"], box["results"]
    if results and any((results.get(k) or {}).get("eval_failed") for k in KINDS):
        log("WARN", f"round {seq}: evaluate_js exception -> error round")
        return "error", results, "fetch-timeout"
    if rs == "error":
        return "error", results, "fetch round error"
    return rs, results, None


def _url_for_log(window) -> str:
    """仅记录用的当前 URL 探针：get_current_url 在 UI 线程停摆时同样可能卡死——
    1s 护栏 + 全吞异常，失败返回 ''，绝不把异常或阻塞透进等待循环。为 §7 明文纪律
    起见剥掉 query/fragment（重定向链可能带一次性 token），只留 scheme+host+path。"""
    fn = getattr(window, "get_current_url", None)
    if fn is None:
        return ""
    box: dict = {}

    def grab():
        box["url"] = str(fn() or "")

    if not _call_with_timeout(grab, 1.0, label="url_probe"):
        return ""
    try:
        sp = urllib.parse.urlsplit(box.get("url", ""))
        return urllib.parse.urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))[:120]
    except Exception:                                   # noqa: BLE001
        return ""


def _final_check_after_park(st: dict):
    """（2026-10-10 16:55:54 实证类：L2 预算在泊航中烧光、fallback 起步瞬间用户
    其实已登录成功——检测滞后假阴性）预算耗尽且**从未跑过 fetch 轮**（全程泊航
    登录 host）时，做最后一次判活：强制回跳 CONSOLE_URL（护栏对登录 host 豁免、
    此处刻意越过——预算已尽、打断无损失）→ 等 ready ≤RELOAD_SETTLE_BUDGET →
    单轮 fetch。live → 返回 results（成功路径），否则 None（维持 timeout 语义）。"""
    window = st["window"]
    if st["stop"].is_set():
        return None
    log("INFO", "await: final-check after park (budget expired, never fetched)")
    if _goto(window, CONSOLE_URL):
        _wait_page_ready(window, RELOAD_SETTLE_BUDGET)
    if st["stop"].is_set():
        return None
    try:
        rs, results, _d = _guarded_round(st, INTERACTIVE_ROUND_BUDGET)
    except Exception as e:                                # noqa: BLE001
        log("WARN", f"await final-check raised: {type(e).__name__}")
        return None
    log("INFO", f"await: final-check rs={rs}")
    if rs == "live":
        log("INFO", "await: final-check live after park")
        return results
    return None


def _await_live(st: dict, budget: float, recheck: float | None = None):
    """L2/L3 等待登录完成：tick 廉价 sleep-poll，fetch 每 recheck 秒至多一次
    （协议 §6 修订：人工等待期间禁 fetch 风暴）。
    返回 (rs, results, detail)，rs ∈ live | timeout | error(取消)。

    修复（2026-10-10 py-spy 实证）：旧版把 fetch 轮硬门控在 _page_ready_now 之后——
    而 load_url 会 clear _pywebviewready（见 §6 探针注释），L3 登录/重定向链期间
    该标志可能**数分钟**不置位，导致用户在弹窗完成登录后等待循环永不发起 fetch、
    一路 sleep 到 budget 耗尽（login_failed）。现改为每 recheck 无条件跑一轮
    _guarded_round：导航中的页面至多产出一轮 error（12s 预算 + 线程隔离 +
    eval_failed→error 映射），无害；每轮一行 INFO 日志补齐可观测性。

    修复（2026-10-16 helper.log 16:20 实证）：泊在登录 host（account/passport）时
    页内 fetch 目标网关必 CORS 拒绝——18 轮全是白费轮。现泊航期间**跳过 fetch 轮**，
    只按 recheck 节奏廉价重探 URL；检测发生在登录后重定向把窗口带离登录 host 之后
    （origin 护栏 + 照常 fetch 轮）。URL 探不到（''）按未知处理、照常跑轮，宁可
    多一轮 error 也不因探针失灵漏判 live。

    修复（2026-10-10 16:47/16:55 实证）：预算在**全程泊航**（从未跑过 fetch 轮）
    中耗尽 → timeout 前跑一次 `_final_check_after_park`（回跳 console + 单轮），
    捞回"登录刚好在完成瞬间越过预算线"的检测滞后假阴性。"""
    window, stop = st["window"], st["stop"]
    tick = float(st.get("poll_interval", POLL_INTERVAL))
    recheck = float(st.get("await_recheck",
                           recheck if recheck is not None
                           else L3_RECHECK_SECONDS))
    park_log_interval = float(st.get("park_log_interval", PARK_LOG_INTERVAL))
    deadline = time.monotonic() + budget
    next_fetch = 0.0
    last_results = None
    round_no = 0
    parked_skips = 0
    park_logged = None
    parked_host = None
    while True:
        if stop.is_set():
            return "error", last_results, "cancelled"
        now = time.monotonic()
        if now >= deadline:
            if round_no == 0 and parked_skips > 0:
                final = _final_check_after_park(st)
                if final is not None:
                    return "live", final, None
            return "timeout", last_results, None
        if now >= next_fetch:
            url = _url_for_log(window)                  # 仅日志/泊航判定，永不抛
            if _url_host(url) in LOGIN_WAIT_HOSTS:
                # 泊航登录页：fetch 必 CORS error → 跳过本轮，只等重定向离开
                host = _url_host(url)
                # 17:11 取证补强：泊航期间 host 变化（如 passport→account 握手页）
                # 单记一行 INFO——区分"从未离开 entrance"与"握手了但没会话"。
                if parked_host is not None and host != parked_host:
                    log("INFO", f"await: host transition {parked_host}→{host}")
                parked_host = host
                parked_skips += 1
                if park_logged is None or now - park_logged >= park_log_interval:
                    log("INFO", f"await: parked on login host, round skipped "
                                f"({host}, x{parked_skips})")
                    park_logged = now
                next_fetch = time.monotonic() + recheck
                time.sleep(tick)
                continue
            round_no += 1
            # Fix 1：登录链可能把窗口泊在 home.console（跨源 CORS 永拒）——回跳后再 fetch
            _ensure_console_origin(window, st)
            try:
                rs, results, _d = _guarded_round(
                    st, min(INTERACTIVE_ROUND_BUDGET, max(0.3, deadline - now)))
            except Exception as e:                      # noqa: BLE001
                log("WARN", f"await round {round_no} raised: {type(e).__name__}")
                rs, results = "error", None
            evalfail = bool(results) and any(
                (results.get(k) or {}).get("eval_failed") for k in KINDS)
            log("INFO", f"await round {round_no}: rs={rs} evalfail={evalfail}"
                        f" url={url or '-'}")
            next_fetch = time.monotonic() + recheck
            if rs == "live":
                return "live", results, None
            if results is not None:
                last_results = results
        time.sleep(tick)


def _finish_live(st: dict, results, method: str):
    """交互路径成功出口：先落稳定页再事件/响应（§6 修订）。"""
    st["state"] = "live"
    _login_done(st, method)
    return "live", results, None


def _l2_fast_grace(st: dict) -> str:
    """L2 fast-escalate 预检（17:25 实证：静默拦截下 submit 已被吞，等待不可能
    有回报；但探针形态无法排除"慢 redirect 在途"——先廉价宽限再升级）。
    宽限窗 L2_FAST_GRACE_SECONDS 内仅在 ~每 probe 间隔和窗尾做 URL 重探
    （不做 fetch、不导航、不碰页面）：

    'left'      → host 离开登录 host（含 ''：探针失灵按在途处理，宁可多一轮
                  error 也不误杀真握手）→ 回正常全量 await；
    'parked'    → 全程仍泊登录 host → 跳过剩余 AUTOFILL park 预算、直入 L3；
    'cancelled' → stop 置位 → 调用方走 error/cancelled 出口。"""
    window, stop = st["window"], st["stop"]
    grace = float(st.get("l2_grace_seconds", L2_FAST_GRACE_SECONDS))
    probe = float(st.get("l2_grace_probe_interval",
                         L2_FAST_GRACE_PROBE_INTERVAL))
    tick = float(st.get("poll_interval", POLL_INTERVAL))
    start = time.monotonic()
    checkpoints: list[float] = []
    t = probe
    while t < grace:
        checkpoints.append(t)
        t += probe
    checkpoints.append(grace)                     # 窗尾必探一次（默认即 ~5s/~10s）
    for off in checkpoints:
        if not _sleep_until(stop, start + off, interval=tick):
            return "cancelled"
        if _url_host(_url_for_log(window)) not in LOGIN_WAIT_HOSTS:
            return "left"
    return "parked"


# ---------------------------------------------------------------- 运行时：ensure_login

def ensure_login(st: dict, allow_popup: bool, force: bool = False):
    """协议 §6（修订 2026-10-10）瀑布。返回 (outcome, results, detail)：
    outcome ∈ live | need_login | no_credential | error。

    Bug I-1：静默 poll 绝不导航登录页（毒化窗口 → evaluate_js 每 20s 抛
    Main window failed to start → 45s 看门狗杀进程风暴）；两种路径拆离。

    `force=True`（reauth 命令，2026-10-12）：交互路径跳过「已 live → 立即回包」
    短路——用户显式要求重新登录/切换账号时，即便会话仍有效也走登录页 →
    L2/L3 全流程（其余护栏与 login_interactive 完全同码）。"""
    if not allow_popup:
        return _silent_poll(st)
    return _interactive_login(st, force=force)


def _silent_poll(st: dict):
    """静默 poll（协议 §6 修订）：只 fetch，绝不导航登录页；
    POLL_DEADLINE（<15s）内必回——任何 evaluate_js 异常/超时立即转
    state=error 响应，绝不让看门狗抓到把柄。"""
    window = st["window"]
    budget = float(st.get("poll_deadline", POLL_DEADLINE))
    start = time.monotonic()
    reloaded = False

    def remaining() -> float:
        return budget - (time.monotonic() - start)

    if st.get("page_poisoned"):
        # 上一次导航污染过页面（登录页/重定向链）：重载 console 首页一次自愈
        log("INFO", "polluted page -> reload console home once (silent)")
        st["page_poisoned"] = False
        reloaded = True
        if _goto(window, CONSOLE_URL):
            _wait_page_ready(window, max(0.5, min(RELOAD_SETTLE_BUDGET,
                                                  remaining())))
    else:
        # Fix 1/Fix 3：交互绕行后窗口可能泊在 home.console 等错误 origin——
        # 入场 fetch 前先过 origin 护栏（poisoned 路径本身已在回 console，不叠加）
        _ensure_console_origin(window, st)
    rs, results, detail = _guarded_round(st, remaining())
    if rs == "live":
        st["state"] = "live"
        return "live", results, None
    if rs == "error":
        st["state"] = "error"
        st["page_poisoned"] = True      # 下轮 poll 重载 console 自愈
        return "error", results, detail or "fetch-timeout"
    # need_login / other：CM 有凭据 → 允许重载 console 首页一次试 SPA 静默续登
    creds = load_login_creds()
    if creds is not None and not reloaded and remaining() > 2.0:
        log("INFO", "need_login + CM creds -> reload console once for SPA renew")
        reloaded = True
        _goto(window, CONSOLE_URL)
        _wait_page_ready(window, max(0.5, min(RELOAD_SETTLE_BUDGET, remaining())))
        rs2, results2, detail2 = _guarded_round(st, remaining())
        if rs2 == "live":
            st["state"] = "live"
            return "live", results2, None
        if rs2 == "error":
            st["state"] = "error"
            st["page_poisoned"] = True
            return "error", results2 or results, detail2 or "fetch-timeout"
        if results2 is not None:
            results = results2
    if creds is None:
        st["state"] = "no_credential"
        return "no_credential", results, None
    st["state"] = "need_login"
    return "need_login", results, None


def _interactive_login(st: dict, force: bool = False):
    """交互路径（协议 §6 修订）：允许导航登录页走 L1'→L2→L3；
    每条出口（成功/失败/人工完成）先落稳定页再隐藏/事件/回响应。

    force=True（reauth）：第 1 步「已 live 立即回包」与第 2 步「导航登录页后
    SPA 静默续登即回 live」两处短路都跳过——显式重登语义下必须真走登录页
    提升 + L2/L3（用户可能想换账号）；stop/shutdown、泊航跳过、origin 护栏、
    submit-verify 机械全部照常。"""
    window, stop = st["window"], st["stop"]
    try:
        tick = float(st.get("poll_interval", POLL_INTERVAL))
        # 1. 先 fetch 一轮（可能已 live，立即回包；reauth 跳过此短路）
        rs, results, detail = _guarded_round(st, POLL_DEADLINE)
        if rs == "live" and not force:
            st["state"] = "live"
            return "live", results, None
        # 2. 导航登录页（交互允许）+ SPA 静默续登等待；导航即标中毒
        log("INFO", f"interactive: {rs}{' (force)' if force else ''}"
                    f" -> navigate login page")
        st["page_poisoned"] = True
        _goto(window, LOGIN_URL)
        wait = float(st.get("silent_retry_wait", SILENT_RETRY_WAIT))
        if not _sleep_until(stop, time.monotonic() + wait, interval=tick):
            return "error", results, "cancelled"
        rs, results2, _d = _guarded_round(st, INTERACTIVE_ROUND_BUDGET)
        if results2 is not None:
            results = results2
        if rs == "live" and not force:
            return _finish_live(st, results, "silent")
        # 3. L2：CM 账密自动填充（仅在页面可执行 JS 时尝试）。
        #    实探取证（2026-10-10）：account 登录页表单在跨源 iframe、顶层零输入
        #    元素——先提升 passport 账密 entrance 到顶层（17:11 修订：实时抓取
        #    iframe src、失败兜底静态 URL），填充失败再回 account 完整登录页交
        #    人工（L3 弹窗停在用户可输入页）。
        creds = load_login_creds()
        if creds is not None and _page_ready_now(window):
            username, password = str(creds[0]), str(creds[1])
            _promote_to_pwd_entrance(window)
            l2 = _normalize_autofill_result(autofill_login(
                window, username, password,
                inputs_budget=float(st.get("autofill_inputs_budget",
                                            AUTOFILL_INPUTS_BUDGET)),
                verify_wait=float(st.get("submit_verify_wait",
                                         SUBMIT_VERIFY_WAIT))))
            await_full = False
            if l2["submitted"]:
                if l2["verify"] == "cleared":
                    # submit 被接受（握手在途）：等待有回报，维持全量 await
                    await_full = True
                else:
                    # 17:25 实证：inconclusive（疑似风控静默拦截——提交被吞，
                    # 等待不可能生效）与 err（错密码等，等待同样无意义）都不
                    # 该再烧满 AUTOFILL_BUDGET 的泊航轮 → 廉价宽限后快速升级。
                    grace = _l2_fast_grace(st)
                    if grace == "cancelled":
                        return "error", results, "cancelled"
                    if grace == "left":
                        await_full = True        # 慢 redirect 离开登录 host=真在途
                    else:
                        gsec = float(st.get("l2_grace_seconds",
                                            L2_FAST_GRACE_SECONDS))
                        log("INFO", f"L2 fast-escalate: verify={l2['verify']} "
                                    f"(grace {gsec:.0f}s still on login "
                                    f"host) -> L3")
            if await_full:
                rs, res2, _d = _await_live(st, AUTOFILL_BUDGET,
                                           recheck=L2_RECHECK_SECONDS)
                if res2 is not None:
                    results = res2
                if rs == "live":
                    return _finish_live(st, results, "autofill")
                if rs == "error":
                    return "error", results, "cancelled"
            # L2 未成功（快速升级，或提交后 AUTOFILL_BUDGET 内未 live）：若仍泊
            # 在 passport 顶层页，回 account 页（扫码/短信/RAM 全形态）再进 L3
            if _url_host(_url_for_log(window)) == PWD_LOGIN_HOST:
                _goto(window, LOGIN_URL)
                _wait_page_ready(window, RELOAD_SETTLE_BUDGET)
        else:
            # 单次尝试门控保留（页面不可执行 JS 时填充必败），但补 skip-reason 日志
            log("INFO", "L2 autofill skipped: " +
                ("no credentials" if creds is None else "page not ready"))
        # 4. L3：人工（协议 §1：仅此处弹窗）；等待期禁 fetch 风暴（§6 修订）
        log("INFO", "L2 incomplete -> L3 manual login (popup)")
        _popup_pulse(window, st)
        if st.get("login_phase") != "manual":
            st["login_phase"] = "manual"
            # Fix 2a：弹窗标题提示"别关"；成功/失败/取消任一路径都恢复原标题
            try:
                st["orig_title"] = window.title
            except Exception:                           # noqa: BLE001
                st["orig_title"] = None
            if not _set_window_title(window, MANUAL_LOGIN_TITLE):
                st["orig_title"] = None
            emit({"event": "login_required"})
        rs, res3, _d = _await_live(st, float(st.get("manual_budget",
                                                    MANUAL_BUDGET)))
        _restore_login_title(st)
        if rs == "live":
            st["login_phase"] = None
            return _finish_live(st, res3, "manual")
        if rs == "error":
            st["login_phase"] = None
            return "error", res3 or results, "cancelled"
        # 5. 全链失败：先落稳定页，再隐藏 + login_failed + 响应
        st["login_phase"] = None
        _land_stable(st)
        _hide_window(st)
        emit({"event": "login_failed", "reason": "timeout"})
        st["state"] = "need_login" if creds is not None else "no_credential"
        return st["state"], results, None
    except Exception as e:                              # noqa: BLE001
        log("ERROR", f"interactive crashed: {type(e).__name__}")
        st["login_phase"] = None
        try:
            _restore_login_title(st)
        except Exception:                               # noqa: BLE001
            pass
        try:
            _land_stable(st)
        except Exception:                               # noqa: BLE001
            pass
        st["state"] = "error"
        return "error", None, f"interactive:{type(e).__name__}"
    finally:
        if not st.get("hidden", True):
            _hide_window(st)


def _notify_login_window_closed(st: dict) -> None:
    """Fix 2(b)：L3 人工等待期间用户关掉弹窗 → 窗口关闭使 webview.start() 返回。
    这不是成功——main() 在 start 返回后调用本函数，若当时仍处 manual 阶段则向
    stdout 补发 login_failed(window_closed)（best-effort，全吞异常）。client 侧
    对 EOF 已有兜底；重开 pill 会重跑瀑布（origin 护栏已修跨源死循环）。"""
    try:
        if st.get("login_phase") == "manual":
            emit({"event": "login_failed", "reason": "window_closed"})
    except Exception:                                   # noqa: BLE001
        pass


def detail_from_results(results) -> str:
    """≤200 字符安全摘要：只含 kind/status/classify，不含信封正文。"""
    if not results:
        return "fetch round unavailable"
    parts = []
    for k in KINDS:
        r = results.get(k) or {}
        if r.get("err"):
            parts.append(f"{k}:err")
        else:
            parts.append(f"{k}:{r.get('status')}/"
                         f"{classify_envelope(r.get('text'))}")
    return safe_detail(" ".join(parts))


# ---------------------------------------------------------------- 运行时：命令分发

def handle_command(st: dict, cmd: dict):
    """处理单条命令；返回 True 表示应退出（shutdown/EOF）。"""
    cid = cmd.get("id")
    cmd_name = cmd.get("cmd")
    if cmd_name not in KNOWN_CMDS:
        emit({"id": cid, "ok": False, "error": "BAD_CMD"})
        return False
    window, api = st["window"], st["api"]
    try:
        if cmd_name == "poll":
            outcome, results, detail = ensure_login(st, allow_popup=False)
            if outcome == "live":
                emit({"id": cid, "ok": True, "state": "live",
                      "data": build_poll_data(results)})
            elif outcome == "no_credential":
                emit({"id": cid, "ok": False, "state": "no_credential",
                      "error": "NO_CREDENTIAL", "detail": detail_from_results(results)})
            elif outcome == "need_login":
                emit({"id": cid, "ok": False, "state": "need_login",
                      "error": "LOGIN_EXPIRED", "detail": detail_from_results(results)})
            else:
                emit({"id": cid, "ok": False, "state": "error",
                      "error": "HELPER_ERROR",
                      "detail": safe_detail(detail or "fetch round failed")})
        elif cmd_name in ("login_interactive", "reauth"):
            # reauth（2026-10-12）：同 login_interactive 但 force=True——跳过
            # 「已 live 立即回包」短路，强制走登录页提升 + L2/L3（重登/换账号）。
            # 响应形状与事件（login_required/login_done/login_failed）完全一致。
            outcome, results, detail = ensure_login(
                st, allow_popup=True, force=(cmd_name == "reauth"))
            if outcome == "live":
                emit({"id": cid, "ok": True, "state": "live",
                      "data": build_poll_data(results)})
            elif outcome == "no_credential":
                emit({"id": cid, "ok": False, "state": "no_credential",
                      "error": "NO_CREDENTIAL",
                      "detail": "manual login completed or no credential"})
            elif outcome == "need_login":
                emit({"id": cid, "ok": False, "state": "need_login",
                      "error": "LOGIN_EXPIRED", "detail": detail_from_results(results)})
            else:
                emit({"id": cid, "ok": False, "state": "error",
                      "error": "HELPER_ERROR",
                      "detail": safe_detail(detail or "fetch round failed")})
        elif cmd_name == "status":
            emit({"id": cid, "state": st.get("state", "unknown"),
                  "hidden": bool(st.get("hidden", True)),
                  "uptime_s": int(time.time() - st["start_ts"])})
        elif cmd_name == "save_creds":
            resp = store_login_creds(cmd.get("username"), cmd.get("password"))
            resp["id"] = cid
            if resp.get("ok"):
                resp.setdefault("state", st.get("state", "unknown"))
            emit(resp)
        elif cmd_name == "shutdown":
            return True
    except Exception as e:                              # noqa: BLE001
        log("ERROR", f"cmd {cmd_name} exception: {type(e).__name__}")
        emit(error_response(cid, "HELPER_ERROR", f"cmd {cmd_name}"))
    return False


# ---------------------------------------------------------------- 运行时：主循环

def _stdin_reader(cmd_q: queue.Queue, st: dict) -> None:
    """读 stdin JSONL；EOF/关闭 → bye 事件 + 销毁窗口（协议 §7）。"""
    stream = sys.stdin
    while not st["stop"].is_set():
        try:
            line = stream.readline() if stream is not None else ""
        except (ValueError, OSError):        # stdin 被关
            line = ""
        if line == "":
            if not st["bye_emitted"]:
                st["bye_emitted"] = True
                emit({"event": "bye"})
            st["stop"].set()
            try:
                st["window"].destroy()
            except Exception:                            # noqa: BLE001
                pass
            return
        cmd_q.put(line)
        # shutdown 在途也要能打断长流程（L3 人工等待中的 _await_live/_sleep_until
        # 都看 stop）；正常路径仍由 _worker 串行处理该行并干净收尾。
        try:
            if json.loads(line).get("cmd") == "shutdown":
                st["stop"].set()
        except (ValueError, AttributeError):
            pass


def _worker(st: dict, cmd_q: queue.Queue) -> None:
    """webview 生命周期内的串行命令执行（webview.start 的 func 线程）。"""
    window, api = st["window"], st["api"]
    stop = st["stop"]
    time.sleep(1.0)                      # 等页面首帧；fetch 失败有瀑布兜底
    log("INFO", f"worker online pid={os.getpid()}")
    while not stop.is_set():
        try:
            line = cmd_q.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            cmd = parse_command(line)
        except CommandError:
            emit({"id": None, "ok": False, "error": "BAD_CMD"})
            continue
        if cmd is None:
            continue
        if handle_command(st, cmd):
            break
    if not st["bye_emitted"]:
        st["bye_emitted"] = True
        emit({"event": "bye"})
    stop.set()
    try:
        window.destroy()
    except Exception:                                    # noqa: BLE001
        pass


def main(profile_dir: Path, pre_window_hook=None) -> int:
    """Helper 入口（main.py --bailian-helper 分支调用；main 线程跑 webview）。"""
    use_utf8_stdio()
    profile_dir = Path(profile_dir)
    try:
        fd, lock_path = acquire_instance_lock(profile_dir)
    except AlreadyLocked as e:
        log("ERROR", f"profile locked (pid={e.args[0] if e.args else '?'})")
        emit({"event": "bye"})
        return 1
    try:
        import webview
    except ImportError:
        log("ERROR", "webview unavailable")
        emit({"event": "bye"})
        release_instance_lock(fd, lock_path)
        return 1
    api = Api()
    window = webview.create_window(WINDOW_TITLE, CONSOLE_URL,
                                   hidden=True, js_api=api,
                                   width=1150, height=780)
    if window is None:
        log("ERROR", "window creation failed (WebView2 runtime?)")
        emit({"event": "bye"})
        release_instance_lock(fd, lock_path)
        return 1
    st: dict = {
        "window": window, "api": api, "stop": threading.Event(),
        "state": "unknown", "hidden": True, "login_phase": None,
        "sec_box": [], "start_ts": time.time(), "bye_emitted": False,
        "page_poisoned": False, "round_seq": 0,
    }
    cmd_q: queue.Queue = queue.Queue()
    threading.Thread(target=_stdin_reader, args=(cmd_q, st),
                     daemon=True, name="helper-stdin").start()
    if pre_window_hook:                     # 仅测试/调试注入，运行时为 None
        pre_window_hook(st)
    try:
        webview.start(_worker, (st, cmd_q), private_mode=False,
                      storage_path=str(profile_dir))
    except Exception as e:                  # noqa: BLE001
        log("ERROR", f"webview.start failed: {type(e).__name__}")
        return 1
    finally:
        st["stop"].set()
        release_instance_lock(fd, lock_path)
    # Fix 2(b)：start() 正常返回而 login_phase 仍是 manual = 用户关闭了弹窗
    # 终止了 webview 事件环——这不是成功，补发 login_failed(window_closed)。
    _notify_login_window_closed(st)
    return 0
