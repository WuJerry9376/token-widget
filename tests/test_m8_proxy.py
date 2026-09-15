"""M8 网络代理验收（fixture 驱动，零真实网络、不依赖本机代理软件）。

运行：`python tests\\test_m8_proxy.py`（Tk 段需可用桌面会话；窗口全程 withdraw）。
红线：
- codex._req / opencode_go._req 用带 opener 记录的替身（M11a：原 openai 桩位换
  Codex）；gw._req 拦截（到达即违规）；
- config/state/auth/USERPROFILE 全重定向临时目录；真实 local\\ 前后哈希比对；
- 结构隔离断言：bailian 两件 + scheduler/ui/registry/main/auth 源码永不含 proxy/netconfig。
覆盖（任务书）：normalize 各形态；build_opener 启用/禁用/非法；proxy_for 矩阵；
两 source opener 注入路由（代理 vs 直连）与 NETWORK 提示语；脱敏（user:pass→:***@）；
probe_channel 分类（任意 HTTP 状态=通）；设置面板代理区渲染/保存/回读/非法输入；
测试连通按钮绿/橙分档。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import auth, config as config_mod, netconfig as npc                   # noqa: E402
from src import settings_panel                                                  # noqa: E402
from src import state as state_mod                                              # noqa: E402
from src.scheduler import Scheduler                                             # noqa: E402
from src.sources import bailian_gateway as gw                                   # noqa: E402
from src.sources import codex as cx                                             # noqa: E402
from src.sources import opencode_go as og                                       # noqa: E402
from src.state import DEFAULTS                                                  # noqa: E402
from src.ui import FAINT, OK, ORANGE, PAPER, TRACK, TRACK_EDGE, NoteApp   # noqa: E402
import main as main_mod                                                         # noqa: E402

REAL_LOCAL = ROOT / "local"
CX_TOKEN = "eyJ-cx-FAKE-abcdefg-0123456789"
GO_KEY = "go-FAKE-key-0123456789"
PX_OK = "http://127.0.0.1:7890"

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False, "enabled_providers": ["bailian"],
       "opencode_go": {"auto_detect": True},
       "network": {"proxy_enabled": False, "proxy_url": "",
                   "proxy_targets": ["opencode_go", "codex"]}}

tmp_root = Path(".")
_net: list[str] = []


class ReqRec:
    """_req(url, headers, opener=None) 替身：记录三元组，交 responder(url, headers)。"""

    def __init__(self):
        self.calls: list[tuple[str, dict, object]] = []
        self.responder = None

    def __call__(self, url, headers, opener=None):
        n = len(self.calls)
        self.calls.append((url, dict(headers), opener))
        if self.responder is None:
            raise AssertionError(f"无 responder 却请求 {url[:60]}")
        r = self.responder(url, headers, n)
        if isinstance(r, Exception):
            raise r
        return r

    @property
    def openers(self):
        return [c[2] for c in self.calls]


reqrec = ReqRec()


def set_resp(fn):
    reqrec.calls = []
    reqrec.responder = fn


def write_cfg(**network):
    cfg = {**CFG, "network": {**CFG["network"], **network}}
    (tmp_root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def codex_ok(url, headers, n):
    """M11a（原 costs_ok）：codex usage 200 样本，s1/t3 路由断言用。"""
    return 200, "application/json", json.dumps(
        {"plan_type": "plus", "rate_limit": {"allowed": True, "primary_window": {
            "used_percent": 10, "limit_window_seconds": 18000,
            "reset_after_seconds": 3600}}}).encode()


def usage_ok(url, headers, n):
    return 200, "application/json", json.dumps(
        {"usage": {"rolling": {"percent": 25, "resetsAt":
                               datetime.now(timezone.utc).timestamp() + 3600}}}).encode()


# ------------------------------------------------- normalize / 构建 ----

def n1_normalize_accept() -> str:
    cases = {
        "127.0.0.1:7890": PX_OK,
        "  http://127.0.0.1:7890 ": PX_OK,
        "127.0.0.1 7890": PX_OK,                      # 两段式（空格分隔）
        "http://user:pass@127.0.0.1:7890": "http://user:pass@127.0.0.1:7890",
        "HTTP://127.0.0.1:7890/": PX_OK,              # scheme 大小写 + 尾斜杠
        "10.0.0.2:3128": "http://10.0.0.2:3128",
        "[::1]:7890": "http://[::1]:7890",             # IPv6 括号保留
    }
    for src, want in cases.items():
        got = npc.normalize_proxy_url(src)
        assert got == want, (src, got, want)
    return f"{len(cases)} 形态规范化正确"


def n2_normalize_reject() -> str:
    bad = ["", "   ", None, 12345, "127.0.0.1",          # 无端口裸 host
           "http://noport.example",                      # scheme 形态也要求端口（返回型固定 host:port）
           "socks5://127.0.0.1:7890", "socks://h:1",     # socks 明确不支持
           "ftp://h:21", "127.0.0.1:99999", "127.0.0.1:0",
           "host port", "abc:xyz", "://x:1",
           "http://h:80/path", "http://h:80?x=1"]
    for b in bad:
        assert npc.normalize_proxy_url(b) is None, b
    return f"{len(bad)} 非法形态全部 None"


def n3_build_opener() -> str:
    assert npc.build_opener(None) is None
    assert npc.build_opener({"network": {"proxy_enabled": False,
                                         "proxy_url": PX_OK}}) is None   # 未启用 → None
    assert npc.build_opener({"network": {"proxy_enabled": True,
                                         "proxy_url": "socks5://h:1"}}) is None  # 非法 → None
    op = npc.build_opener({"network": {"proxy_enabled": True, "proxy_url": "127.0.0.1:7890",
                                       "proxy_targets": ["codex"]}})
    assert isinstance(op, urllib.request.OpenerDirector), op
    ph = [h for h in op.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert len(ph) == 1
    req = urllib.request.Request("http://ex.invalid/x")
    ph[0].proxy_open(req, PX_OK, "http")       # 同源返回 None，副作用=改写请求
    assert req.host == "127.0.0.1:7890", "http 请求应被改写为经代理发起"
    req2 = urllib.request.Request("https://ex.invalid/x")
    ph[0].proxy_open(req2, PX_OK, "https")     # CONNECT 隧道语义：目标留在 _tunnel_host
    assert req2.host == "127.0.0.1:7890" and req2._tunnel_host == "ex.invalid", \
        "https 请求应改写为向代理发起 CONNECT"
    assert ph[0].proxies["https"] == PX_OK
    return "None/None/None + ProxyHandler{http,https} 正确装配"


def n4_proxy_for_matrix() -> str:
    def cfg(on, url, tg):
        return {"network": {"proxy_enabled": on, "proxy_url": url, "proxy_targets": tg}}
    assert npc.proxy_for("codex", cfg(True, PX_OK, ["opencode_go", "codex"])) == PX_OK
    assert npc.proxy_for("opencode_go", cfg(True, PX_OK, ["opencode_go", "codex"])) == PX_OK
    assert npc.proxy_for("opencode_go", cfg(True, PX_OK, ["codex"])) is None       # 不在作用域
    assert npc.proxy_for("bailian", cfg(True, PX_OK, ["opencode_go", "codex"])) is None  # 永不
    assert npc.proxy_for("codex", cfg(False, PX_OK, ["codex"])) is None            # 总开关
    assert npc.proxy_for("codex", cfg(True, "bad input", ["codex"])) is None       # URL 非法
    assert npc.proxy_for("codex", cfg(True, PX_OK, "codex")) is None               # targets 非 list
    assert npc.proxy_for("codex", {}) is None                                      # 空 cfg
    assert npc.proxy_for("codex", {"network": {"proxy_enabled": True,
                                               "proxy_url": "127.0.0.1 7890"}}) == PX_OK  # 缺省 targets
    return "9 格矩阵正确（含 bailian 永不；M11a 样本 provider=Codex）"


def n5_sanitize() -> str:
    s = npc.sanitize_proxy_msg("connect http://u1:pa4sw0rd@127.0.0.1:7890 refused")
    assert "pa4sw0rd" not in s and "u1:***@" in s and "127.0.0.1:7890" in s, s
    s2 = npc.sanitize_proxy_msg("a http://u@h:80 b https://x:SECRET@y:1 c")
    assert "SECRET" not in s2 and "u@h:80" in s2 and "x:***@y:1" in s2, s2
    assert npc.sanitize_proxy_msg("no auth here") == "no auth here"
    assert npc.sanitize_proxy_msg(None) == "" and npc.sanitize_proxy_msg(42) == "42"
    return "://user:pass@ → ://user:***@；无认证段不动；非串不抛"


# ------------------------------------------------- probe_channel ----

class FakeResp:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class OpResp:
    def open(self, req, timeout=None):
        return FakeResp()


class OpHttp:
    def __init__(self, code, body=b""):
        self.code = code
        self.body = body

    def open(self, req, timeout=None):
        raise urllib.error.HTTPError("https://api.openai.com/v1/models", self.code,
                                     "err", {}, io.BytesIO(self.body))


class OpFail:
    def open(self, req, timeout=None):
        raise urllib.error.URLError(
            ConnectionRefusedError(10061, "target machine actively refused it"))


class OpFailAuth:
    def open(self, req, timeout=None):
        raise urllib.error.URLError(
            ValueError("tunnel to http://proxyuser:pr0xysecret@10.1.1.1:7890 failed"))


REGION_JSON = json.dumps({"error": {
    "message": "No access from your country or region.",
    "type": "invalid_request_error",
    "code": "unsupported_country_region_territory"}}).encode()


def n6_probe_classification() -> str:
    """M8 缺陷修复后三态：(状态|None, 已脱敏原因, region_blocked)。"""
    st, d, blocked = npc.probe_channel(PX_OK, opener=OpResp())
    assert (st, d, blocked) == (204, "", False), (st, d, blocked)
    st, _, blocked = npc.probe_channel(PX_OK, opener=OpHttp(401))   # 401：通、非封锁
    assert st == 401 and blocked is False
    st, _, blocked = npc.probe_channel(None, opener=OpHttp(403))    # 空 body 403：通、非封锁
    assert st == 403 and blocked is False
    st, _, blocked = npc.probe_channel(PX_OK, opener=OpHttp(403, REGION_JSON))
    assert st == 403 and blocked is True, "region 403 必须被标记（通道可达但被地区封锁）"
    st, d, blocked = npc.probe_channel(PX_OK, opener=OpFail())
    assert st is None and blocked is False and "10061" in d, (st, d)
    st, d, blocked = npc.probe_channel(PX_OK, opener=OpFailAuth())
    assert st is None and "pr0xysecret" not in d and "proxyuser:***@" in d, d
    return "三态：204/401/403 通；region403 标记；refused 败+脱敏"


# ------------------------------------------------- source 路由 ----

def s1_codex_routing() -> str:
    """M11a（原 openai_routing 桩位换 Codex）：代理路由三态。"""
    auth.save_secret("codex_access_token", CX_TOKEN)
    # (a) 启用且在作用域 → 代理 opener
    write_cfg(**{"proxy_enabled": True, "proxy_url": "127.0.0.1 7890"})
    set_resp(codex_ok)
    u = cx.CodexSource().fetch()
    assert u.ok and reqrec.calls, u.error_msg
    assert all(isinstance(op, urllib.request.OpenerDirector) for op in reqrec.openers), \
        "usage 请求应经代理 opener"
    # (b) 不在作用域 → None（直连）
    write_cfg(**{"proxy_enabled": True, "proxy_url": PX_OK, "proxy_targets": ["opencode_go"]})
    set_resp(codex_ok)
    u2 = cx.CodexSource().fetch()
    assert u2.ok and reqrec.openers == [None], reqrec.openers
    # (c) 总开关关 → None
    write_cfg(**{"proxy_enabled": False, "proxy_url": PX_OK})
    set_resp(codex_ok)
    u3 = cx.CodexSource().fetch()
    assert u3.ok and reqrec.openers == [None]
    return "enabled∧target→代理；否则直连 opener=None"


def s2_go_routing_and_network_hint() -> str:
    auth.save_secret("opencode_go_key", GO_KEY)
    auth.save_secret("codex_access_token", CX_TOKEN)   # (c) 段 codex 需 token 才会打网络
    refuse = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    # (a) 代理在作用域 + 连接被拒 → NETWORK + 「代理已启用」提示
    write_cfg(**{"proxy_enabled": True, "proxy_url": PX_OK})
    set_resp(lambda url, h, n: refuse)
    u = og.OpenCodeGoSource().fetch()
    assert u.error_code == "NETWORK", u.error_code
    assert "代理已启用，检查地址/软件" in u.error_msg, u.error_msg
    assert isinstance(reqrec.openers[0], urllib.request.OpenerDirector)
    # (b) 未启用 → 「未配置代理，直连失败」
    write_cfg(**{"proxy_enabled": False, "proxy_url": ""})
    set_resp(lambda url, h, n: refuse)
    u2 = og.OpenCodeGoSource().fetch()
    assert u2.error_code == "NETWORK" and "未配置代理，直连失败" in u2.error_msg
    assert reqrec.openers == [None]
    # (c) codex 同款提示语（M11a：原 openai 桩位）
    write_cfg(**{"proxy_enabled": True, "proxy_url": PX_OK, "proxy_targets": ["codex"]})
    set_resp(lambda url, h, n: refuse)
    u3 = cx.CodexSource().fetch()
    assert u3.error_code == "NETWORK" and "代理已启用" in u3.error_msg, (u3.error_code, u3.error_msg)
    return "两源 NETWORK msg 均带代理/直连语境提示"


def s3_proxy_cred_never_leaks() -> str:
    auth.save_secret("opencode_go_key", GO_KEY)
    write_cfg(**{"proxy_enabled": True,
                 "proxy_url": "http://proxyuser:pr0xysecret@127.0.0.1:7890"})
    leaky = urllib.error.URLError(
        "tunnel http://proxyuser:pr0xysecret@127.0.0.1:7890 refused")
    set_resp(lambda url, h, n: leaky)
    u = og.OpenCodeGoSource().fetch()
    assert u.error_code == "NETWORK"
    assert "pr0xysecret" not in u.error_msg, u.error_msg      # 密码已脱敏
    assert "proxyuser:***@" in u.error_msg, u.error_msg       # 保留可辨识的 user 段
    # 面板 CODE_HINTS 展示路径同样不泄（NETWORK → 固定文案「网络异常」）
    return "代理密码 pr0xysecret 不出现在任何 msg；user:***@ 可辨识"


def s4_bailian_structural_isolation() -> str:
    """硬边界：百炼两件 + 调度/渲染/入口/注册/auth 源码永不含代理通道关键词。"""
    for rel in ("src/sources/bailian.py", "src/sources/bailian_gateway.py",
                "src/scheduler.py", "src/ui.py", "src/registry.py", "src/auth.py",
                "src/cli.py", "main.py"):
        blob = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert "proxy" not in blob, rel
        assert "netconfig" not in blob, rel
    # 且两境外源之外无人 import netconfig（settings_panel 是唯一 UI 入口，sources 层仅两家；
    # M11a：openai.py 已删，样本换 codex.py）
    for rel in ("src/sources/opencode_go.py", "src/sources/codex.py"):
        assert "netconfig" in (ROOT / rel).read_text(encoding="utf-8"), rel
    return "8 文件零 proxy/netconfig 关键词；仅两家 source 接线"


# ------------------------------------------------- 设置面板（Tk）----

def _all_texts(w, out):
    try:
        t = w.cget("text")
        if isinstance(t, str) and t:
            out.append(t)
    except tk.TclError:
        pass
    if isinstance(w, tk.Entry):
        out.append(w.get())
    for ch in w.winfo_children():
        _all_texts(ch, out)
    return out


def t1_group_render(app, root) -> str:
    write_cfg()                                     # defaults：关闭、空、双目标
    panel = settings_panel.SettingsPanel(app)
    panel.withdraw()
    texts = _all_texts(panel, [])
    assert any("网络代理" in t for t in texts)
    assert any("启用代理" in t for t in texts)
    assert any("作用范围" in t for t in texts)
    assert any("连通测试" in t for t in texts)
    assert panel.chk_px_go.cget("text") == "OpenCode Go"
    assert panel.chk_px_cx.cget("text") == "Codex"
    assert not any(t.strip() == "OpenAI" for t in texts), "M11a：代理作用域不再有 OpenAI 项"
    assert "百炼" not in panel.chk_px_go.cget("text") + panel.chk_px_cx.cget("text")
    assert any("不支持 socks" in t for t in texts), "socks 不支持文案需在"
    # M8 视觉轮②回归锁：面板可见串一律全角括号/分号（技术串 host:port、127.0.0.1:7890 内半角不动）。
    # 注：本轮核实当前代码本就全角（0xff08/0xff09/0xff1b），此断言防半角版本回流。
    assert any("启用代理（境外源）" in t for t in texts), "须全角括号（M8②锁）"
    assert any("HTTP；不支持 socks）" in t for t in texts), "注记须全角分号+全角括号收尾（M8②锁）"
    assert panel.var_px_on.get() is False and panel.var_px_addr.get() == ""
    assert panel.var_px_go.get() and panel.var_px_cx.get(), "默认双勾（M11a：Go+Codex）"
    assert panel.lbl_net.cget("text").strip().startswith("不依赖凭据")
    panel.destroy()
    return "分组渲染：开关/地址+端口/双目标 Go+Codex（无百炼无 OpenAI）/socks 文案/测试行"


def t2_save_reread_echo(app, root) -> str:
    write_cfg()
    panel = settings_panel.SettingsPanel(app)
    panel.withdraw()
    panel.var_px_addr.set("127.0.0.1 7890")         # 两段式宽进
    panel.var_px_on.set(True)
    panel.var_px_go.set(False)
    panel._save_net()
    saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))["network"]
    assert saved["proxy_enabled"] is True
    assert saved["proxy_url"] == "127.0.0.1 7890", "存原始输入"
    assert saved["proxy_targets"] == ["codex"], saved   # 取消 Go 后仅剩 Codex（M11a 两项制）
    assert panel.var_px_addr.get() == "127.0.0.1" and panel.var_px_port.get() == "7890", \
        "保存后规范化标准形态回显"
    # 地址框已含端口时端口框不重复追加
    panel.var_px_addr.set("http://10.0.0.2:3128")
    panel.var_px_port.set("8080")
    panel._save_net()
    saved2 = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))["network"]
    assert saved2["proxy_url"] == "http://10.0.0.2:3128", saved2   # addr 自带端口优先
    assert panel.var_px_addr.get() == "10.0.0.2" and panel.var_px_port.get() == "3128"
    panel.destroy()
    # 回读：新面板按 cfg 重建控件值
    panel2 = settings_panel.SettingsPanel(app)
    panel2.withdraw()
    assert panel2.var_px_on.get() is True
    assert panel2.var_px_addr.get() == "10.0.0.2" and panel2.var_px_port.get() == "3128"
    assert panel2.var_px_cx.get() is True and panel2.var_px_go.get() is False
    panel2.destroy()
    app.cfg["network"] = dict(CFG["network"])       # 复位给后续用例
    return "原始存/标准回显/addr 端口优先/关面板重开回读一致"


def t3_bad_input_warn_direct(app, root) -> str:
    write_cfg()
    panel = settings_panel.SettingsPanel(app)
    panel.withdraw()
    panel.var_px_addr.set("not a host!!")
    panel.var_px_on.set(True)
    panel._save_net()
    st = panel.status.cget("text")
    assert "未识别" in st, st                        # 橙色宽进提示
    assert panel.status.cget("fg").lower() == ORANGE.lower()
    saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))["network"]
    assert saved["proxy_url"] == "not a host!!", (saved["proxy_url"], saved["proxy_enabled"])
    # 非法 URL 即便 enabled 也在 source 侧回落直连（opener=None；M11a 样本源=Go）
    auth.save_secret("opencode_go_key", GO_KEY)
    write_cfg(**{"proxy_enabled": True, "proxy_url": "not a host!!"})
    set_resp(usage_ok)
    u = og.OpenCodeGoSource().fetch()
    assert u.ok and reqrec.openers == [None]
    panel.destroy()
    return "非法地址：橙字提示+原样存；source 回落直连"


def t4_probe_labels(app, root) -> str:
    write_cfg()
    orig_probe = npc.probe_channel
    try:
        npc.probe_channel = lambda p, timeout=None: (401, "", False)
        panel = settings_panel.SettingsPanel(app)
        panel.withdraw()
        panel.var_px_addr.set(PX_OK)
        panel._save_net()
        panel._probe_run(PX_OK)
        lab = panel.lbl_net.cget("text")
        assert "代理通道正常（收到 HTTP 401）" in lab, lab   # 401 也算通 → 绿字
        assert panel.lbl_net.cget("fg").lower() == OK.lower()
        npc.probe_channel = lambda p, timeout=None: (403, "", True)   # region 封锁 → 橙「换节点」
        panel._probe_run(PX_OK)
        lab = panel.lbl_net.cget("text")
        assert "通道可达，但出口地区被 OpenAI 封锁：换海外节点" in lab, lab
        assert "HTTP 403" in lab
        assert panel.lbl_net.cget("fg").lower() == ORANGE.lower()
        assert "密钥" not in lab and "key" not in lab.lower(), "region 提示不得误导成密钥问题"
        npc.probe_channel = lambda p, timeout=None: (None, "[Errno 10061] refused", False)
        panel._probe_run(PX_OK)
        lab = panel.lbl_net.cget("text")
        assert "通道未建立" in lab and "检查代理地址/软件" in lab, lab
        assert "10061" in lab
        assert panel.lbl_net.cget("fg").lower() == ORANGE.lower()
        panel._probe_run(None)                                  # 直连失败语境
        assert "直连失败" in panel.lbl_net.cget("text")
        panel.destroy()
    finally:
        npc.probe_channel = orig_probe
    return "三态：401绿通；403+region橙换节点；refused橙未建立"


def t5_proxy_save_reaches_sources(app, root) -> str:
    """端到端（离线）：面板保存 → source fetch_now 即按新路由走代理 opener。"""
    write_cfg()
    auth.save_secret("opencode_go_key", GO_KEY)
    set_resp(usage_ok)
    panel = settings_panel.SettingsPanel(app)
    panel.withdraw()
    panel.var_px_addr.set("127.0.0.1")
    panel.var_px_port.set("7890")
    panel.var_px_on.set(True)
    panel._save_net()
    from src.registry import SOURCES
    u = SOURCES["opencode_go"].fetch_now()
    assert u.ok, (u.error_code, u.error_msg)
    assert isinstance(reqrec.openers[-1], urllib.request.OpenerDirector), \
        "面板保存后下一采集应即刻经代理"
    panel.destroy()
    return "保存→fetch_now 走代理 opener（改即生效）"


def t6_probe_button_two_states(app, root) -> str:
    """M8 视觉轮① + M12①：代理组（Entry/作用域勾选/测试按钮）随「启用代理」整组两态。"""
    write_cfg()                                     # 默认关闭
    app.cfg["network"] = dict(CFG["network"])       # 复位内存态（面板读 app.cfg 非文件；t5 会污染）
    panel = settings_panel.SettingsPanel(app)
    panel.withdraw()
    b = panel.btn_probe
    # —— 关闭态（初建即应为此态——初始化正确性锁）：整组禁用 ——
    assert str(b.cget("state")) == "disabled", "未启用应为禁用态"
    assert int(b.cget("highlightthickness")) == 0, "禁用态无描边"
    assert str(b.cget("disabledforeground")).lower() == FAINT.lower(), "禁用态灰字"
    assert str(b.cget("bg")).lower() == PAPER.lower(), "禁用底融回面板（经典 tk 无 disabledbackground，直接切 bg）"
    for e in (panel.ent_px_addr, panel.ent_px_port):
        assert str(e.cget("state")) == "disabled", "M12① 未启用时地址/端口 Entry 应禁用"
        assert str(e.cget("disabledbackground")).lower() == PAPER.lower(), \
            "M12① disabled 底融纸"
        assert str(e.cget("disabledforeground")).lower() == FAINT.lower()
    for k in (panel.chk_px_go, panel.chk_px_cx):
        assert str(k.cget("state")) == "disabled", "M12① 未启用时作用域勾选应禁用"
        assert str(k.cget("disabledforeground")).lower() == FAINT.lower(), "文字转 FAINT"
    # —— 启用态：整组回可编辑 + 按钮常态加深底 ——
    panel.var_px_on.set(True)
    panel._sync_probe_btn()
    assert str(b.cget("state")) == "normal", "启用后应可点"
    assert int(b.cget("highlightthickness")) == 1, "启用态 1px 描边"
    assert str(b.cget("bg")).lower() == TRACK.lower(), "常态底色加深一档"
    assert str(b.cget("highlightbackground")).lower() == TRACK_EDGE.lower()
    for e in (panel.ent_px_addr, panel.ent_px_port):
        assert str(e.cget("state")) == "normal", "M12① 恢复勾选即时回可编辑"
        assert str(e.cget("bg")).lower() == settings_panel.ENTRY_BG.lower()
    for k in (panel.chk_px_go, panel.chk_px_cx):
        assert str(k.cget("state")) == "normal"
    # 常态底色比面板底深一档（对比可辨）
    assert int(TRACK[1:], 16) < int(PAPER[1:], 16), "常态底应比面板底深"
    # 勾选框命令确会联动整组态（_save_net 走 _sync_probe_btn）
    panel.var_px_on.set(False)
    panel._save_net()
    assert str(b.cget("state")) == "disabled", "取消勾选后回落禁用"
    assert str(panel.ent_px_addr.cget("state")) == "disabled"
    assert str(panel.chk_px_cx.cget("state")) == "disabled"
    panel.destroy()
    return "整组两态：Entry/作用域/按钮 禁用(融纸/灰字/无描边) ↔ 常态(可编辑/TRACK底/可点)"


# ---------------------------------------------------------------- run ----

def local_snapshot() -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(REAL_LOCAL.glob("*")) if p.is_file()}


def clear_dpapi():
    for p in tmp_root.glob("*.dpapi"):
        try:
            p.unlink()
        except OSError:
            pass


def run(tmp: Path) -> int:
    global tmp_root
    tmp_root = tmp
    checks: list[tuple[str, bool, str]] = []
    before = local_snapshot()

    def case(name, fn):
        print(f"· {name} …", flush=True)
        clear_dpapi()
        try:
            note = fn() or ""
            checks.append((name, True, note))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:220]))

    orig = (auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE,
            config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            cx._req, og._req, gw._req, os.environ.get("USERPROFILE"))

    def blocked(url, headers, data=None):
        _net.append(str(url)[:80])
        raise AssertionError("真实网络请求被拦截（测试违规）")

    auth.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = tmp / "bailian_cookie.dpapi"
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    os.environ["USERPROFILE"] = str(tmp)
    p = tmp / ".local" / "share" / "opencode"
    p.mkdir(parents=True, exist_ok=True)
    (p / "auth.json").write_text("{}", encoding="utf-8")
    cx._req = reqrec
    og._req = reqrec
    gw._req = blocked
    root = app = None
    try:
        for name, fn in [("normalize_accept", n1_normalize_accept),
                         ("normalize_reject", n2_normalize_reject),
                         ("build_opener", n3_build_opener),
                         ("proxy_for_matrix", n4_proxy_for_matrix),
                         ("sanitize_msg", n5_sanitize),
                         ("probe_classification", n6_probe_classification),
                          ("codex_routing", s1_codex_routing),
                         ("go_routing_hint", s2_go_routing_and_network_hint),
                         ("proxy_cred_sanitize", s3_proxy_cred_never_leaks),
                         ("bailian_isolation", s4_bailian_structural_isolation)]:
            case(name, fn)

        main_mod.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        sched = Scheduler([], poll_seconds=300)     # 不 start：零后台拉取
        app = NoteApp(root, dict(CFG), sched, state=dict(DEFAULTS))
        root.withdraw()
        for name, fn in [("panel_render", t1_group_render),
                         ("panel_save_reread", t2_save_reread_echo),
                         ("panel_bad_input", t3_bad_input_warn_direct),
                         ("panel_probe", t4_probe_labels),
                         ("panel_to_source", t5_proxy_save_reaches_sources),
                         ("panel_probe_two_states", t6_probe_button_two_states)]:
            print(f"· {name} …", flush=True)
            clear_dpapi()
            try:
                note = fn(app, root) or ""
                checks.append((name, True, note))
            except Exception as e:                  # noqa: BLE001
                checks.append((name, False, repr(e)[:220]))
    finally:
        try:
            if app is not None:
                app.quit()
        except Exception:                           # noqa: BLE001
            pass
        (auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE,
         config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         cx._req, og._req, gw._req, _up) = orig
        if _up is not None:
            os.environ["USERPROFILE"] = _up

    checks.append(("NET_零真实网络（拦截线未触发）", not _net, "; ".join(_net)))
    checks.append(("GUARD_real_local_untouched", local_snapshot() == before, ""))
    bad = [c for c in checks if not c[1]]
    print()
    for name, ok, note in checks:
        print(f"  {'PASS' if ok else 'FAIL':4} {name} {note}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    import tempfile
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="m8_px_") as d:
        raise SystemExit(run(Path(d)))
