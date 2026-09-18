"""M5 验收 A 组（A1~A10 异常态矩阵）。

运行：`python tests\\test_anomaly.py`（需可用桌面会话；窗口全程 withdraw）。
安全红线（与 test_settings.py 同款机制）：
- 零真实网络：全程打桩 gw._req 为拦截器（任何到达即记为失败用例），
  源层测试只 stub gw.gateway_post / gw.resolve_sec_token / load_bailian_cookie；
- config.json / state.json / cookie 全部 temp 重定向，真实 local/ 不写；
- 真实 local/bailian_cookie.dpapi 前后 SHA-256 比对 + 与 PLAN §8 基线核对；
- 不 start 真实网络源调度；A9 仅启动本测试自建的假源线程并 stop/join（不杀进程）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import types
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import auth, config as config_mod                               # noqa: E402
from src import settings_panel                                           # noqa: E402
from src import state as state_mod                                       # noqa: E402
from src.scheduler import BACKOFF_CAP, FAST_INTERVAL, Scheduler          # noqa: E402
from src.sources import bailian_gateway as gw                            # noqa: E402
from src.sources import bailian as bailian_mod                           # noqa: E402
from src.sources.bailian import BailianSource                            # noqa: E402
from src.sources.base import Usage, Window                               # noqa: E402
from src.state import DEFAULTS                                           # noqa: E402
from src.ui import (CRED_ERRORS, FAINT, ORANGE, SOFT, STALE,             # noqa: E402
                    NoteApp, fmt_value)
import main as main_mod                                                   # noqa: E402

REAL_COOKIE = ROOT / "local" / "bailian_cookie.dpapi"
COOKIE_BASELINE_SHA256 = ("fba4c5b5dd94553871511da622a6c7701e6660cf"
                          "f4076ebb0734a32513452739")

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian", "opencode_go"]}

_NOW = datetime.now(timezone.utc)

app_tmp: dict = {}   # run() 填充：{"cfg": 临时config路径, "cookie": 临时cookie路径}


def u_ok(remaining=17022.0, addon=1509.0, total=60000.0, pct=0.612):
    wins = [Window("7d", pct, _NOW + timedelta(hours=8, minutes=2))]
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=total * pct, total=total, remaining=remaining,
                 pct_used=pct, resets_at=wins[0].resets_at, windows=wins,
                 addon_remaining=addon)


def u_err(code, msg="fake", provider="bailian"):
    return Usage(provider=provider, ok=False, error_code=code, error_msg=msg)


def feed(app, *usages):
    app.sched.events.put(("update", list(usages),
                          {"next_delay": 300, "ts": time.time(), "low": False}))
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)


def reset(app, seed_ok=False):
    app.last_good.clear()
    app.usages = []
    app.meta = {}
    if seed_ok:
        feed(app, u_ok())


def text_items(app):
    c = app.canvas
    return [(c.itemcget(i, "text"), str(c.itemcget(i, "fill")).lower())
            for i in c.find_all() if c.type(i) == "text"]


def fill_of(app, substr) -> str:
    """第一个含 substr 的画布文字项的填充色（小写 hex）；找不到即 AssertionError。"""
    for t, fill in text_items(app):
        if substr in str(t):
            return fill
    raise AssertionError(f"画布无文案：{substr!r}（现有：{[t for t, _ in text_items(app)]}）")


def texts_join(app) -> str:
    return " | ".join(str(t) for t, _ in text_items(app))


def has_dashed_badge(app) -> bool:
    c = app.canvas
    for i in c.find_all():
        if c.type(i) != "rectangle":
            continue
        dash = str(c.itemcget(i, "dash")).lower()
        outline = str(c.itemcget(i, "outline")).lower()
        if dash not in ("", "none") and outline == FAINT.lower():
            return True
    return False


def env_ok(payload) -> dict:
    return {"code": "200", "data": {"DataV2": {"data": {
        "success": True, "code": "SUCCESS", "data": payload}}}}


# ---------------------------------------------------------------- 用例 ----

def a1_login_expired_with_history(app, checks):
    reset(app, seed_ok=True)
    feed(app, u_err("LOGIN_EXPIRED", "Cookie 过期"))
    infos = app._row_infos()
    assert infos[0]["stale"] and infos[0]["cred"]          # 内部状态
    assert "需重新登录凭据（Cookie 过期）" in texts_join(app)
    assert fill_of(app, "需重新登录凭据（Cookie 过期）") == ORANGE.lower()   # 橙
    assert "更新登录凭据…" in texts_join(app) and app.clicks, "缺行内凭据胶囊"
    assert fmt_value(17022.0) in texts_join(app), "旧值应保留可见"
    assert fill_of(app, "17,022") == STALE.lower(), "旧值应灰显"
    assert has_dashed_badge(app) and "旧数据" in texts_join(app)


def a2_login_expired_no_history(app, checks):
    reset(app)
    feed(app, u_err("LOGIN_EXPIRED", "Cookie 过期"))
    infos = app._row_infos()
    assert infos[0]["kind"] == "err"                        # 内部状态
    labels = texts_join(app)
    assert "凭据已失效" in labels and "暂无可显示的历史数据" in labels
    assert fill_of(app, "凭据已失效") == ORANGE.lower()
    assert not any(t == "—" for t, _ in text_items(app)), "不得出现 -- 假象堆叠"
    assert not has_dashed_badge(app), "从未成功 → 不应有旧数据徽章"


def a3_workspace_notauthorised(app, checks):
    reset(app)
    # 网关分类语义守护（规格 §6.3）
    cls = gw.classify_error({"code": "Workspace.NotAuthorised", "message": "no perm"},
                            "Workspace.NotAuthorised", "no perm")
    assert cls.startswith("WORKSPACE_NOTAUTHORISED"), cls
    assert "补 token 重试" in cls and "勿重贴" in cls, cls
    code = cls.split("(", 1)[0]                              # source 的 _usage_error 截取
    assert code not in CRED_ERRORS
    feed(app, u_err(code, cls))
    labels = texts_join(app)
    assert "拉取失败 · WORKSPACE_NOTAUTHORISED · 自动重试中" in labels
    assert "更新登录凭据…" not in labels, "NotAuthorised 不得弹重贴凭据入口"
    assert "需重新登录凭据" not in labels
    assert app._row_infos()[0]["cred"] is False
    # 注：msg 行可含上游提示「勿重贴 Cookie」（否定式），断言只拦肯定式祈使：
    for t, _ in text_items(app):
        t = str(t)
        assert "请重贴" not in t and "重新粘贴" not in t and "需重贴" not in t, t


def a4_network_stale_and_backoff(app, checks):
    reset(app, seed_ok=True)
    feed(app, u_err("NETWORK", "timed out"))
    labels = texts_join(app)
    assert "拉取失败 · NETWORK · 自动重试中（退避）" in labels
    assert fill_of(app, "17,022") == STALE.lower()          # 灰显旧值
    assert has_dashed_badge(app), "缺 stale 虚线徽章"

    # 退避内部值：直接驱动 Scheduler._cycle（无线程、无网络、无 sleep）。
    # 判据 = 修复后语义 poll ≤ delay ≤ CAP：连续失败逐轮翻倍
    # （600/1200/1800…封顶 1800），成功复位回 poll。
    class AlwaysFail:
        name = "bailian"
        def fetch(self):
            return u_err("NETWORK", "down")

    sched = Scheduler([AlwaysFail()], poll_seconds=300.0)
    for n in range(1, 13):
        d = sched._cycle()
        assert sched._streak["bailian"] == n, (n, dict(sched._streak))
        assert FAST_INTERVAL <= d <= BACKOFF_CAP == 1800.0, \
            f"第{n}轮退避 {d} 越界 [60, 1800]"
        assert d == min(BACKOFF_CAP, max(300.0, 300.0 * 2 ** n)), f"第{n}轮 {d}"
        _k, _p, _m = sched.events.get_nowait()             # tick
        _k, _p, meta = sched.events.get_nowait()           # update
        assert meta["streak"]["bailian"] == n and meta["next_delay"] == d
    assert [min(BACKOFF_CAP, max(300.0, 300.0 * 2 ** n)) for n in (1, 2, 3, 4)] \
        == [600.0, 1200.0, 1800.0, 1800.0], "退避应逐轮翻倍并封顶 1800"

    class Recover:
        name = "bailian"
        def fetch(self):
            return u_ok()

    sched.set_sources([Recover()])
    assert sched._cycle() == 300.0, "恢复后应复位到 poll"
    assert sched._streak["bailian"] == 0
    while not sched.events.empty():                          # 清空，不影响后续断言
        sched.events.get_nowait()


def _stub_gateway_api(app, posts, delays):
    """返回 (undo) —— 用 posts[tail] 桩 gateway_post，静默 usage 重试 sleep。"""
    calls = {"usage": 0}

    def fake_post(cookie, sec_token, api, data_extra=None):
        tail = api.rsplit("/", 1)[-1]
        if tail == "usage":
            calls["usage"] += 1
        return posts[tail]

    orig = (gw.gateway_post, gw.resolve_sec_token, gw.time,
            bailian_mod.load_bailian_cookie)
    gw.gateway_post = fake_post
    gw.resolve_sec_token = lambda c: (None, "stub")
    gw.time = types.SimpleNamespace(sleep=lambda s: delays.append(s))
    bailian_mod.load_bailian_cookie = lambda: "fake_cookie=a; login_aliyunid_csrf=b"

    def undo():
        gw.gateway_post, gw.resolve_sec_token, gw.time, \
            bailian_mod.load_bailian_cookie = orig
    return undo, calls


def a5_usage_missing_percentage_key(app, checks):
    delays: list[float] = []
    posts = {
        "subscription": {"http": 200, "api": "subscription", "env": env_ok({"specCode": "pro"})},
        "quota-config": {"http": 200, "api": "quota-config",
                         "env": env_ok({"pro": {"weekly": 40000.0}})},
        "usage": {"http": 200, "api": "usage", "env": env_ok({})},   # 丢 per1WeekPercentage
        "addon/list": {"http": 200, "api": "addon/list", "env": env_ok({"items": []})},
    }
    undo, calls = _stub_gateway_api(app, posts, delays)
    try:
        u = BailianSource().fetch()                          # 新实例，不吃缓存
    finally:
        undo()
    assert u.ok is False and u.error_code == "EMPTY_WINDOW", (u.error_code, u.error_msg)
    assert calls["usage"] == 3, f"usage 应重试 3 次，实际 {calls['usage']}"
    assert delays == [gw.USAGE_RETRY_DELAY] * 2, delays      # 重试间隔 2×400ms
    # 归入错误态不崩：喂给 UI 渲染一轮
    reset(app)
    feed(app, u)
    assert app._row_infos()[0]["kind"] in ("err", "full")
    assert "重试" in texts_join(app) or "EMPTY_WINDOW" in texts_join(app)


def a6_envelope_no_datav2(app, checks):
    assert gw.extract_payload(env_ok({"x": 1})) == {"x": 1}
    assert gw.extract_payload({"code": "200", "data": {}}) is None          # 缺 DataV2
    assert gw.extract_payload({"code": "200", "data": None}) is None
    assert gw.extract_payload("不是json结构") is None
    assert gw.extract_payload(None) is None

    delays: list[float] = []
    posts = {
        "subscription": {"http": 200, "api": "subscription",
                         "env": {"code": "200", "data": {}}},               # 改版信封
        "quota-config": {"http": 200, "api": "quota-config",
                         "env": {"code": "200", "data": {}}},
        "usage": {"http": 200, "api": "usage", "env": {"code": "200", "data": {}}},
        "addon/list": {"http": 200, "api": "addon/list", "env": {"code": "200", "data": {}}},
    }
    undo, _calls = _stub_gateway_api(app, posts, delays)
    try:
        u = BailianSource().fetch()
    finally:
        undo()
    assert u.ok is False, "DataV2 缺失必须归入错误态"
    assert u.error_code in ("EMPTY_WINDOW", "PARSE_EMPTY", "UNKNOWN"), u.error_code
    reset(app)
    feed(app, u)
    assert "暂无可显示的历史数据" in texts_join(app)


def a11_subscription_endtime_to_plan_end(app, checks):
    """M23：百炼 subscription.endTime（毫秒 epoch）→ Usage.plan_end；缺省/坏型→None。
    其余 source 不动恒 None（合成 Usage 不经 bailian 路径，plan_end 默认零占位）。"""
    import time as _t
    future_ms = int((_t.time() + 30 * 86400) * 1000)
    base_posts = {
        "quota-config": {"http": 200, "api": "quota-config",
                         "env": env_ok({"pro": {"weekly": 40000.0}})},
        "usage": {"http": 200, "api": "usage",
                  "env": env_ok({"per1WeekPercentage": 61.2,
                                 "per1WeekResetTime": future_ms})},
        "list": {"http": 200, "api": "addon/list", "env": env_ok({"items": []})},
    }
    posts = {**base_posts, "subscription": {"http": 200, "api": "subscription",
                                            "env": env_ok({"specCode": "pro",
                                                          "endTime": future_ms})}}
    undo, _c = _stub_gateway_api(app, posts, [])
    try:
        u = BailianSource().fetch()
        assert u.ok, (u.error_code, u.error_msg)
        assert u.plan_end is not None and abs(u.plan_end.timestamp() * 1000 - future_ms) < 1000
        # 缺 endTime / 坏型字符串 → None（不崩、零占位）
        posts["subscription"] = {"http": 200, "api": "subscription",
                                 "env": env_ok({"specCode": "pro"})}
        u2 = BailianSource().fetch()
        assert u2.ok and u2.plan_end is None
        posts["subscription"] = {"http": 200, "api": "subscription",
                                 "env": env_ok({"specCode": "pro", "endTime": "not-a-ts"})}
        u3 = BailianSource().fetch()
        assert u3.ok and u3.plan_end is None
    finally:
        undo()
    # 渲染兼容：plan_end 有值的错误/stale 路径不炸（错误 Usage 默认 None）
    reset(app)
    err = Usage(provider="bailian", ok=False, error_code="NETWORK", error_msg="t")
    assert err.plan_end is None, "错误路径默认零占位"
    feed(app, err)
    assert app._row_infos()[0]["kind"] in ("err", "full")


def a7_all_providers_error(app, checks):
    # M11a：合成 provider 样本由 openai 换 opencode_go（OpenAI 行已退场）
    reset(app)
    feed(app, u_err("NETWORK", "bailian down"),
         Usage(provider="opencode_go", ok=False, unit="percent",
               error_code="not_configured", error_msg="占位：未配置凭据"))
    infos = {i["u"].provider: i for i in app._row_infos()}
    assert infos["bailian"]["kind"] == "err" and infos["bailian"]["cred"] is False
    assert infos["opencode_go"]["kind"] == "err" and infos["opencode_go"]["cred"] is False
    labels = texts_join(app)
    assert "百炼" in labels and "OpenCode Go" in labels
    assert "未配置凭据 · 待启用" in labels                    # go 行文案
    assert "拉取失败 · NETWORK · 自动重试中" in labels        # bailian 行文案
    assert "尚无成功数据" in labels                          # 头部合计语义
    # M7-b 调整：hits 新增头部刷新图标热区（{"tip":...}），行 hover 区按含 "u" 过滤
    assert len([z for z in app.hits if "u" in z[4]]) == 2, "每行各自 hover 区（无空窗）"
    h = float(app.canvas.cget("height"))
    assert h > 120 * app.S, f"窗口未塌陷：h={h}"


def a8_cookie_panel_rejects_no_equals(app, checks):
    fake = app_tmp["cookie"]
    for p in (fake, fake.with_name(fake.name + ".tmp")):
        assert not p.exists(), "前置：临时 cookie 文件应不存在"
    reset(app)
    panel = settings_panel.CredentialPanel(app, cookie_path=fake)
    panel.withdraw()
    try:
        panel.txt.insert("1.0", "z" * 80)                   # 够长但无 '='
        panel._save()
        assert "不是完整 Cookie" in panel.status.cget("text"), panel.status.cget("text")
        assert not fake.exists() and not fake.with_name(fake.name + ".tmp").exists(), \
            "非法串不得落盘"
        assert "z" * 80 not in panel.status.cget("text")
    finally:
        panel.destroy()


def a9_poll_race(app, checks):
    cfg_path = app_tmp["cfg"]

    class Fast:
        name = "bailian"
        calls = 0
        def fetch(self):
            Fast.calls += 1
            return u_ok()

    orig_sources = app.sched.sources
    app.sched.set_sources([Fast()])
    app.sched.start()                        # 本测试自建假源线程（非 TokenWidget 进程）
    errs = []
    try:
        time.sleep(0.15)                     # 让线程进入周期/等待（不持锁）
        assert app.sched._thread.is_alive(), "轮询线程应在运行"
        for v in range(61, 71):              # 线程运行中连改 10 次
            try:
                app.set_poll_seconds(v)      # 写 config 文件 + 改 sched.poll
                if v % 5 == 0:               # 交错驱动一轮采集（模拟线程活跃期读 poll）
                    app.sched._cycle()
            except Exception as e:           # noqa: BLE001
                errs.append(e)
            time.sleep(0.02)
        assert not errs, errs
        assert app.sched._thread.is_alive(), "写竞态导致线程死亡/异常退出"
        saved = json.loads(cfg_path.read_text(encoding="utf-8"))["poll_seconds"]
        assert saved == 70 and app.sched.poll == 70.0, (saved, app.sched.poll)
    finally:
        codes = [u.error_code for _, payload, _m in _drain(app.sched)
                 for u in payload or [] if payload]
        app.sched.stop()
        t = app.sched._thread
        if t:
            t.join(timeout=5)
            assert not t.is_alive(), "轮询线程未退出（疑似死锁）"
        app.sched.set_sources(orig_sources)
    assert "SOURCE_EXCEPTION" not in codes, codes          # 竞态期无源异常
    # 双保险：越界 5 → 钳到 60（config 读侧 + ui 写侧）
    app.set_poll_seconds(5)
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["poll_seconds"] == 60


def _drain(sched):
    out = []
    while True:
        try:
            out.append(sched.events.get_nowait())
        except Exception:                    # noqa: BLE001 queue.Empty
            return out


def a10_http_semantics(app, checks):
    # 源层分类映射：401→LOGIN_EXPIRED 语义、403→AUTH_DENIED、429→UNKNOWN
    assert gw.classify_error({"code": "PostOnlyOrTokenHasExpired"}, "Login.Expired",
                             "") == "LOGIN_EXPIRED(Cookie 过期 → 重新抓取)"
    assert gw.classify_error({"code": "Forbidden"}, "403",
                             "access denied").startswith("AUTH_DENIED")
    assert gw.classify_error({}, "429", "Too Many Requests") == "UNKNOWN"

    rows = [  # (code, 无历史文案, 色, 有历史(stale)文案, 色)
        ("LOGIN_EXPIRED", "凭据已失效", ORANGE, "需重新登录凭据（Cookie 过期）", ORANGE),
        ("AUTH_DENIED", "拉取失败 · AUTH_DENIED · 自动重试中", SOFT,
         "拉取失败 · AUTH_DENIED · 自动重试中（退避）", FAINT),
        ("UNKNOWN", "拉取失败 · UNKNOWN · 自动重试中", SOFT,
         "拉取失败 · UNKNOWN · 自动重试中（退避）", FAINT),
    ]
    for code, txt_no, col_no, txt_stale, col_stale in rows:
        reset(app)
        feed(app, u_err(code))
        assert fill_of(app, txt_no) == col_no.lower(), (code, "无历史配色")
        assert (code in CRED_ERRORS) == ("更新登录凭据…" in texts_join(app)), code
        reset(app, seed_ok=True)
        feed(app, u_err(code))
        assert fill_of(app, txt_stale) == col_stale.lower(), (code, "stale 配色")
        assert fill_of(app, "17,022") == STALE.lower(), code   # 灰显旧值


def _start_first_fetch(sched, src, timeout=5.0) -> None:
    """等调度线程完成首轮 fetch（假源，零网络）。"""
    sched.start()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if src.count() >= 1:
            return
        time.sleep(0.02)
    raise AssertionError("首轮 fetch 未在 5s 内发生（线程未启动？）")


def _stop_join(sched) -> None:
    sched.stop()
    t = sched._thread
    if t:
        t.join(timeout=5)
        assert not t.is_alive(), "stop() 后线程未在 5s 内退出（疑似死锁/未唤醒）"


def t11_kick_wakes_immediately(app, checks):
    """T-kick：poll=300 时 kick() 应在 ≤2s 内触发再次 fetch（唤醒生效）。

    回归缺陷②：旧实现 `_stop.wait(delay)` 无人消费 _wake，kick 后仍等满
    300s 自然周期。本用例线程节拍即证明唤醒路径打通。
    """
    class Stampede:
        name = "bailian"
        def __init__(self):
            self.stamps: list[float] = []
        def fetch(self):
            self.stamps.append(time.time())
            return u_ok()
        def count(self):
            return len(self.stamps)

    src = Stampede()
    sched = Scheduler([src], poll_seconds=300.0)
    try:
        _start_first_fetch(sched, src)
        n0, t0 = src.count(), src.stamps[-1]
        sched.kick()
        deadline = t0 + 2.0
        while time.time() < deadline and src.count() < n0 + 1:
            time.sleep(0.02)
        assert src.count() >= n0 + 1, \
            f"kick() 未在 ≤2s 内触发再次 fetch（唤醒未生效，仍等自然周期）"
        assert src.stamps[-1] - t0 <= 2.0, f"唤醒延迟 {src.stamps[-1] - t0:.2f}s > 2s"
    finally:
        _stop_join(sched)
        while not sched.events.empty():
            sched.events.get_nowait()


def t12_kick_coalesced_no_storm(app, checks):
    """T-kick-idempotent：同窗口连点 10 次 kick，额外 fetch 次数有界（≤3）。

    理由：_wake 是事件位、_force 是标志位（非计数队列）——等待窗口内多次
    kick 合并为一次唤醒；fetch 期间到达的 kick 合并为一轮补拉。故 10 连点
    最坏 = 当前轮 + 1 轮唤醒 + 1 轮补拉，不随点击数线性放大（无拉取风暴）。
    """
    class Slow:
        name = "bailian"
        def __init__(self):
            self.n = 0
        def fetch(self):
            self.n += 1
            time.sleep(0.2)                      # 模拟一次拉取耗时，撑开合并窗口
            return u_ok()
        def count(self):
            return self.n

    src = Slow()
    sched = Scheduler([src], poll_seconds=300.0)
    try:
        _start_first_fetch(sched, src)           # 首轮含 0.2s fetch
        base = src.count()
        for _ in range(10):                      # 连点 10 次（全部落在同/相邻窗口）
            sched.kick()
            time.sleep(0.01)
        time.sleep(1.5)                          # 观察窗：poll=300，自然周期不可能到
        extra = src.count() - base
        assert extra <= 3, f"kick 风暴：10 连点额外拉取 {extra} 轮（应 ≤3，位合并失效）"
    finally:
        _stop_join(sched)
        while not sched.events.empty():
            sched.events.get_nowait()


CASES = [("A1", a1_login_expired_with_history), ("A2", a2_login_expired_no_history),
         ("A3", a3_workspace_notauthorised), ("A4", a4_network_stale_and_backoff),
         ("A5", a5_usage_missing_percentage_key), ("A6", a6_envelope_no_datav2),
         ("A7", a7_all_providers_error), ("A8", a8_cookie_panel_rejects_no_equals),
         ("A9", a9_poll_race), ("A10", a10_http_semantics),
         ("A11-plan_end", a11_subscription_endtime_to_plan_end),
         ("T-kick", t11_kick_wakes_immediately),
         ("T-kick-idempotent", t12_kick_coalesced_no_storm)]


def cookie_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(tmp: Path) -> int:
    checks: list[tuple[str, bool, str]] = []

    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            fn(app, checks)
            checks.append((name, True, ""))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:220]))

    # ---- 落盘重定向（同 test_settings 机制） ----
    cookie_before = cookie_sha(REAL_COOKIE) if REAL_COOKIE.exists() else None
    cfg_path = tmp / "config.json"
    state_path = tmp / "state.json"
    fake_cookie = tmp / "cookie_anomaly.dpapi"      # A8：初始不存在
    app_tmp.clear()
    app_tmp.update({"cfg": cfg_path, "cookie": fake_cookie})
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE)
    config_mod.CONFIG_PATH = cfg_path
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = state_path
    state_mod.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = fake_cookie

    # ---- 网络拦截线：任何真实 HTTP 到达 gw 底层即失败 ----
    net_attempts: list[str] = []
    orig_req = gw._req

    def _block(url, headers, data=None):
        net_attempts.append(str(url)[:80])
        raise AssertionError("真实网络请求被拦截（测试违规）")

    gw._req = _block
    root = None
    app = None
    try:
        main_mod.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        sched = Scheduler([], poll_seconds=300)     # 未 start；A9 才临时 start 假源
        app = NoteApp(root, dict(CFG), sched, state=dict(DEFAULTS))
        root.withdraw()
        for name, fn in CASES:
            case(name, fn)
    finally:
        try:
            if app is not None:
                app.quit()
        except Exception:                           # noqa: BLE001
            pass
        gw._req = orig_req
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         auth.BAILIAN_COOKIE_FILE) = orig

    checks.append(("NET_零真实网络（拦截线未触发）", not net_attempts,
                   "; ".join(net_attempts)))
    cookie_after = cookie_sha(REAL_COOKIE) if REAL_COOKIE.exists() else None
    checks.append(("GUARD_cookie_未被触碰",
                   cookie_before == cookie_after is not None, ""))
    checks.append(("GUARD_cookie_哈希==基线",
                   (cookie_after or "").lower() == COOKIE_BASELINE_SHA256, ""))

    bad = [c for c in checks if not c[1]]
    print()
    for name, ok, err in checks:
        print(f"  {'PASS' if ok else 'FAIL':4} {name} {err}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m5a_") as d:
        raise SystemExit(run(Path(d)))
