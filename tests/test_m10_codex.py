"""M10 Codex（ChatGPT Plan 窗口限额）实验性 provider 验收（fixture 零网络）。

运行：`python tests\\test_m10_codex.py`（Tk 段需可用桌面会话；窗口全程 withdraw）。
唯一事实来源：docs/codex_chatgpt_wire_spec.md。本机无 Codex 登录 → 真实首跑在用户
生产机；本套件全部 mock：
- codex._req / opencode_go._req / gw._req 全程打桩（真实 HTTP=违规；M11a 起
  openai source 已删，本套件不再引用）；
- config/state/auth.LOCAL_DIR/USERPROFILE 重定向 temp；~/.codex/auth.json 用伪造文件；
- 真实 local\\ 与（若存在的）真实 ~/.codex/auth.json 前后哈希守护，绝不读写真实凭据；
- 结构断言：百炼三件 + scheduler + base 永不含 "codex" 字样（本任务零触碰）。
覆盖（任务书）：窗口按秒匹配/归一+allowed 钳位/reset 三形态/credits→float/错误分码/
not_configured 零网络且与 Go 侧凭据完全隔离/detect 五变体/缓存+代理路由/
第 4 复选框+作用域 codex/绑定面板保存即验证不回显/tooltip 积分与徽章大写/cli 行/
错误行橙档与面板联动。M10b 增补：CF 指纹头（originator+Sec-Fetch 对、无 Accept-Encoding）/
find_codex_auth 四路径变体（优先级/损坏跳过/全缺 None）/窗口重置券 note 与 PII 零入库/
检测行三态（手动/自动+来源路径/三候选缺失）。M11b 改版：双进度条（主条=最紧已知窗+
副细条，独立阈值色，other:N 行内不显、tooltip 全列）+ 券×N 角标（无券零占位、
hover 说明热区）+ 单/双窗高度与 stale 降灰联动断言。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import auth, config as config_mod, settings_panel, state as state_mod   # noqa: E402
from src import cli as cli_mod                                                    # noqa: E402
from src import netconfig as npc                                                  # noqa: E402
from src.scheduler import Scheduler                                               # noqa: E402
from src.sources import bailian_gateway as gw                                     # noqa: E402
from src.sources import codex as cx                                               # noqa: E402
from src.sources import opencode_go as og                                         # noqa: E402
from src.sources.base import Usage, Window                                        # noqa: E402
from src.state import DEFAULTS                                                    # noqa: E402
from src.ui import (CODEX_GAP, CODEX_TEXT_Y, CODEX_TXT_BAR, OK, ORANGE, ROW_ADDON,
                    SOFT, SOFT_TXT, NoteApp,                                   # noqa: E402
                    spec_display, _tip_credits, addon_bar_state, codex_bars,
                    codex_ticket_count, codex_win_caption)
import main as main_mod                                                           # noqa: E402

REAL_LOCAL = ROOT / "local"
CODEX_TOKEN = "eyJ-fake-codex-jwt-0123456789-TAIL"
ADMIN_KEY = "FAKE-admin-key-0123456789"      # 仅作"不合格 auth.json 载荷"样本串（M11a）
GO_KEY = "go-FAKE-key-0123456789"
PX_OK = "http://127.0.0.1:7890"

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False, "enabled_providers": ["bailian"],
       "opencode_go": {"auto_detect": True},
       "network": {"proxy_enabled": False, "proxy_url": "",
                   "proxy_targets": ["opencode_go", "codex"]}}

tmp_root = Path(".")
_net: list[str] = []
_NOW = datetime.now(timezone.utc)


class Stub:
    """codex/go 两模块共用 _req 替身（M11a：openai source 已删）：记录 (url, headers, opener)。"""

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


stub = Stub()


def set_resp(fn):
    stub.calls = []
    stub.responder = fn


def usage_json(rate_limit, plan="plus", credits=None):
    j: dict = {"plan_type": plan, "rate_limit": rate_limit}
    if credits is not None:
        j["credits"] = credits
    return 200, "application/json", json.dumps(j).encode()


def win(pct, secs, **kw):
    w = {"used_percent": pct, "limit_window_seconds": secs}
    w.update(kw)
    return w


def fresh() -> cx.CodexSource:
    return cx.CodexSource()


def save(name: str, value: str) -> None:
    auth.save_secret(name, value)              # auth.LOCAL_DIR 已重定向 tmp


def write_codex_auth(payload) -> Path:
    p = tmp_root / ".codex"
    p.mkdir(parents=True, exist_ok=True)
    f = p / "auth.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


# ------------------------------------------------------ source 用例 ----

def c1_windows_normal() -> str:
    """spec 规则 1：按秒数匹配——18000→"5h"、604800→"周"；pct 归一、reset_at epoch 秒。"""
    save("codex_access_token", CODEX_TOKEN)
    epoch = int(_NOW.timestamp()) + 7200
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True, "limit_reached": False,
         "primary_window": win(62, 18000, reset_at=epoch),
         "secondary_window": win(30, 604800, reset_at=epoch + 86400 * 3)},
        plan="pro", credits={"has_credits": False}))
    u = fresh().fetch()
    assert u.ok and u.unit == "percent" and u.total is None, (u.error_code, u.error_msg)
    assert stub.calls[0][1]["Authorization"] == "Bearer " + CODEX_TOKEN
    assert [w.label for w in u.windows] == ["5h", "周"], u.windows
    assert abs(u.pct_used - 0.62) < 1e-9 and abs(u.windows[1].pct_used - 0.30) < 1e-9
    assert abs(u.windows[0].resets_at.timestamp() - epoch) <= 2
    assert u.spec == "pro" and stub.calls[0][1]["Authorization"] == "Bearer " + CODEX_TOKEN
    assert u.addon_remaining is None, "has_credits=False → 积分位留 None"
    return "5h/周 按秒匹配；62→0.62；epoch reset_at；spec=plan"


def c2_windows_no_5h_primary_week_other() -> str:
    """无 5h 套餐：周窗出现在 primary（禁按位置写死）；未知秒数 → other:<sec>。"""
    save("codex_access_token", CODEX_TOKEN)
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True,
         "primary_window": win(40, 604800, reset_at=int(_NOW.timestamp()) + 86400),
         "secondary_window": win(10, 21600, reset_after_seconds=3600)}))
    u = fresh().fetch()
    assert u.ok and u.windows[0].label == "周", [w.label for w in u.windows]
    assert u.windows[1].label == "other:21600", u.windows[1].label
    assert abs(u.pct_used - 0.40) < 1e-9          # 最紧窗=周(40%) 在首位
    return "周窗居 primary 正确 label；21600s → other:21600"


def c3_tightest_first_sort() -> str:
    """最紧窗在前（spec Usage 映射「pct_used 取最紧窗」，主行 label 与 pct 一致）。"""
    save("codex_access_token", CODEX_TOKEN)
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True,
         "primary_window": win(20, 18000),
         "secondary_window": win(80, 604800)}))
    u = fresh().fetch()
    assert u.windows[0].label == "周" and abs(u.pct_used - 0.80) < 1e-9
    assert u.windows[1].label == "5h"
    assert u.resets_at == u.windows[0].resets_at   # 主行倒计时跟最紧窗
    return "5h 20% < 周 80% → windows[0]=周，pct_used=0.8"


def c4_allowed_false_clamp() -> str:
    """spec 规则 5：allowed=False → 各窗 pct 钳 1.0（行满档）。"""
    save("codex_access_token", CODEX_TOKEN)
    set_resp(lambda url, h, n: usage_json(
        {"allowed": False, "limit_reached": True,
         "primary_window": win(12, 18000, reset_after_seconds=900)}))
    u = fresh().fetch()
    assert u.ok and u.pct_used == 1.0 and u.windows[0].pct_used == 1.0, u.pct_used
    return "allowed=False → pct 钳 1.0"


def c5_reset_forms() -> str:
    """reset 三形态：epoch 秒（含毫秒兼容）/ reset_after_seconds 倒计时 / 皆缺 → None。"""
    save("codex_access_token", CODEX_TOKEN)
    ep = int(_NOW.timestamp()) + 600
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True,
         "primary_window": win(10, 18000, reset_at=ep),
         "secondary_window": win(5, 604800, reset_after_seconds=1800)}))
    u = fresh().fetch()
    assert abs(u.windows[0].resets_at.timestamp() - ep) <= 2
    d = (u.windows[1].resets_at - datetime.now(timezone.utc)).total_seconds()
    assert 1790 < d < 1830, d
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True, "primary_window": win(10, 18000, reset_at=ep * 1000)}))
    u2 = fresh().fetch()
    assert abs(u2.windows[0].resets_at.timestamp() - ep) <= 2   # 毫秒兼容
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True, "primary_window": win(10, 18000)}))
    u3 = fresh().fetch()
    assert u3.ok and u3.windows[0].resets_at is None and u3.resets_at is None
    return "epoch 秒/毫秒、倒计时、皆缺 None"


def c6_credits_balance_float() -> str:
    """spec 规则 4：has_credits 时 balance（十进制串）→ float 进 addon 复用位。"""
    save("codex_access_token", CODEX_TOKEN)
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True, "primary_window": win(10, 18000)},
        plan="pro", credits={"has_credits": True, "unlimited": False,
                             "overage_limit_reached": False, "balance": "12.345"}))
    u = fresh().fetch()
    assert u.ok and abs(u.addon_remaining - 12.345) < 1e-9, u.addon_remaining
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True, "primary_window": win(10, 18000)},
        credits={"has_credits": True, "balance": "not-a-number"}))
    assert fresh().fetch().addon_remaining is None       # 坏串不炸，降级 None
    return "balance 串→12.345；坏串→None"


def c7_error_codes() -> str:
    """401→KEY_INVALID(登录过期文案)；403/HTML→NETWORK(Cloudflare)；429→RATE_LIMITED；
    缺 rate_limit / 双窗全 null → PARSE_EMPTY。"""
    save("codex_access_token", CODEX_TOKEN)
    cases = [
        ((401, "application/json", b'{"error":{"message":"Token expired"}}'), "KEY_INVALID"),
        ((429, "application/json", b"{}"), "RATE_LIMITED"),
        ((403, "text/html", b"<html><title>Just a moment...</title><body>cf</body></html>"),
         "NETWORK"),
        ((200, "text/html", b"<html><body>block page</body></html>"), "NETWORK"),
        ((200, "application/json", b'{"plan_type":"plus"}'), "PARSE_EMPTY"),
        ((200, "application/json",
          b'{"rate_limit":{"allowed":true,"primary_window":null,"secondary_window":null}}'),
         "PARSE_EMPTY"),
        ((500, "application/json", b'{"detail":"boom"}'), "HTTP_500"),
    ]
    for resp, want in cases:
        set_resp(lambda url, h, n, _r=resp: _r)
        u = fresh().fetch()
        assert not u.ok and u.error_code == want, (want, u.error_code, u.error_msg)
    set_resp(lambda url, h, n: (401, "application/json", b"{}"))
    u = fresh().fetch()
    assert "登录已过期" in u.error_msg and "access token" in u.error_msg
    assert CODEX_TOKEN not in u.error_msg
    set_resp(lambda url, h, n: cases[2][0])
    u2 = fresh().fetch()
    assert "Cloudflare" in u2.error_msg and "退避" in u2.error_msg   # 防重试轰炸提示
    return "7 例分码 + 401/403 文案核验"


def c8_not_configured_isolated() -> str:
    """无 codex token → not_configured 零网络；Go 侧凭据齐备也绝不共用（M11a：
    OpenAI API 侧已移除，隔离对象收敛为 opencode-go secret/文件）。"""
    save("opencode_go_key", GO_KEY)
    codex_dir = tmp_root / ".codex"
    if codex_dir.exists():
        for f in codex_dir.iterdir():
            f.unlink()
    set_resp(lambda url, h, n: usage_json({"allowed": True, "primary_window": win(1, 18000)}))
    u = fresh().fetch()
    assert not u.ok and u.error_code == "not_configured", u.error_code
    assert stub.calls == [], "无 token 不得发起任何网络请求"
    assert "Codex CLI" in u.error_msg and "access_token" in u.error_msg
    assert "local\\" in u.error_msg                          # M10b：两种放置方式提示
    # 即便 opencode auth.json 里有 go key、.codex 缺失 → 仍不得借用（credential 隔离）
    od = tmp_root / ".local" / "share" / "opencode"
    od.mkdir(parents=True, exist_ok=True)
    (od / "auth.json").write_text(json.dumps(
        {"opencode-go": {"type": "api", "key": GO_KEY}}), encoding="utf-8")
    assert auth.detect_codex_token() is None and fresh().fetch().error_code == "not_configured"
    return "not_configured + 零网络 + 与 Go 凭据完全隔离"


def c9_detect_variants() -> str:
    """detect_codex_token 五变体 + 绝不读 opencode 侧任何凭据文件。"""
    p = write_codex_auth({"auth_mode": "chatgpt",
                          "tokens": {"access_token": CODEX_TOKEN, "id_token": "x"}})
    assert auth.detect_codex_token(p) == CODEX_TOKEN
    assert auth.detect_codex_token(write_codex_auth(
        {"auth_mode": "api", "OPENAI_API_KEY": ADMIN_KEY})) is None    # 非 chatgpt 模式
    assert auth.detect_codex_token(write_codex_auth(
        {"auth_mode": "chatgpt", "tokens": {"access_token": ""}})) is None
    assert auth.detect_codex_token(write_codex_auth(
        {"auth_mode": "chatgpt", "OPENAI_API_KEY": ADMIN_KEY})) is None  # 无 tokens
    p.write_text("{broken json", encoding="utf-8")
    assert auth.detect_codex_token(p) is None                            # 损坏 JSON
    assert auth.detect_codex_token(tmp_root / "nope.json") is None       # 缺失
    assert auth.detect_codex_token(tmp_root / ".codex") is None          # 目录当文件读 → None
    return "正常/非chatgpt/空token/无tokens/损坏/缺失 → 正确 None"


def c10_cache_and_proxy() -> str:
    """60s 缓存 + fetch_now 绕缓存 + 代理路由（targets 含/不含 codex）与失败语境。"""
    save("codex_access_token", CODEX_TOKEN)
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True, "primary_window": win(10, 18000, reset_after_seconds=60)}))
    src = fresh()
    src.fetch(); src.fetch()
    assert len(stub.calls) == 1, "TTL 内命中缓存"
    src._cache_at -= cx.CACHE_TTL_SECONDS + 1
    src.fetch()
    assert len(stub.calls) == 2
    src.fetch_now()
    assert len(stub.calls) == 3, "fetch_now 绕缓存"

    # 代理在作用域 → opener 是 ProxyHandler 装配的 OpenerDirector
    cfgj = {**CFG, "network": {**CFG["network"], "proxy_enabled": True,
                               "proxy_url": PX_OK, "proxy_targets": ["codex"]}}
    (tmp_root / "config.json").write_text(json.dumps(cfgj), encoding="utf-8")
    src2 = fresh()
    src2.fetch()
    op = stub.calls[-1][2]
    assert isinstance(op, urllib.request.OpenerDirector), op
    # 不在作用域 → None（直连）
    cfgj["network"]["proxy_targets"] = ["opencode_go"]
    (tmp_root / "config.json").write_text(json.dumps(cfgj), encoding="utf-8")
    fresh().fetch()
    assert stub.calls[-1][2] is None
    # 代理开着但连接被拒 → NETWORK msg 带「代理已启用」语境
    cfgj["network"]["proxy_targets"] = ["codex"]
    (tmp_root / "config.json").write_text(json.dumps(cfgj), encoding="utf-8")
    set_resp(lambda url, h, n: urllib.error.URLError(
        ConnectionRefusedError(10061, "refused @ http://u:secretP@127.0.0.1:7890")))
    u = fresh().fetch()
    assert u.error_code == "NETWORK" and "代理已启用，检查地址/软件" in u.error_msg, u.error_msg
    assert "secretP" not in u.error_msg, "代理认证段必须脱敏"
    return "TTL/fetch_now/opener 路由/代理语境+脱敏"


def c11_cf_fingerprint_headers() -> str:
    """M10b CF 指纹头：originator + Sec-Fetch 对必发；**Accept-Encoding 零发送**（H1 教训）；
    UA 保留 token-widget 身份不伪装。"""
    save("codex_access_token", CODEX_TOKEN)
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True, "primary_window": win(10, 18000)}))
    u = fresh().fetch()
    assert u.ok, (u.error_code, u.error_msg)
    h = {k.lower(): v for k, v in stub.calls[0][1].items()}
    assert h["originator"] == "codex_cli_rs", "缺 originator → CF challenge 403（矩阵定案）"
    assert h["sec-fetch-mode"] == "cors" and h["sec-fetch-dest"] == "empty", h
    assert h["accept"] == "application/json"
    assert h["user-agent"] == cx.UA and "token-widget" in h["user-agent"]
    assert h["authorization"] == "Bearer " + CODEX_TOKEN
    assert "accept-encoding" not in h, "禁止显式发 Accept-Encoding（gzip 体不解码）"
    return "originator+Sec-Fetch 对/无 AE/UA 身份保留"


def c12_find_codex_auth_variants() -> str:
    """find_codex_auth 四路径变体（temp 伪造）：优先级/损坏跳过/不合格跳过/全缺 None；
    默认候选序结构 + 候选①local\\auth.json 的 source 级集成。"""
    good = {"auth_mode": "chatgpt", "tokens": {"access_token": CODEX_TOKEN}}
    bad = {"auth_mode": "api", "OPENAI_API_KEY": ADMIN_KEY}

    def mk(name: str, payload) -> Path:
        f = tmp_root / name
        f.write_text(json.dumps(payload) if payload is not None else "{broken json",
                     encoding="utf-8")
        return f

    local, root, home = mk("f_local.json", good), mk("f_root.json", good), \
        mk("f_home.json", good)
    assert auth.find_codex_auth([local, root, home]) == (CODEX_TOKEN, local)
    local.write_text("{broken json", encoding="utf-8")                    # 损坏 → 跳过
    assert auth.find_codex_auth([local, root, home])[1] == root
    root.write_text(json.dumps(bad), encoding="utf-8")                    # 不合格 → 跳过
    assert auth.find_codex_auth([local, root, home])[1] == home
    home.write_text(json.dumps(bad), encoding="utf-8")
    assert auth.find_codex_auth([local, root, home]) is None, "全不合格 → None"
    assert auth.find_codex_auth([tmp_root / "nope_a.json", tmp_root / "nope_b.json"]) \
        is None, "全缺 → None"
    assert auth.find_codex_auth([]) is None
    for f in (local, root, home):
        f.unlink()
    cands = auth.codex_auth_candidates()     # 默认序：local → 项目根/exe 同级 → ~/.codex
    assert cands == [tmp_root / "auth.json", (tmp_root.parent / "auth.json"),
                     tmp_root / ".codex" / "auth.json"], cands
    (tmp_root / "auth.json").write_text(json.dumps(good), encoding="utf-8")
    try:                                                   # source 集成：候选①命中即采
        set_resp(lambda url, h, n: usage_json(
            {"allowed": True, "primary_window": win(10, 18000)}))
        u = fresh().fetch()
        assert u.ok and stub.calls[0][1]["Authorization"] == "Bearer " + CODEX_TOKEN
    finally:
        (tmp_root / "auth.json").unlink()
    return "优先级/损坏/不合格/全缺 4 变体 + 默认候选序 + source 集成"


def c13_reset_credits_note_pii() -> str:
    """M10b：rate_limit_reset_credits → note「窗口重置券：可用 x」（无/0/坏 → 不显）；
    PII（user_id/account_id/email）零入 Usage。"""
    save("codex_access_token", CODEX_TOKEN)

    def body(rlrc, **top) -> tuple[int, str, bytes]:
        j: dict = {"plan_type": "plus",
                   "rate_limit": {"allowed": True, "primary_window": win(10, 18000)}}
        if rlrc is not None:
            j["rate_limit_reset_credits"] = rlrc
        j.update(top)
        return 200, "application/json", json.dumps(j).encode()

    set_resp(lambda url, h, n: body({"available_count": 1, "applicable_available_count": 0}))
    u = fresh().fetch()
    assert u.ok and u.note == "窗口重置券：可用 1", u.note
    set_resp(lambda url, h, n: body({"available_count": 2, "applicable_available_count": 2}))
    assert fresh().fetch().note == "窗口重置券：可用 2"
    for rlrc in (None, {}, {"available_count": 0}, {"available_count": -1},
                 {"available_count": "x"}, {"available_count": True},
                 {"applicable_available_count": 3}):
        set_resp(lambda url, h, n, _b=body(rlrc): _b)
        assert fresh().fetch().note is None, rlrc
    set_resp(lambda url, h, n: body(
        {"available_count": 1}, user_id="user-123", account_id="acct-9",
        email="a@b.c", promo=None))
    u = fresh().fetch()
    blob = json.dumps(u.__dict__, default=str)
    assert u.ok and u.note == "窗口重置券：可用 1"
    for pii in ("user-123", "acct-9", "a@b.c"):
        assert pii not in blob, f"PII 入 Usage：{pii}"
    return "reset 券正反例 + PII 零入库"


# ------------------------------------------------------ 面板 / UI（Tk）----

def _all_texts(w, out):
    try:
        t = w.cget("text")
        if isinstance(t, str) and t:
            out.append(t)
    except tk.TclError:
        pass
    if isinstance(w, tk.Entry):
        try:
            out.append(w.get())
        except tk.TclError:
            pass
    for ch in w.winfo_children():
        _all_texts(ch, out)
    return out


def text_items(app):
    c = app.canvas
    return [(c.itemcget(i, "text"), str(c.itemcget(i, "fill")).lower())
            for i in c.find_all() if c.type(i) == "text"]


def texts_join(app) -> str:
    return " | ".join(str(t) for t, _ in text_items(app))


def fill_of(app, substr) -> str:
    for t, fill in text_items(app):
        if substr in str(t):
            return fill
    raise AssertionError(f"画布无文案：{substr!r}")


def feed(app, *usages):
    app.sched.events.put(("update", list(usages),
                          {"next_delay": 300, "ts": time.time(), "low": False}))
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)


def u_ok_codex(**kw) -> Usage:
    base = dict(provider="codex", ok=True, spec="plus", unit="percent",
                pct_used=0.62, resets_at=_NOW + timedelta(hours=2, minutes=1),
                windows=[Window("5h", 0.62, _NOW + timedelta(hours=2, minutes=1)),
                         Window("周", 0.30, _NOW + timedelta(days=4))],
                addon_remaining=12.345)
    base.update(kw)
    return Usage(**base)


def p1_codex_checkbox_and_scope(app, root) -> str:
    clear_secrets()
    panel = settings_panel.SettingsPanel(app)
    panel.withdraw()
    texts = _all_texts(panel, [])
    assert any(t == "Codex" for t in texts), "M12②：Codex 复选框（标签已去实验性后缀）"
    assert not any("Codex（实验性）" in t for t in texts)
    assert sum(1 for t in texts if "点击配置" in t) == 3, "三行旁注（M11a -OpenAI）"
    assert not any("OpenAI" in t for t in texts), "M11a：OpenAI 行应已移除"
    assert panel.chk_px_cx.cget("text") == "Codex", "代理作用域含 codex"
    assert panel.var_px_cx.get() is True, "CFG 两目标全在作用域"
    # 无凭据勾选 codex → 自动弹其绑定面板
    panel._pvars["codex"].set(True)
    panel._on_provider_toggle("codex")
    kp = app._key_panels.get("codex")
    assert kp is not None and kp.alive() and kp.provider == "codex"
    saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
    assert saved["enabled_providers"] == ["bailian", "codex"], saved
    kp.close_card()
    # 勾选 codex 但作用域取消 codex → targets 无 codex
    panel.var_px_cx.set(False)
    panel._save_net()
    saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
    assert saved["network"]["proxy_targets"] == ["opencode_go"], saved["network"]
    panel.destroy()
    app.cfg["enabled_providers"] = ["bailian"]
    return "Codex框/勾选即弹/作用域可去 codex（M11a 剩两项）"


def p2_key_panel_codex_flow(app, root) -> str:
    clear_secrets()
    set_resp(lambda url, h, n: usage_json(
        {"allowed": True, "primary_window": win(40, 18000,
                                                reset_after_seconds=3600)}))
    # 检测行：伪造 ~/.codex/auth.json（chatgpt 模式）→ M10b 升级「已自动检测：<路径>（尾4）」
    write_codex_auth({"auth_mode": "chatgpt",
                      "tokens": {"access_token": CODEX_TOKEN}})
    panel = settings_panel.ProviderKeyPanel(app, "codex")
    panel.withdraw()
    det = panel.lbl_detect.cget("text")
    assert "已自动检测" in det and ".codex" in det and CODEX_TOKEN[-4:] in det, det
    assert CODEX_TOKEN not in det, "检测行仅尾 4 位"
    assert any("实验性" in t for t in _all_texts(panel, [])), "面板需标实验性"
    assert any("非官方接口" in t or "随时失效" in t for t in _all_texts(panel, []))
    # 手动粘贴 → 保存即刻清空 → fetch_now 验证（绿字，窗口 label 5h）
    panel.ent_key.insert(0, CODEX_TOKEN)
    panel._save()
    assert panel.ent_key.get() == "", "保存后即刻清空"
    assert auth.load_secret("codex_access_token") == CODEX_TOKEN
    panel._validate()
    st = panel.status.cget("text")
    assert "验证成功" in st and "5h" in st and "40%" in st, st
    assert panel.status.cget("fg").lower() == OK.lower()
    for t in _all_texts(panel, []):
        assert CODEX_TOKEN not in t, "面板任何文本不回显 token"
    panel.destroy()
    # secret 已存 → 检测行显「手动绑定」优先级（覆盖文件检测）
    pm = settings_panel.ProviderKeyPanel(app, "codex")
    pm.withdraw()
    assert "手动" in pm.lbl_detect.cget("text"), pm.lbl_detect.cget("text")
    pm.destroy()
    # 无 secret + 候选均不合格 → 三候选缺失提示；空输入保存 → 提示粘贴
    clear_secrets()
    write_codex_auth({"auth_mode": "api", "OPENAI_API_KEY": ADMIN_KEY})
    p2 = settings_panel.ProviderKeyPanel(app, "codex")
    p2.withdraw()
    det2 = p2.lbl_detect.cget("text")
    assert "三候选均未找到" in det2 and "local\\" in det2 and "Codex CLI" in det2, det2
    p2._save()
    assert "还没有粘贴内容" in p2.status.cget("text")
    p2.destroy()
    # 候选①local\auth.json 命中 → 检测行显示其相对路径
    (tmp_root / "auth.json").write_text(json.dumps(
        {"auth_mode": "chatgpt", "tokens": {"access_token": CODEX_TOKEN}}),
        encoding="utf-8")
    try:
        p3b = settings_panel.ProviderKeyPanel(app, "codex")
        p3b.withdraw()
        det3 = p3b.lbl_detect.cget("text")
        assert "已自动检测" in det3 and "auth.json" in det3 and CODEX_TOKEN[-4:] in det3, det3
        assert CODEX_TOKEN not in det3
        p3b.destroy()
    finally:
        (tmp_root / "auth.json").unlink()
    return "检测行三态(手动/自动+路径/三候选缺失)/保存清空/验证绿字/全程不回显"


def _rect_fills(app, fill_hex) -> list[tuple[float, ...]]:
    """按填充色收集矩形 bbox（进度条 track/fill 都是 _pill 中的中段矩形）。"""
    c = app.canvas
    return [c.bbox(i) for i in c.find_all()
            if c.type(i) == "rectangle"
            and str(c.itemcget(i, "fill")).lower() == fill_hex]


def p3_ui_rows_tooltip(app, root) -> str:
    # ===== M14 双主条形态：5h/周各一块「文字行+等尺寸条」，固定槽（M11d）上 5h 下 周 =====
    u = u_ok_codex()                                   # [5h .62, 周 .30]，无 note
    feed(app, u)
    labels = texts_join(app)
    items = [str(t) for t, _ in text_items(app)]
    assert "Codex" in labels, labels                   # NAMES 行名
    assert "PLUS" in labels, "spec 徽章大写化：" + labels
    assert "38%" in labels, "大数字=剩余占比(1-最紧窗 62%)"
    # 块1（5h 主条，M11d① 固定槽+② 去「窗」）：「5h · 已用 x%」+右侧粗体倒计时
    assert "5h · 已用 62.0%" in labels, labels
    assert not any(t.startswith(("5h 窗口", "周 窗口")) for t in items), \
        "codex 行不得再有「X 窗口 · 已用」旧拼接"
    # 块2（M14 周升等尺寸主条）：完全对称的「周窗 · 已用 x%」+独立倒计时
    assert "周窗 · 已用 30.0%" in labels, labels
    cds = [t for t in items if t.endswith("后重置")]
    assert len(cds) == 2, f"两窗各一条倒计时：{cds}"
    # 图文语法对称：两文字行同字档（f_tiny），两倒计时同粗档（f_small_b）——
    # 周不再是副显（旧细条 f_note 尾注字档随 M14 退场）
    c = app.canvas
    def font_of(txt_start):
        it = next(i for i in c.find_all() if c.type(i) == "text"
                  and str(c.itemcget(i, "text")).startswith(txt_start))
        return str(c.itemcget(it, "font"))
    assert font_of("5h · 已用") == font_of("周窗 · 已用") == str(app.f_tiny), "左文字行同档"
    assert all(font_of(x) == str(app.f_small_b) for x in cds), "倒计时同为粗档"
    # 双主条等尺寸与间距（M14）：轨道 bbox 高差 ≤1px；行距 pitch=28、条-条空隙=19
    # （空隙 = CODEX_TXT_BAR(7 文→条) + CODEX_GAP(12 条底→下块文) = 19，远大于旧细条 2.6）
    tracks = sorted(_rect_fills(app, "#e3d3a9"), key=lambda b: b[1])
    assert len(tracks) == 2, tracks
    assert abs((tracks[0][3] - tracks[0][1]) - (tracks[1][3] - tracks[1][1])) <= 1.0, \
        "两主条等高（同高同圆角同空轨语言）"
    pitch = tracks[1][1] - tracks[0][1]
    assert abs(pitch - 28 * app.S) <= 2.0, f"块行距 pitch={pitch:.1f} 应≈28·S"
    bar_gap = tracks[1][1] - tracks[0][3]
    assert abs(bar_gap - (CODEX_TXT_BAR + CODEX_GAP) * app.S) <= 2.0, \
        f"条-条空隙 {bar_gap:.1f} 应=(7+12)·S−2 容差"
    # 两根条并存：绿色填充（5h .62→剩38%、周 .30→剩70% 均正常档）恰 2 根
    assert len(_rect_fills(app, "#3bc371")) == 2, "两根主条（各窗独立阈值着色）"
    h2w = float(app.canvas.cget("height"))
    # —— other:N 行内不显（tooltip 仍全列），且不占高度 ——
    uo = u_ok_codex(windows=[Window("5h", 0.62, _NOW + timedelta(hours=2, minutes=1)),
                             Window("周", 0.30, _NOW + timedelta(days=4)),
                             Window("other:21600", 0.42, _NOW + timedelta(hours=6))])
    feed(app, uo)
    assert "other" not in texts_join(app), "other:N 行内不得出现"
    assert float(app.canvas.cget("height")) == h2w, "other:N 不得占高度"
    assert "other:21600 窗口：已用 42.0%" in app._tip_text(
        {"u": uo, "err": None, "stale": False}), "tooltip 仍须全列未知窗"
    # —— 阈值色独立判定：周窗逼近红线而 5h 窗仍绿 ——
    uc = u_ok_codex(windows=[Window("5h", 0.62, _NOW + timedelta(hours=2, minutes=1)),
                             Window("周", 0.96, _NOW + timedelta(days=4))])
    feed(app, uc)
    assert len(_rect_fills(app, "#3bc371")) == 1, "5h 主条应仍绿"
    assert len(_rect_fills(app, "#ef0000")) == 1, "周主条应红（剩 4%<5%，各窗独立判）"
    # —— M11d① 固定槽：周更紧时 5h 仍是块1（上）、周恒块2（下）——几何序锁 ——
    ut = u_ok_codex(pct_used=0.80,
                    windows=[Window("周", 0.80, _NOW + timedelta(days=4)),
                             Window("5h", 0.62, _NOW + timedelta(hours=2, minutes=1))])
    feed(app, ut)
    tl = texts_join(app)
    assert "5h · 已用 62.0%" in tl, "固定槽：5h 恒块1（即便周更紧）"
    assert "周窗 · 已用 80.0%" in tl, "周恒块2（等尺寸主条块，非副显）"
    cv = app.canvas

    def top_of(txt_start):
        return min(cv.bbox(i)[1] for i in cv.find_all()
                   if cv.type(i) == "text"
                   and str(cv.itemcget(i, "text")).startswith(txt_start))

    assert top_of("5h · 已用") < top_of("周窗 · 已用"), "槽序：5h 上、周 下"
    assert "38%" in tl and "20%" not in tl, "大数字随主条窗(5h剩38%)非最紧窗(周剩20%)"
    # —— 单窗：仅一块；M14 双窗与单窗等高（第二条落在旧细条+C 行空档）——
    u1 = u_ok_codex(windows=[Window("周", 0.30, _NOW + timedelta(days=4))])
    feed(app, u1)
    h1w = float(app.canvas.cget("height"))
    assert "周窗 · 已用 30.0%" in texts_join(app), "缺 5h：周升块1（递补）"
    u5 = u_ok_codex(windows=[Window("5h", 0.62, _NOW + timedelta(hours=2))])
    feed(app, u5)
    assert "5h · 已用 62.0%" in texts_join(app)
    assert float(app.canvas.cget("height")) == h1w, "无周：5h 留块1，行高同单边"
    assert h2w == h1w, (h1w, h2w, "M14：两窗/单窗等高（ROW_FULL=100 内收双条）")
    # ============ 重置券角标：有券显「券×N」，无券零占位（高度不变） ============
    feed(app, u)                                        # 无 note 基线
    assert not any(t.startswith("券×") for t in
                   [str(x) for x, _ in text_items(app)]), "无券不得占位"
    assert "窗口重置券" not in texts_join(app)
    un = u_ok_codex(note="窗口重置券：可用 2")
    feed(app, un)
    assert "券×2" in [str(x) for x, _ in text_items(app)], "角标缺数"
    assert fill_of(app, "券×2") == SOFT.lower(), "M11c②：券与 PLUS 同档灰褐（配角不争墨）"
    assert float(app.canvas.cget("height")) == h2w, "角标在 A 行徽章位，零高度增量"
    tk_hits = [z for z in app.hits if isinstance(z[4], dict)
               and "重置券" in z[4].get("tip", "")]
    assert len(tk_hits) == 1 and "券 ×2" in tk_hits[0][4]["tip"], tk_hits
    tip = app._tip_text({"u": un, "err": None, "stale": False})
    assert "窗口重置券：可用 2" in tip, tip              # 行 tooltip 的 note 行保留
    # 券角标热区 hover → 说明 tooltip（_tip_text 固定文案支路）
    assert app._tip_text({"tip": tk_hits[0][4]["tip"]}) == tk_hits[0][4]["tip"]
    # ============ 积分复用位：不进加油包条（两条都是窗口条）+ tooltip 单列 ============
    feed(app, u)
    tip = app._tip_text({"u": u, "err": None, "stale": False})
    assert "积分余额 $12.35（实验性源）" in tip, tip
    assert "加油包" not in tip and "7 天周期" not in tip, tip
    assert "5h 窗口：已用 62.0%" in tip and "周 窗口：已用 30.0%" in tip, tip
    h1 = float(app.canvas.cget("height"))
    feed(app, u_ok_codex(addon_remaining=None))
    assert float(app.canvas.cget("height")) == h1, "积分不进加油包条占位"
    # ============ KEY_INVALID 错误行（无历史）：橙档 + msg 续期文案 + 按钮开面板 ====
    import types as _t
    app.last_good.clear()
    feed(app, Usage(provider="codex", ok=False, unit="percent",
                    error_code="KEY_INVALID", error_msg="登录已过期，重新获取 access token"))
    assert fill_of(app, "凭据已失效") == ORANGE.lower()
    assert "登录已过期" in texts_join(app)                 # msg 行透传续期文案
    assert "配置密钥…" in texts_join(app)
    # M7-b 后 clicks[0]=刷新图标热区 → 遍历全部点击热区合成"原地松开"，
    # 期望其中一个（凭据行 pill）打开 Codex 绑定面板。
    for z in list(app.clicks):
        ev = _t.SimpleNamespace(x_root=0, y_root=0,
                                x=(z[0] + z[2]) / 2, y=(z[1] + z[3]) / 2)
        app._press_xy = (0, 0)
        app._drag_end(ev)
        kp0 = app._key_panels.get("codex")
        if kp0 is not None and kp0.alive():
            break
    kp = app._key_panels.get("codex")
    assert kp is not None and kp.alive(), "错误行按钮应开 Codex 绑定面板"
    kp.close_card()
    # stale（有历史+失败）：双条保留但整体降灰，券角标同降灰
    feed(app, u)                                          # 重建 last_good
    feed(app, Usage(provider="codex", ok=False, unit="percent",
                    error_code="NETWORK", error_msg="x"))
    assert "5h · 已用 62.0%" in texts_join(app), "stale 行保留双条"
    assert len([i for i in _rect_fills(app, "#3bc371")]) == 0, "stale 条须降灰非彩色"
    # ============ 纯函数面：cli/徽章/积分条抑制/M11b 取数 ============
    row = cli_mod._row(u_ok_codex())
    assert "credits $12.35" in row[-1] and "addon" not in row[-1], row
    assert spec_display(u) == "PLUS" and spec_display(Usage(provider="bailian", ok=True,
                                                            spec="pro")) == "Pro"
    assert _tip_credits(u) == "积分余额 $12.35（实验性源）"
    assert addon_bar_state(u_ok_codex())[0] is False, "codex 不画加油包细条"
    assert addon_bar_state(Usage(provider="bailian", ok=True, addon_remaining=10.0))[0] \
        is True, "百炼加油包逻辑不变"
    m_, s_ = codex_bars(u_ok_codex())
    assert m_ is not None and m_.label == "5h" and s_ is not None and s_.label == "周"
    m_, s_ = codex_bars(ut)
    assert m_.label == "5h" and s_.label == "周", "M11d 固定槽：周更紧也不换位"
    m_, s_ = codex_bars(u1)
    assert m_.label == "周" and s_ is None, "缺位递补：无 5h 周升主条；单窗零副条"
    assert codex_bars(Usage(provider="codex", ok=True, unit="percent",
                            windows=[Window("other:21600", 0.5, None)])) == (None, None), \
        "全未知窗 → 回落通用渲染"
    assert codex_ticket_count(un) == 2
    assert codex_ticket_count(u_ok_codex()) is None, "无 note → 无角标"
    assert codex_ticket_count(Usage(provider="bailian", ok=True,
                                    note="窗口重置券：可用 5")) is None, "仅 codex"
    assert codex_ticket_count(u_ok_codex(note="窗口重置券：可用 x")) is None, "解析失败宁缺"
    assert codex_win_caption("周") == "周窗" and codex_win_caption("5h") == "5h", \
        "M11d②：5h 去「窗」"
    assert codex_win_caption("周窗") == "周窗", "短名幂等"
    return "M14 双等尺寸主条（块对称/等高/条-条19·S/独立阈值色/other不显/固定槽序/"\
           "单双窗等高）+券SOFT角标零占位+错误行+纯函数 全中"


def p4_bailian_untouched(app, root) -> str:
    """结构断言：M10 零触碰百炼三件 + scheduler + base + go source；
    M11a：OpenAI source/测试件确已删除、registry 不再引用。"""
    for rel in ("src/sources/bailian.py", "src/sources/bailian_gateway.py",
                "src/scheduler.py", "src/sources/base.py",
                "src/sources/opencode_go.py",
                "src/registry.py", "main.py"):
        blob = (ROOT / rel).read_text(encoding="utf-8").lower()
        if rel == "src/registry.py":
            assert "codex" in blob, "registry 应注册 codex"     # 唯一合法接入点
            assert "openaisource" not in blob, "M11a：registry 不应再注册 OpenAI"
            assert "sources.openai" not in blob, "M11a：registry 不应再 import openai"
            continue
        assert "codex" not in blob, rel
    assert not (ROOT / "src" / "sources" / "openai.py").exists(), "M11a：openai.py 应已删除"
    assert not (ROOT / "tests" / "test_m6_openai.py").exists(), "M11a：openai 套件应已删除"
    assert "openai_admin_key" not in (ROOT / "src" / "auth.py").read_text(encoding="utf-8") \
        .split("SECRET_NAMES = (")[1].split(")")[0], "SECRET_NAMES 应已去 openai 两枚"
    # auth.py 允许 codex（detect 所在）：仅函数级增量，不 import 任何源
    a = (ROOT / "src/auth.py").read_text(encoding="utf-8")
    assert "detect_codex_token" in a and "detect_go_key" in a
    assert "import urllib" not in a, "auth 不发网络、不读 .codex 以外凭据文件"
    return "7 文件结构核验 + openai 删除三证"


CASES_SOURCE = [
    ("windows_normal", c1_windows_normal),
    ("primary_week_other", c2_windows_no_5h_primary_week_other),
    ("tightest_first", c3_tightest_first_sort),
    ("allowed_clamp", c4_allowed_false_clamp),
    ("reset_forms", c5_reset_forms),
    ("credits_float", c6_credits_balance_float),
    ("error_codes", c7_error_codes),
    ("not_configured_isolated", c8_not_configured_isolated),
    ("detect_variants", c9_detect_variants),
    ("cache_proxy", c10_cache_and_proxy),
    ("cf_fingerprint_headers", c11_cf_fingerprint_headers),
    ("find_codex_auth_variants", c12_find_codex_auth_variants),
    ("reset_credits_note_pii", c13_reset_credits_note_pii),
]


def blocked(url, headers, data=None):
    _net.append(str(url)[:80])
    raise AssertionError("真实网络请求被拦截（测试违规）")


def clear_secrets():
    for p in list(tmp_root.glob("*.dpapi")) + [tmp_root / "config.json"]:
        try:
            p.unlink()
        except OSError:
            pass


def snapshot_dirs() -> tuple[dict, dict]:
    def sha(d: Path):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(d.glob("*")) if p.is_file()}
    real_codex = Path(os.environ.get("USERPROFILE") or str(Path.home())) / ".codex"
    return sha(REAL_LOCAL), (sha(real_codex) if real_codex.is_dir() else {})


_orig_userprofile: str | None = None


def run(tmp: Path) -> int:
    global tmp_root, _orig_userprofile
    tmp_root = tmp
    checks: list[tuple[str, bool, str]] = []
    _net.clear()

    def case(name, fn):
        print(f"· {name} …", flush=True)
        clear_secrets()
        try:
            note = fn() or ""
            checks.append((name, True, note))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:240]))

    orig = (auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE,
            config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            cx._req, og._req, gw._req, os.environ.get("USERPROFILE"))
    before_local, before_codex = snapshot_dirs()
    auth.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = tmp / "bailian_cookie.dpapi"
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    _orig_userprofile = os.environ.get("USERPROFILE")
    os.environ["USERPROFILE"] = str(tmp)            # detect 默认路径重定向到伪造区
    cx._req = stub
    og._req = blocked                               # go 源在本任务不可达（触达=违规）
    gw._req = blocked
    root = app = None
    try:
        for name, fn in CASES_SOURCE:
            case(name, fn)
        main_mod.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        sched = Scheduler([], poll_seconds=300)
        app = NoteApp(root, dict(CFG), sched, state=dict(DEFAULTS))
        root.withdraw()
        for name, fn in (("panel_checkbox_scope", p1_codex_checkbox_and_scope),
                         ("panel_key_flow", p2_key_panel_codex_flow),
                         ("ui_rows", p3_ui_rows_tooltip),
                         ("untouched", p4_bailian_untouched)):
            print(f"· {name} …", flush=True)
            clear_secrets()
            try:
                note = fn(app, root) or ""
                checks.append((name, True, note))
            except Exception as e:                  # noqa: BLE001
                checks.append((name, False, repr(e)[:240]))
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
    after_local, after_codex = snapshot_dirs()
    checks.append(("NET_零真实网络（拦截线未触发）", not _net, "; ".join(_net)))
    checks.append(("GUARD_real_local_untouched", after_local == before_local, ""))
    checks.append(("GUARD_real_codex_auth_untouched", after_codex == before_codex, ""))
    bad = [c for c in checks if not c[1]]
    print()
    for name, okflag, note in checks:
        print(f"  {'PASS' if okflag else 'FAIL':4} {name} {note}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    import tempfile
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="m10_cx_") as d:
        raise SystemExit(run(Path(d)))
