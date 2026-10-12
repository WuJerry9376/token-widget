r"""车道 C 回归：BailianHelperClient（假 Popen）+ BailianSource 传输选择。

红线：
- 不起真实 helper、不发真实网络请求、不读写真实 local/ 文件
  （client 全部注入 tmp_path 的 profile/log；legacy 路 monkeypatch gw._req）；
- 真实 local/bailian_cookie.dpapi 永不被触碰（load_bailian_cookie 打桩）。
信封样本形态取自 local/spike_v11.json（usage 月度窗口 SUCCESS）。
"""
from __future__ import annotations

import io
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sources import bailian as bailian_mod                  # noqa: E402
from src.sources import bailian_client as client_mod            # noqa: E402
from src.sources import bailian_gateway as gw                   # noqa: E402
from src.sources.bailian import BailianSource                   # noqa: E402
from src.sources.bailian_client import BailianHelperClient, build_command  # noqa: E402

# ---------- 信封样本（shape 复刻 spike_v11：{code,data:{DataV2:{data:{...}}}}） ----------

def mk_env(payload: dict) -> str:
    return json.dumps({
        "code": "200",
        "data": {"DataV2": {
            "ret": ["SUCCESS::接口调用成功"],
            "data": {"msg": "Success.", "code": "SUCCESS", "data": payload,
                     "requestId": "d3d993b4-test", "success": True},
            "success": True, "httpStatus": 200, "errorCode": "",
            "api": "zeldaHttp.apikeyMgr./tokenplan/personal/api/v2/x", "errorMsg": ""}},
        "httpStatusCode": "200"})


USAGE_ENV = mk_env({"per1MonthPercentage": 0.14572871666666667,
                    "per1MonthResetTime": 1793203200000})
SUB_ENV = mk_env({"specCode": "lite", "endTime": 1793203200000})
QUOTA_ENV = mk_env({"lite": {"monthly": 100000}})
ADDON_ENV = mk_env({"items": [{"remainingCredits": 100, "totalCredits": 500}]})
POLL_OK = {"ok": True, "state": "live",
           "data": {"subscription": SUB_ENV, "quota_config": QUOTA_ENV,
                    "usage": USAGE_ENV, "addon": ADDON_ENV}}

# ---------- 假 subprocess 件 ----------

class FakeStdin:
    def __init__(self, proc):
        self._p = proc
        self.closed_flag = False

    def write(self, s):
        self._p.writes.append(s)
        self._p._on_line(s)

    def flush(self):
        pass

    def close(self):
        self.closed_flag = True
        self._p._q.put(None)          # stdout EOF → reader 线程收尾


class FakeProc:
    """stdin 行 → responder(cmd) 产出若干 stdout 行；支持 kill/poll/wait 记录。"""

    def __init__(self, cmd, responder):
        self.cmd = cmd
        self._responder = responder
        self.writes: list[str] = []
        self.killed = False
        self.alive = True
        self._q: queue.Queue = queue.Queue()
        self.stdin = FakeStdin(self)
        self.stdout = self              # 可迭代（reader 线程 for line in …）
        self.stderr = None              # Popen(stderr=fileobj) 下真实 proc.stderr 即 None

    def _on_line(self, s):
        for chunk in s.splitlines():
            obj = json.loads(chunk)
            for out in self._responder(obj) or []:
                self._q.put(out)

    def __iter__(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            yield item

    def poll(self):
        return None if self.alive else 0

    def close(self):
        pass                            # cleanup 关 stdout 句柄（真实 Popen 里即文件对象）

    def kill(self):
        self.killed = True
        self.alive = False
        self._q.put(None)

    def wait(self, timeout=None):
        return 0


class FakePopenFactory:
    def __init__(self, responder, raises=None):
        self.responder = responder
        self.raises = raises
        self.procs: list[FakeProc] = []
        self.attempts = 0               # 含失败的 spawn 尝试次数

    def __call__(self, cmd, **kwargs):
        self.factories_kwargs = kwargs
        self.attempts += 1
        if self.raises:
            raise self.raises
        p = FakeProc(cmd, self.responder)
        self.procs.append(p)
        return p

    @property
    def spawn_count(self):
        return len(self.procs)


def echo_responder(obj):
    """普通命令 → 直接回 {"id":…, "ok":true}。"""
    return [json.dumps({"id": obj.get("id"), "ok": True})]


def make_client(tmp_path, responder, **kw):
    kw.setdefault("timeout", 0.1)
    fac = FakePopenFactory(responder, raises=kw.pop("raises", None))
    c = BailianHelperClient(profile_dir=tmp_path / "wp",
                            log_path=tmp_path / "helper.log",
                            popen=fac, **kw)
    return c, fac


# ==================== client ====================

def test_build_command_frozen_and_dev():
    assert build_command("P:\\dir", frozen=True, executable="TokenWidget.exe") == \
        ["TokenWidget.exe", "--bailian-helper", "--profile-dir", "P:\\dir"]
    cmd = build_command("P:\\dir", frozen=False, executable="py")
    assert cmd == ["py", str(ROOT / "main.py"), "--bailian-helper",
                   "--profile-dir", "P:\\dir"]
    # 红线：不引入隐藏参数（默认 STARTUPINFO；plan §3.4）
    assert not any(f in cmd for f in ("/hidden", "pythonw"))


def test_request_roundtrip_assigns_monotonic_ids(tmp_path):
    c, fac = make_client(tmp_path, echo_responder)
    r1 = c.request({"cmd": "status"})
    r2 = c.request({"cmd": "poll"})
    assert r1["ok"] and r2["ok"]
    ids = [json.loads(w)["id"] for p in fac.procs for w in p.writes if w.strip()]
    assert ids == [1, 2]                     # 单调 id，请求不含调用方 id


def test_event_lines_dispatched_not_blocking(tmp_path):
    def responder(obj):
        if obj.get("cmd") == "poll":
            return [json.dumps({"event": "login_required"}),
                    json.dumps({"id": obj["id"], **POLL_OK})]
        return echo_responder(obj)

    got: list[dict] = []
    c, _ = make_client(tmp_path, responder)
    c.on_event = got.append
    r = c.request({"cmd": "poll"})
    assert r.get("ok") and r["data"]["usage"] == USAGE_ENV
    assert got == [{"event": "login_required"}]   # 事件即时派发、不占响应位


def test_watchdog_timeout_respawns_once_then_unavailable(tmp_path):
    class Clock:
        def __init__(self):
            self.t = 0.0
        def __call__(self):
            return self.t

    c, fac = make_client(tmp_path, lambda obj: [], timeout=0.05,
                        unavailable_s=900.0, time_fn=Clock())
    clock = c._time
    r = c.request({"cmd": "poll"})
    assert r["ok"] is False and r["error"] == "HELPER_ERROR"
    assert fac.spawn_count == 2                        # 超时 → kill+重 spawn 一次
    assert fac.procs[0].killed
    assert not c.available()
    clock.t += 899.0
    assert not c.available()                           # 15min 静默窗未满
    assert c.request({"cmd": "poll"})["error"] == "HELPER_ERROR"
    assert fac.spawn_count == 2                        # 静默窗内不再 spawn
    clock.t += 2.0
    assert c.available()


def test_spawn_failure_marks_unavailable_helper_error(tmp_path):
    c, fac = make_client(tmp_path, echo_responder,
                         raises=FileNotFoundError("no python"))
    r = c.request({"cmd": "poll"})
    assert r["error"] == "HELPER_ERROR"
    assert fac.attempts == 1 and fac.spawn_count == 0 and not c.available()


def test_stderr_redirected_to_log_with_size_cap(tmp_path):
    log = tmp_path / "helper.log"
    log.write_bytes(b"x" * (client_mod.LOG_MAX_BYTES + 1))   # 超限 → 截断重开
    c = BailianHelperClient(profile_dir=tmp_path / "wp", log_path=log,
                            popen=FakePopenFactory(echo_responder), timeout=0.1)
    c.request({"cmd": "poll"})
    kwargs = c._popen.factories_kwargs                       # type: ignore[attr-defined]
    assert kwargs["stderr"] is not subprocess.PIPE and kwargs["stderr"].name == str(log)
    assert kwargs["stdin"] is subprocess.PIPE and kwargs["stdout"] is subprocess.PIPE
    assert "creationflags" not in kwargs                     # 红线：不隐藏窗口
    assert log.stat().st_size < client_mod.LOG_MAX_BYTES


def test_shutdown_sends_cmd_and_closes_stdin(tmp_path):
    c, fac = make_client(tmp_path, echo_responder)
    c.request({"cmd": "status"})
    c.shutdown()
    p = fac.procs[0]
    assert json.loads(p.writes[-1]) == {"cmd": "shutdown"}  # 无 id（协议 §2）
    assert p.stdin.closed_flag


# ==================== source：传输选择与解析等价 ====================

class FakeClient:
    """最小客户端替身：脚本化响应序列 + available 标志 + on_event 槽。"""

    def __init__(self, responses, available=True):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.available_flag = available
        self.on_event = None

    def available(self):
        return self.available_flag

    def request(self, cmd):
        self.calls.append(cmd)
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True, "state": "live", "data": dict(POLL_OK["data"])}


def _patch_legacy(monkeypatch, env_by_api):
    """legacy 路打桩：假 cookie + gw._req 按 url 里的 api 名返回信封（真 call_api 解析）。"""
    monkeypatch.setattr(bailian_mod, "load_bailian_cookie", lambda: "cna=x; login_aliyunid_csrf=y")
    monkeypatch.setattr(gw, "resolve_sec_token", lambda ck: ("tok", "test"))

    def fake_req(url, headers, data=None):
        for key, env in env_by_api.items():
            if key == "addon" and "addon" not in url:
                continue
            if key in url:
                return 200, "application/json", env.encode()
        raise AssertionError(f"unexpected url {url[:120]}")

    monkeypatch.setattr(gw, "_req", fake_req)


def test_parse_envelope_equivalence_legacy_vs_helper(monkeypatch):
    _patch_legacy(monkeypatch, {"subscription": SUB_ENV, "quota-config": QUOTA_ENV,
                                "usage": USAGE_ENV, "addon": ADDON_ENV})
    u_legacy = BailianSource(mode="legacy").fetch()
    fc = FakeClient([{"ok": True, "state": "live", "data": dict(POLL_OK["data"])}])
    u_helper = BailianSource(mode="helper", client=fc).fetch()
    assert u_legacy.ok and u_helper.ok
    d1, d2 = dict(u_legacy.__dict__), dict(u_helper.__dict__)
    d1.pop("fetched_at"); d2.pop("fetched_at")
    assert d1 == d2                                    # 逐字段一致（除时间戳）
    assert u_helper.spec == "lite" and u_helper.total == 100500.0
    assert u_helper.remaining == pytest.approx(100000 * (1 - 0.14572871666666667) + 100)
    assert u_helper.windows[0].label == "月"


def test_helper_need_login_and_no_credential_mapping():
    s = BailianSource(mode="helper", client=FakeClient(
        [{"ok": False, "state": "need_login", "error": "LOGIN_EXPIRED", "detail": "L3 待人工"}]))
    u = s.fetch()
    assert not u.ok and u.error_code == "LOGIN_EXPIRED" and "L3" in (u.error_msg or "")

    s2 = BailianSource(mode="helper", client=FakeClient(
        [{"ok": False, "state": "no_credential", "error": "NO_CREDENTIAL", "detail": "无账密"}]))
    u2 = s2.fetch()
    assert not u2.ok and u2.error_code == "NO_CREDENTIAL"


def test_auto_fallback_when_spawn_fails(monkeypatch, tmp_path):
    """真客户端 spawn 抛 FileNotFoundError → auto 透明降级 legacy 成功，且不再 spawn。"""
    _patch_legacy(monkeypatch, {"subscription": SUB_ENV, "quota-config": QUOTA_ENV,
                                "usage": USAGE_ENV, "addon": ADDON_ENV})
    fac = FakePopenFactory(echo_responder, raises=FileNotFoundError("nope"))
    c = BailianHelperClient(profile_dir=tmp_path / "wp", log_path=tmp_path / "helper.log",
                            popen=fac, timeout=0.05)
    s = BailianSource(mode="auto", client=c)
    u = s.fetch()
    assert u.ok and u.error_code is None               # legacy 兜底成功
    assert fac.attempts == 1                           # 失败即静默窗，本轮不重复 spawn


def test_auto_falls_back_on_helper_error_payload(monkeypatch):
    _patch_legacy(monkeypatch, {"subscription": SUB_ENV, "quota-config": QUOTA_ENV,
                                "usage": USAGE_ENV, "addon": ADDON_ENV})
    fc = FakeClient([{"ok": False, "state": "error", "error": "HELPER_ERROR", "detail": "x"}])
    u = BailianSource(mode="auto", client=fc).fetch()
    assert u.ok                                        # 降级 legacy
    assert fc.calls == [{"cmd": "poll"}]


def test_auto_keeps_login_expired_without_fallback(monkeypatch):
    """helper 走完整登录瀑布仍 need_login → 尊重其判定（plan §3.3），不降级。"""
    called = []
    def boom_cookie():
        called.append(1)
        raise OSError("should not run legacy")
    monkeypatch.setattr(bailian_mod, "load_bailian_cookie", boom_cookie)
    fc = FakeClient([{"ok": False, "state": "need_login", "error": "LOGIN_EXPIRED",
                      "detail": "验证码"}])
    u = BailianSource(mode="auto", client=fc).fetch()
    assert u.error_code == "LOGIN_EXPIRED" and not called


def test_helper_usage_empty_window_after_three_polls(monkeypatch):
    monkeypatch.setattr(bailian_mod.time, "sleep", lambda s: None)  # 免真实 400ms
    empty = mk_env({"someOther": 1})
    fc = FakeClient([{"ok": True, "state": "live",
                      "data": {"subscription": SUB_ENV, "quota_config": QUOTA_ENV,
                               "usage": empty, "addon": ADDON_ENV}}] * 3)
    u = BailianSource(mode="helper", client=fc).fetch()
    assert u.error_code == "EMPTY_WINDOW"
    assert len(fc.calls) == gw.USAGE_ATTEMPTS


def test_helper_addon_null_tolerated():
    data = {"subscription": SUB_ENV, "quota_config": QUOTA_ENV,
            "usage": USAGE_ENV, "addon": None}
    u = BailianSource(mode="helper", client=FakeClient(
        [{"ok": True, "state": "live", "data": data}])).fetch()
    assert u.ok and u.addon_remaining is None
    assert u.total == 100000 and u.remaining == pytest.approx(100000 * (1 - 0.14572871666666667))


def test_helper_addon_error_tolerated():
    """addon 信封 NotLogined 级错误 → 容错，不升级为整体失败（语义同 legacy §4）。"""
    bad = json.dumps({"code": "e", "data": {"DataV2": {"data": {
        "success": False, "code": "LOGIN_NOTLOGINED", "message": "NotLogined"}}}})
    data = {"subscription": SUB_ENV, "quota_config": QUOTA_ENV,
            "usage": USAGE_ENV, "addon": bad}
    u = BailianSource(mode="helper", client=FakeClient(
        [{"ok": True, "state": "live", "data": data}])).fetch()
    assert u.ok and u.addon_remaining is None


def test_mode_legacy_never_touches_client():
    fc = FakeClient([])
    def _boom(cmd):
        raise AssertionError("client must not be used in legacy mode")
    fc.request = _boom
    # load_bailian_cookie 抛 OSError → NO_CREDENTIAL（不打真实 cookie 文件）
    import src.sources.bailian as m
    orig = m.load_bailian_cookie
    m.load_bailian_cookie = lambda: (_ for _ in ()).throw(OSError("stub"))
    try:
        u = BailianSource(mode="legacy", client=fc).fetch()
    finally:
        m.load_bailian_cookie = orig
    assert u.error_code == "NO_CREDENTIAL"


def test_event_stashed_on_source(tmp_path):
    def responder(obj):
        if "id" not in obj:
            return []
        return [json.dumps({"event": "login_required"}),
                json.dumps({"id": obj["id"], **POLL_OK})]
    c, _ = make_client(tmp_path, responder)
    s = BailianSource(mode="helper", client=c)
    u = s.fetch()
    assert u.ok
    assert s.last_event == {"event": "login_required"}
    assert s.event_text == "等待人工登录（助手已弹窗）"
    c.shutdown()


def test_mode_reads_config_default(monkeypatch, tmp_path):
    import src.config as config_mod
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config_mod, "LOCAL_DIR", tmp_path)
    cfg = config_mod.load_config()
    assert cfg["bailian_mode"] == "auto"
    cfg["bailian_mode"] = "BOGUS"
    config_mod.save_config(cfg)
    assert config_mod.load_config()["bailian_mode"] == "auto"   # clamp
    assert BailianSource()._mode() == "auto"                    # 无 override → 读 config
