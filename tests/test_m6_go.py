"""M6 OpenCode Go source + 通用 secret + 绑定面板/两 unit 行渲染 验收。

运行：`python tests\\test_m6_go.py`（需可用桌面会话；窗口全程 withdraw）。
fixture 驱动零真实网络（用户尚无 key，验收=离线规格对点，wire spec §3.5）：
- opencode_go._req / codex._req（M11a 改点：原 openai 桩位）/ gw._req 全程打桩
  （真实 HTTP 到达=违规）；
- auth.LOCAL_DIR / BAILIAN_COOKIE_FILE / config / state 全重定向 temp；
- detect_go_key 经 USERPROFILE 重定向读伪造 auth.json（真实文件只读不碰）；
- 真实 local\\ 前后（名+SHA-256）比对守护；
- 面板断言：保存即清空、任何控件文本永不含 key 值、验证结果配色分档。
覆盖（任务书 F）：双字段变体（percent|usagePercent、resetsAt ISO|epoch、resetInSec）、
EntitlementError 403 body 判定、Zen key 绝不自动采用、rate-limited→100%、weekly 缺省
不渲染、auth 通用 secret 往返+原子性、设置面板新控件渲染/保存/清空/不回显、ui 两 unit 行渲染。
M11a（2026-09-15）：OpenAI API 侧移除——本套件 openai 面板两案例（s2/s3）原地改造为
Codex 面板形态样本；s1 勾选对象与旁注计数同步（4→3）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import types
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import auth, config as config_mod                                # noqa: E402
from src import settings_panel                                            # noqa: E402
from src import state as state_mod                                        # noqa: E402
from src.scheduler import Scheduler                                       # noqa: E402
from src.sources import bailian_gateway as gw                             # noqa: E402
from src.sources import codex as cx                                       # noqa: E402
from src.sources import opencode_go as og                                 # noqa: E402
from src.sources.base import Usage, Window                                # noqa: E402
from src.state import DEFAULTS                                            # noqa: E402
from src.ui import (CRED_ERRORS, FAINT, INK, OK, ORANGE, SOFT, STALE,     # noqa: E402
                    NoteApp)
import main as main_mod                                                   # noqa: E402

REAL_LOCAL = ROOT / "local"
GO_KEY = "go-FAKE-key-12345678-TAIL"
ZEN_KEY = "sk-zen-NEVER-USE-9999"
CX_TOKEN = "eyJ-cxFAKE-abcdefg0123456789-TAIL"     # M11a：s2/s3 Codex 面板样本用

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian"],
       "opencode_go": {"auto_detect": True}}

tmp_root: Path = Path()          # run() 填充
_net: list[str] = []             # 违规网络记录


# ---------------- 传输层替身（openai/go 共用；记录调用供零网络断言） ----------------

class Stub:
    """可调用替身：_req(url, headers) → responder(url, headers, n)。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.responder = None

    def __call__(self, url: str, headers: dict, opener=None):
        # opener（M8 代理形参）：本套件默认直连，仅吸收；路由断言见 test_m8_proxy.py
        n = len(self.calls)
        self.calls.append((url, dict(headers)))
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


def go_body(obj) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(obj).encode()


def usage_json(rolling, weekly=None, monthly=None):
    u = {"rolling": rolling}
    if weekly is not None:
        u["weekly"] = weekly
    if monthly is not None:
        u["monthly"] = monthly
    return go_body({"usage": u})


def fresh_go() -> og.OpenCodeGoSource:
    return og.OpenCodeGoSource()


def write_auth_json(payload) -> None:
    p = tmp_root / ".local" / "share" / "opencode"
    p.mkdir(parents=True, exist_ok=True)
    (p / "auth.json").write_text(json.dumps(payload), encoding="utf-8")


def key_never_leaks(*texts: str) -> None:
    for t in texts:
        for k in (GO_KEY, ZEN_KEY, CX_TOKEN):
            if k and len(k) > 4:
                assert k not in (t or ""), f"泄露 key 值：{t[:60]}"


# ---------------------------------------------------- Go source 用例 ----

def g1_api_variant_iso():
    """spec §2.2 API 变体：percent + resetsAt ISO（小数秒/Z 尾缀）；weekly 同构进 windows。"""
    auth.save_secret("opencode_go_key", GO_KEY)
    iso = "2026-09-11T18:30:00.123456Z"
    set_resp(lambda url, h, n: usage_json(
        {"percent": 42.5, "status": "ok", "resetsAt": iso},
        weekly={"percent": 12, "resetsAt": iso}))
    u = fresh_go().fetch()
    assert u.ok and u.unit == "percent", (u.error_code, u.error_msg)
    assert u.total is None and u.remaining is None, "%语义无绝对额"
    assert abs(u.pct_used - 0.425) < 1e-9, u.pct_used          # 0..100 → 0..1
    assert [w.label for w in u.windows] == ["rolling", "weekly"], u.windows
    assert u.resets_at == datetime.fromisoformat(iso.replace("Z", "+00:00"))
    assert u.resets_at.tzinfo is not None
    assert stub.calls[0][1]["Authorization"] == "Bearer " + GO_KEY
    return "percent 42.5→0.425；ISO 带小数秒解析；weekly 进 windows"


def g2_dashboard_variant():
    """Web dashboard 变体兼容兜底：usagePercent + resetInSec（倒计时秒）。"""
    auth.save_secret("opencode_go_key", GO_KEY)
    set_resp(lambda url, h, n: usage_json({"usagePercent": 37.0, "resetInSec": 3600}))
    before = time.time()
    u = fresh_go().fetch()
    assert u.ok and abs(u.pct_used - 0.37) < 1e-9, u.pct_used
    assert len(u.windows) == 1 and u.windows[0].label == "rolling"
    delta = (u.resets_at - datetime.now(timezone.utc)).total_seconds()
    assert 3590 < delta < 3610, (before, delta)
    return "usagePercent 37→0.37；resetInSec→now+3600s"


def g3_epoch_forms():
    """resetsAt epoch 双形态（>1e12 毫秒 / 秒）；percent 100→1.0、≤1 原样。"""
    auth.save_secret("opencode_go_key", GO_KEY)
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    set_resp(lambda url, h, n: usage_json(
        {"percent": 100, "resetsAt": now.timestamp()},
        monthly={"percent": 0.5, "resetsAt": now.timestamp() * 1000}))
    u = fresh_go().fetch()
    assert u.ok and u.pct_used == 1.0, u.pct_used
    assert abs(u.resets_at - now) < timedelta(seconds=2), u.resets_at
    m = u.windows[1]
    assert abs(m.resets_at - now) < timedelta(seconds=2), m.resets_at   # 毫秒形态
    assert abs(m.pct_used - 0.5) < 1e-9, m.pct_used                     # ≤1 不 /100
    return "epoch 秒/毫秒双兼容；100→1.0"


def g4_rate_limited():
    """status=="rate-limited" → pct=1.0（即使 percent 更小）。"""
    auth.save_secret("opencode_go_key", GO_KEY)
    set_resp(lambda url, h, n: usage_json({"percent": 3.0, "status": "rate-limited"}))
    u = fresh_go().fetch()
    assert u.ok and u.pct_used == 1.0, u.pct_used
    return "rate-limited → 100%"


def g5_rolling_missing_and_badjson():
    """rolling 必存在；非 JSON → PARSE_EMPTY。"""
    auth.save_secret("opencode_go_key", GO_KEY)
    set_resp(lambda url, h, n: go_body({"usage": {"weekly": {"percent": 1}}}))
    u = fresh_go().fetch()
    assert not u.ok and u.error_code == "PARSE_EMPTY", u.error_code
    set_resp(lambda url, h, n: (200, "text/html", b"<html><body>not json"))
    u2 = fresh_go().fetch()
    assert not u2.ok and u2.error_code == "PARSE_EMPTY", u2.error_code
    key_never_leaks(u.error_msg or "", u2.error_msg or "")
    return "缺 rolling / 非 JSON → PARSE_EMPTY"


def g6_entitlement_403():
    """spec §2.4：403 必须解析 body；EntitlementError→NO_SUBSCRIPTION，其他 403 另归。"""
    auth.save_secret("opencode_go_key", GO_KEY)
    ent = (403, "application/json", json.dumps(
        {"error": {"type": "EntitlementError", "message": "no subscription"}}).encode())
    set_resp(lambda url, h, n: ent)
    u = fresh_go().fetch()
    assert u.error_code == "NO_SUBSCRIPTION", (u.error_code, u.error_msg)
    assert "无 OpenCode Go 订阅" in u.error_msg
    set_resp(lambda url, h, n: (403, "text/html",
                                b"<html><title>Access denied by WAF</title></html>"))
    u2 = fresh_go().fetch()
    assert u2.error_code == "HTTP_403" and u2.error_code != "NO_SUBSCRIPTION", u2.error_code
    assert "WAF" in (u2.error_msg or "") or "Access" in (u2.error_msg or "")   # title 前 80
    key_never_leaks(u.error_msg or "", u2.error_msg or "")
    return "EntitlementError→NO_SUBSCRIPTION；其他 403→HTTP_403（title 提示）"


def g7_401_429():
    auth.save_secret("opencode_go_key", GO_KEY)
    set_resp(lambda url, h, n: (401, "application/json", go_body(
        {"error": {"message": "Invalid key"}})))
    u = fresh_go().fetch()
    assert u.error_code == "KEY_INVALID", u.error_code
    set_resp(lambda url, h, n: (429, "application/json", b"{}"))
    u2 = fresh_go().fetch()
    assert u2.error_code == "RATE_LIMITED", u2.error_code
    assert u2.unit == "percent"
    key_never_leaks(u.error_msg or "", u2.error_msg or "")
    return "401→KEY_INVALID；429→RATE_LIMITED"


def g8_not_configured_zero_net():
    """无 secret 且检测不到 → not_configured（附粘贴/登录提示），零网络。"""
    write_auth_json({})
    set_resp(lambda url, h, n: usage_json({"percent": 1}))
    u = fresh_go().fetch()
    assert not u.ok and u.error_code == "not_configured", u.error_code
    assert "Go key" in u.error_msg and "opencode" in u.error_msg
    assert stub.calls == [], "无 key 不得发起网络请求"
    return "not_configured + 提示粘贴/登录 + 零网络"


def g9_zen_key_never_auto():
    """红线：auth.json 只有 Zen("opencode") 或 go 条目 type≠api → 绝不被采用（零网络）。"""
    write_auth_json({"opencode": {"type": "api", "key": ZEN_KEY},
                     "opencode-go": {"type": "oauth", "key": "stale-oauth-12345678"}})
    assert auth.detect_go_key() is None
    set_resp(lambda url, h, n: usage_json({"percent": 1}))
    u = fresh_go().fetch()
    assert u.error_code == "not_configured" and stub.calls == []
    # 换成合法 go 条目：只允许用 go key（头断言），Zen key 绝不出现
    write_auth_json({"opencode": {"type": "api", "key": ZEN_KEY},
                     "opencode-go": {"type": "api", "key": GO_KEY}})
    assert auth.detect_go_key() == GO_KEY

    def resp(url, h, n):
        assert h["Authorization"] == "Bearer " + GO_KEY, "自动检测取错 key（危险！）"
        assert ZEN_KEY not in str(h)
        return usage_json({"percent": 20})
    set_resp(resp)
    u2 = fresh_go().fetch()
    assert u2.ok and abs(u2.pct_used - 0.2) < 1e-9
    return "Zen/oauth 不采用（零网络）；go/api 条目正确携带"


def g10_auto_detect_off():
    """config.opencode_go.auto_detect=false → 不读 auth.json（零网络）。"""
    write_auth_json({"opencode-go": {"type": "api", "key": GO_KEY}})
    (tmp_root / "config.json").write_text(json.dumps(
        {"enabled_providers": ["opencode_go"],
         "opencode_go": {"auto_detect": False}}), encoding="utf-8")
    set_resp(lambda url, h, n: usage_json({"percent": 1}))
    u = fresh_go().fetch()
    assert u.error_code == "not_configured" and stub.calls == []
    return "auto_detect=False → 关闭检测"


def g11_cache_ttl():
    auth.save_secret("opencode_go_key", GO_KEY)
    set_resp(lambda url, h, n: usage_json({"percent": 10}))
    src = fresh_go()
    src.fetch(); src.fetch()
    assert len(stub.calls) == 1, "TTL 内应命中缓存"
    src._cache_at -= og.CACHE_TTL_SECONDS + 1
    src.fetch()
    assert len(stub.calls) == 2
    return "60s 缓存 + 过期重拉"


# ---------------------------------------------------- auth 通用用例 ----

def a1_secret_roundtrip():
    p = tmp_root / "custom_go.dpapi"
    auth.save_secret("opencode_go_key", "alpha-key-1", path=p)
    assert p.exists() and p.read_bytes() != b"alpha-key-1"
    assert auth.load_secret("opencode_go_key", path=p) == "alpha-key-1"
    assert not p.with_name(p.name + ".tmp").exists(), "原子写不得留 .tmp"
    auth.save_secret("opencode_go_key", "beta-key-2", path=p)          # 覆盖原子替换
    assert auth.load_secret("opencode_go_key", path=p) == "beta-key-2"
    assert auth.has_secret("opencode_go_key", path=p)
    assert not auth.has_secret("alt_secret_name")                    # 默认路径=重定向 tmp
    for bad in ("", None):
        try:
            auth.save_secret("alt_secret_name", bad)
            raise AssertionError("空值应拒绝")
        except ValueError:
            pass
    try:
        auth.save_secret("evil/../x", "v")
        raise AssertionError("非法名称应拒绝")
    except ValueError:
        pass
    try:
        auth.load_secret("alt_secret_missing")                       # 不存在
        raise AssertionError("缺文件应 OSError")
    except OSError:
        pass
    return "往返/覆盖/无 .tmp/空值与非法名拒绝"


def a2_detect_variants():
    p = tmp_root / "auth_variants.json"
    p.write_text(json.dumps({"opencode-go": {"type": "api", "key": "k12345678"}}),
                 encoding="utf-8")
    assert auth.detect_go_key(p) == "k12345678"
    p.write_text(json.dumps({"opencode-go": {"type": "oauth", "key": "k"}}),
                 encoding="utf-8")
    assert auth.detect_go_key(p) is None
    p.write_text(json.dumps({"opencode-go": {"type": "api", "key": ""}}), encoding="utf-8")
    assert auth.detect_go_key(p) is None
    p.write_text(json.dumps({"opencode": {"type": "api", "key": "zen-only"}}),
                 encoding="utf-8")
    assert auth.detect_go_key(p) is None, "绝不回退读 Zen 条目"
    p.write_text("{broken json", encoding="utf-8")
    assert auth.detect_go_key(p) is None
    assert auth.detect_go_key(tmp_root / "nope.json") is None
    return "type≠api/空 key/仅 Zen/损坏/缺失 → None"


# ---------------------------------------------------- 设置面板 / UI（Tk）----

def _all_texts(w, out):
    try:
        t = w.cget("text")
        if isinstance(t, str) and t:
            out.append(t)
    except tk.TclError:
        pass
    if isinstance(w, (tk.Entry, tk.Text)):
        try:
            out.append(w.get("1.0", "end") if isinstance(w, tk.Text) else w.get())
        except tk.TclError:
            pass
    for ch in w.winfo_children():
        _all_texts(ch, out)
    return out


def pump(root, n=10):
    for _ in range(n):
        root.update()
        time.sleep(0.01)


def feed(app, *usages):
    app.sched.events.put(("update", list(usages),
                          {"next_delay": 300, "ts": time.time(), "low": False}))
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)


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


def clear_secrets():
    for p in list(tmp_root.glob("*.dpapi")) + [tmp_root / "config.json"]:
        try:
            p.unlink()
        except OSError:
            pass


_NOW = datetime.now(timezone.utc)


def s1_settings_togglable_and_note(app, root):
    """供应商复选框均可勾选；旁注动态；无凭据勾选 codex → 自动弹绑定面板并写入 config。
    M11a：OpenAI 行移除 → 旁注计数 4→3；「勾选即弹」样本由 openai 换为 Codex。"""
    clear_secrets()
    write_auth_json({})
    panel = settings_panel.SettingsPanel(app)
    panel.withdraw()
    texts = _all_texts(panel, [])
    assert sum(1 for t in texts if "点击配置" in t) == 3, "三行均应有绑定旁注（M11a -OpenAI）"
    assert any(t.startswith("未绑定") for t in texts), "无凭据 → 未绑定"
    assert not any("未配置凭据）" in t for t in texts), "旧置灰旁注应已移除"
    assert not any("OpenAI" in t for t in texts), "M11a：OpenAI 供应商行应已移除"
    panel._pvars["codex"].set(True)
    panel._on_provider_toggle("codex")
    assert "codex" in app._key_panels and app._key_panels["codex"].alive(), \
        "无凭据勾选应自动弹绑定面板"
    assert app._key_panels["codex"].provider == "codex"
    saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
    assert saved["enabled_providers"] == ["bailian", "codex"], saved
    app._key_panels["codex"].close_card()
    auth.save_secret("codex_access_token", CX_TOKEN)
    panel._refresh_notes()
    assert any(t.startswith("已绑定") for t in _all_texts(panel, [])), "有 token → 已绑定"
    panel.destroy()
    app.cfg["enabled_providers"] = ["bailian"]
    return "三家可勾选 / 旁注动态 / 勾选即弹（样本=Codex）"


def codex_usage_ok(url, h, n):
    return 200, "application/json", json.dumps(
        {"plan_type": "plus", "rate_limit": {"allowed": True, "primary_window": {
            "used_percent": 40, "limit_window_seconds": 18000,
            "reset_after_seconds": 3600}}}).encode()


def s2_codex_panel_save_clear_verify(app, root):
    """（M11a 由 openai 面板案例原地改造）Codex 面板：保存→清空→fetch_now 验证绿字；
    token 永不回显。保留原案例的「保存即验证+即清空+不回显」三纪律覆盖。"""
    clear_secrets()
    set_resp(codex_usage_ok)
    panel = settings_panel.ProviderKeyPanel(app, "codex")
    panel.withdraw()
    texts = _all_texts(panel, [])
    assert any("实验性" in t for t in texts), "Codex 面板需标实验性"
    panel.ent_key.insert(0, CX_TOKEN)
    panel._save()
    assert panel.ent_key.get() == "", "输入框即刻清空"
    assert auth.load_secret("codex_access_token") == CX_TOKEN
    panel._validate()
    st = panel.status.cget("text")
    assert "验证成功" in st and "40%" in st and panel.status.cget("fg").lower() == OK.lower(), st
    for t in _all_texts(panel, []):
        key_never_leaks(t)
    panel.destroy()
    return "保存清空+绿字验证(含窗口pct)+不回显"


def s3_codex_panel_verify_fail(app, root):
    """（M11a 由 openai 面板案例原地改造）401 → 橙字 KEY_INVALID 提示且不泄 token。"""
    clear_secrets()
    set_resp(lambda url, h, n: (401, "application/json",
                                b'{"error":{"message":"Token expired"}}'))
    panel = settings_panel.ProviderKeyPanel(app, "codex")
    panel.withdraw()
    panel.ent_key.insert(0, CX_TOKEN)
    panel._save()
    panel._validate()
    st = panel.status.cget("text")
    assert "KEY_INVALID" in st and "密钥无效" in st, st
    assert panel.status.cget("fg").lower() == ORANGE.lower()
    for t in _all_texts(panel, []):
        key_never_leaks(t)
    panel.destroy()
    return "401 → 橙字 KEY_INVALID 提示且不泄 token"


def s4_go_panel_detect_paste(app, root):
    """自动检测行（仅尾 4 位）；开关切换；手动粘贴保存→清空→验证。"""
    clear_secrets()
    write_auth_json({"opencode": {"type": "api", "key": ZEN_KEY},
                     "opencode-go": {"type": "api", "key": GO_KEY}})
    set_resp(lambda url, h, n: usage_json({"percent": 40, "resetsAt":
                                           (_NOW + timedelta(hours=3)).isoformat()}))
    panel = settings_panel.ProviderKeyPanel(app, "opencode_go")
    panel.withdraw()
    det = panel.lbl_detect.cget("text")
    assert "已找到" in det and GO_KEY[-4:] in det, det
    key_never_leaks(det)                                            # 仅尾 4 位
    panel.var_auto.set(False)
    panel._save_go_cfg()
    assert "已关闭" in panel.lbl_detect.cget("text")
    cfg = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
    assert cfg["opencode_go"]["auto_detect"] is False, "开关改即存"
    panel.var_auto.set(True)
    panel._save_go_cfg()
    panel.ent_key.insert(0, GO_KEY)
    panel._save()
    assert panel.ent_key.get() == "", "保存后即刻清空"
    assert auth.load_secret("opencode_go_key") == GO_KEY
    panel._validate()
    st = panel.status.cget("text")
    assert "验证成功" in st and "~5h" in st and panel.status.cget("fg").lower() == OK.lower(), st
    for t in _all_texts(panel, []):
        key_never_leaks(t)
    panel.destroy()
    return "检测行尾4位 / 开关即存 / 粘贴保存验证"


def u1_usd_rows(app, root):
    """E：usd 大数字 $x,xxx.xx；副行「近30天已用/预算」「近30天已用/余额」。"""
    feed(app, Usage(provider="openai", ok=True, unit="usd", used=1234.56,
                    total=2000.0, remaining=765.44, pct_used=0.6172))
    labels = texts_join(app)
    assert "$765.44" in labels and "$1,234.56" in labels
    assert "近30天已用 $1,234.56 / 预算 $2,000.00" in labels, labels
    assert fill_of(app, "$765.44") == INK.lower()
    assert "额度 · 已用 61.7%" in labels, "无 windows 时 B 行额度文案"
    assert not any(str(t) == "None" for t, _ in text_items(app)), "spec 空不画徽章"
    feed(app, Usage(provider="openai", ok=True, unit="usd", used=40.0,
                    total=None, remaining=60.0, pct_used=0.4,
                    resets_at=_NOW + timedelta(days=5)))
    assert "近30天已用 $40.00 / 余额 $60.00" in texts_join(app)


def u2_percent_row(app, root):
    """E：percent 大数字=剩余占比；~5h/周/月多窗副显各带倒计时。"""
    feed(app, Usage(provider="opencode_go", ok=True, unit="percent",
                    pct_used=0.4, resets_at=_NOW + timedelta(hours=2),
                    windows=[Window("rolling", 0.4, _NOW + timedelta(hours=2)),
                             Window("weekly", 0.7, _NOW + timedelta(days=2)),
                             Window("monthly", 0.9, _NOW + timedelta(days=9))]))
    labels = texts_join(app)
    assert "~5h 窗口 · 已用 40.0%" in labels, labels       # rolling→~5h
    assert "周 窗口 · 已用 70.0%" in labels and "月 窗口 · 已用 90.0%" in labels
    assert "（周）" in labels and "（月）" in labels, "各窗倒计时后缀"
    big = [t for t, _ in text_items(app) if t == "60%"]
    assert big, "大数字=剩余占比 60%"
    assert fill_of(app, "60%") == INK.lower()


def u3_cred_and_stale_tiers(app, root):
    """E：KEY_INVALID/NO_SUBSCRIPTION 橙档+「配置密钥…」；RATE_LIMITED 灰 stale；
    not_configured 保持「未配置凭据 · 待启用」。"""
    assert {"KEY_INVALID", "NO_SUBSCRIPTION"} <= CRED_ERRORS
    # 无历史 err 行：橙 + 密钥面板入口（点按钮真开面板）
    app.last_good.clear()                           # 前例已建 last_good，此处验证「从未成功」档
    feed(app, Usage(provider="opencode_go", ok=False, unit="percent",
                    error_code="KEY_INVALID", error_msg="密钥无效"))
    labels = texts_join(app)
    assert "凭据已失效" in labels and "配置密钥…" in labels
    assert "更新登录凭据…" not in labels, "非百炼行不得走百炼 Cookie 面板按钮"
    assert fill_of(app, "凭据已失效") == ORANGE.lower()
    # M7-b 调整：clicks[0] 现为头部刷新图标，取「配置密钥…」按钮热区需过滤 icon
    z = next(z for z in app.clicks if z[4] != app.refresh)
    ev = types.SimpleNamespace(x_root=0, y_root=0,
                               x=(z[0] + z[2]) / 2, y=(z[1] + z[3]) / 2)
    app._press_xy = (0, 0)
    app._drag_end(ev)
    assert "opencode_go" in app._key_panels and app._key_panels["opencode_go"].alive()
    app._key_panels["opencode_go"].close_card()
    # 有历史 full 行：NO_SUBSCRIPTION → 橙色专属文案
    ok_go = Usage(provider="opencode_go", ok=True, unit="percent", pct_used=0.1,
                  windows=[Window("rolling", 0.1, _NOW + timedelta(hours=4))])
    feed(app, ok_go)
    feed(app, Usage(provider="opencode_go", ok=False, unit="percent",
                    error_code="NO_SUBSCRIPTION", error_msg="此 key 无 OpenCode Go 订阅"))
    assert fill_of(app, "此 key 无 OpenCode Go 订阅") == ORANGE.lower()
    assert "配置密钥…" in texts_join(app)
    # RATE_LIMITED / NETWORK → 灰 stale 档
    feed(app, Usage(provider="opencode_go", ok=False, unit="percent",
                    error_code="RATE_LIMITED", error_msg="429"))
    labels = texts_join(app)
    assert "拉取失败 · RATE_LIMITED · 自动重试中（退避）" in labels
    assert fill_of(app, "拉取失败 · RATE_LIMITED") == FAINT.lower()
    assert "配置密钥…" not in labels
    app.last_good.clear()                           # not_configured 看「无历史」档
    feed(app, Usage(provider="opencode_go", ok=False, unit="percent",
                    error_code="not_configured", error_msg="未绑定 OpenCode Go key"))
    assert "未配置凭据 · 待启用" in texts_join(app)


def tk_section(app, root, checks) -> None:
    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            note = fn(app, root) or ""
            checks.append((name, True, note))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:220]))
    for name, fn in [("settings_togglable_note", s1_settings_togglable_and_note),
                     ("codex_panel_ok", s2_codex_panel_save_clear_verify),
                     ("codex_panel_fail", s3_codex_panel_verify_fail),
                     ("go_panel_detect_paste", s4_go_panel_detect_paste),
                     ("ui_usd_rows", u1_usd_rows),
                     ("ui_percent_rows", u2_percent_row),
                     ("ui_cred_stale", u3_cred_and_stale_tiers)]:
        case(name, fn)


# ---------------------------------------------------------------- run ----

def local_snapshot() -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(REAL_LOCAL.glob("*")) if p.is_file()}


def run(tmp: Path) -> int:
    global tmp_root
    tmp_root = tmp
    checks: list[tuple[str, bool, str]] = []
    before = local_snapshot()

    def case(name, fn):
        print(f"· {name} …", flush=True)
        clear_secrets()
        try:
            note = fn() or ""
            checks.append((name, True, note))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:220]))

    orig = (auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE,
            config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            cx._req, og._req, gw._req, os.environ.get("USERPROFILE"))
    auth.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = tmp / "bailian_cookie.dpapi"
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    os.environ["USERPROFILE"] = str(tmp)           # detect_go_key 默认路径重定向
    write_auth_json({})

    def blocked(url, headers, data=None):
        _net.append(str(url)[:80])
        raise AssertionError("真实网络请求被拦截（测试违规）")

    cx._req = stub                                  # _req(url, headers, opener) 替身（M11a：原 openai 桩位）
    og._req = stub
    gw._req = blocked
    root = None
    app = None
    try:
        for name, fn in [("g1_api_variant_iso", g1_api_variant_iso),
                         ("g2_dashboard_variant", g2_dashboard_variant),
                         ("g3_epoch_forms", g3_epoch_forms),
                         ("g4_rate_limited", g4_rate_limited),
                         ("g5_rolling_missing_badjson", g5_rolling_missing_and_badjson),
                         ("g6_entitlement_403", g6_entitlement_403),
                         ("g7_401_429", g7_401_429),
                         ("g8_not_configured_zero_net", g8_not_configured_zero_net),
                         ("g9_zen_key_never_auto", g9_zen_key_never_auto),
                         ("g10_auto_detect_off", g10_auto_detect_off),
                         ("g11_cache_ttl", g11_cache_ttl),
                         ("a1_secret_roundtrip", a1_secret_roundtrip),
                         ("a2_detect_variants", a2_detect_variants)]:
            case(name, fn)

        # ---- Tk 段：设置面板 + UI 行渲染 ----
        main_mod.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        sched = Scheduler([], poll_seconds=300)     # 不 start：零后台拉取
        app = NoteApp(root, dict(CFG), sched, state=dict(DEFAULTS))
        root.withdraw()
        tk_section(app, root, checks)
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
    with tempfile.TemporaryDirectory(prefix="m6_go_") as d:
        raise SystemExit(run(Path(d)))
