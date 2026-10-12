r"""车道 C 登录时序 bugfix 回归（test_login_timing）。

Bug：interactive_login 走默认 45s 看门狗 → L3 人工登录（协议 §6，≤10min）中途
helper 被 SIGKILL+respawn（弹窗死亡）；且常规 poll 排队撞 helper 串行队列里的
10min 人工等待，各自 45s 看门狗到点再次误杀。
Fix：request(cmd, timeout=660) 每次调用超时 + login_inflight 旗标（写前置位；
配对响应/login_done|login_failed 事件/超时 respawn/shutdown 任一清除），
_fetch_via_helper 见旗标即闭嘴——不写任何命令，直接回 LOGIN_EXPIRED 语义。

红线：零真实 helper、零网络、零真实 local/（profile/log 全部 tmp_path 注入；
假 Popen 件复用 test_bailian_client）。
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sources.bailian import BailianSource                       # noqa: E402
from src.sources.bailian_client import (LOGIN_TIMEOUT_SECONDS,       # noqa: E402
                                        WATCHDOG_SECONDS,
                                        BailianHelperClient)
from test_bailian_client import (FakePopenFactory, POLL_OK,          # noqa: E402
                                 echo_responder)

LIVE_ACK = {"ok": True, "state": "live", "data": dict(POLL_OK["data"])}
LOGIN_EVENT = json.dumps({"event": "login_required"})


def mk(tmp_path, responder, **kw):
    fac = FakePopenFactory(responder)
    c = BailianHelperClient(profile_dir=tmp_path / "wp",
                            log_path=tmp_path / "helper.log",
                            popen=fac, **kw)
    return c, fac


def _poll_ok(obj):
    if obj.get("cmd") == "poll":
        return [json.dumps({"id": obj["id"], **LIVE_ACK})]
    if obj.get("cmd") == "login_interactive":
        return [LOGIN_EVENT]                     # 人工在途：只发事件，不回包
    return echo_responder(obj)


class StepClock:
    """每次调用前进 step 秒：把「100s 慢回包」压缩成微秒级时序断言。"""

    def __init__(self, step: float = 100.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


# ==================== (a) 660s 看门狗接线与慢回包不误杀 ====================

def test_constants():
    assert WATCHDOG_SECONDS == 45.0
    assert LOGIN_TIMEOUT_SECONDS == 660.0        # L3 10min + 余量（协议 §6/§7）


def test_interactive_login_passes_long_timeout(tmp_path, monkeypatch):
    def responder(obj):
        if obj.get("cmd") == "login_interactive":
            return [json.dumps({"id": obj["id"], **LIVE_ACK})]
        return echo_responder(obj)
    c, fac = mk(tmp_path, responder, timeout=0.3)     # 默认看门狗缩到 0.3s：若被误用必炸
    s = BailianSource(mode="helper", client=c)
    seen: dict = {}
    orig = BailianHelperClient._roundtrip

    def spy(self, cmd, timeout=None):
        if cmd.get("cmd") == "login_interactive":
            seen["timeout"] = timeout
        return orig(self, cmd, timeout)
    monkeypatch.setattr(BailianHelperClient, "_roundtrip", spy)
    assert c.request({"cmd": "status"}).get("ok")      # 预 spawn（helper_running 前提）
    res = s.interactive_login()
    assert res is not None and res["ok"]
    assert seen["timeout"] == LOGIN_TIMEOUT_SECONDS    # 660，不是默认 45/0.3
    assert not fac.procs[-1].killed and fac.spawn_count == 1


def test_slow_login_ack_100s_survives_default_45s_would_kill(tmp_path):
    """假时钟步进 100s/拍：660s 路收包无 kill；对照 45s 路同拍即 watchdog kill+respawn。"""
    def responder(obj):
        if obj.get("cmd") == "login_interactive":
            return [json.dumps({"id": obj["id"], **LIVE_ACK})]
        return echo_responder(obj)
    c, fac = mk(tmp_path / "a", responder)
    c._mono = StepClock(100.0)
    r = c.request({"cmd": "login_interactive"}, timeout=LOGIN_TIMEOUT_SECONDS)
    assert r["ok"] and not fac.procs[0].killed and fac.spawn_count == 1
    assert c.login_inflight is False

    c2, fac2 = mk(tmp_path / "b", responder)
    c2._mono = StepClock(100.0)
    r2 = c2.request({"cmd": "poll"})                    # 旧默认看门狗 → 100s > 45s → 误杀
    assert r2["ok"] is False and r2["error"] == "HELPER_ERROR"
    assert fac2.procs[0].killed and fac2.spawn_count == 2


# ==================== (b) 在途 poll：不写命令、回 LOGIN_EXPIRED ====================

def test_poll_silenced_while_login_inflight(tmp_path):
    c, fac = mk(tmp_path, _poll_ok)
    c.login_inflight = True
    u = BailianSource(mode="helper", client=c).fetch()
    assert not u.ok and u.error_code == "LOGIN_EXPIRED"
    assert "等待人工登录中" in (u.error_msg or "")
    assert fac.spawn_count == 0                         # 连 spawn 都不发起


def test_auto_mode_inflight_no_legacy_fallback(monkeypatch, tmp_path):
    def _boom():
        raise AssertionError("legacy must not run while login inflight")
    monkeypatch.setattr("src.sources.bailian.load_bailian_cookie", _boom)
    c, fac = mk(tmp_path, _poll_ok)
    c.login_inflight = True
    u = BailianSource(mode="auto", client=c).fetch()
    assert u.error_code == "LOGIN_EXPIRED"              # 不在 _FALLBACK_CODES → 不降级
    assert fac.spawn_count == 0


def test_inflight_end_to_end_then_flows(tmp_path):
    c, fac = mk(tmp_path, _poll_ok)
    s = BailianSource(mode="helper", client=c)
    assert c.request({"cmd": "status"}).get("ok")       # 预 spawn 常驻
    assert fac.spawn_count == 1

    results: list = []
    t = threading.Thread(target=lambda: results.append(s.interactive_login()),
                         daemon=True, name="login-thread")
    t.start()
    writes0 = fac.procs[0].writes
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if c.login_inflight and any("login_interactive" in w for w in writes0):
            break
        time.sleep(0.01)
    assert c.login_inflight, "login 写前未置旗标"
    login_id = next(json.loads(w)["id"] for w in writes0 if "login_interactive" in w)

    n0 = sum(len(p.writes) for p in fac.procs)
    u = s.fetch()                                       # 人工在途 → poll 被旗标拦截
    assert u.error_code == "LOGIN_EXPIRED" and "等待人工登录中" in (u.error_msg or "")
    assert sum(len(p.writes) for p in fac.procs) == n0  # 一条命令都没多写
    assert fac.spawn_count == 1                         # 旗标在途无误杀/重 spawn

    proc = fac.procs[0]                                 # helper 人工完成：事件 + 回包
    proc._q.put(json.dumps({"event": "login_done", "method": "manual",
                            "cred_saved": False}) + "\n")
    proc._q.put(json.dumps({"id": login_id, **LIVE_ACK}) + "\n")
    t.join(timeout=2.0)
    assert not t.is_alive() and results and results[0]["ok"]
    assert c.login_inflight is False

    s._cache, s._cache_at = None, 0.0                   # 绕 60s TTL 缓存
    u2 = s.fetch()                                      # 旗标清后 poll 恢复流动
    assert u2.ok
    assert any(json.loads(w).get("cmd") == "poll" for p in fac.procs for w in p.writes)
    c.shutdown()


# ==================== (c) 读线程事件防御清旗标 ====================

class _LinesProc:
    def __init__(self, lines):
        self.stdout = iter(lines)


def test_reader_events_toggle_inflight_flag(tmp_path):
    c = BailianHelperClient(profile_dir=tmp_path / "wp",
                            log_path=tmp_path / "helper.log")
    got: list[dict] = []
    c.on_event = got.append
    c._read_loop(_LinesProc([LOGIN_EVENT + "\n"]))
    assert c.login_inflight is True
    c._read_loop(_LinesProc([json.dumps({"event": "login_done"}) + "\n"]))
    assert c.login_inflight is False
    c._read_loop(_LinesProc([LOGIN_EVENT + "\n"]))
    c._read_loop(_LinesProc([json.dumps({"event": "login_failed",
                                         "reason": "timeout"}) + "\n"]))
    assert c.login_inflight is False
    assert [e["event"] for e in got] == ["login_required", "login_done",
                                         "login_required", "login_failed"]


# ==================== (d) 超时路仍 kill+respawn 且清旗标 ====================

def test_login_timeout_still_respawns_and_clears_flag(tmp_path):
    def responder(obj):
        return []                                       # login 永不回包
    c, fac = mk(tmp_path, responder)
    r = c.request({"cmd": "login_interactive"}, timeout=0.15)
    assert r["ok"] is False and r["error"] == "HELPER_ERROR"
    assert fac.spawn_count == 2                         # 协议 §7：超时 kill+重 spawn 一次
    assert fac.procs[0].killed and fac.procs[1].killed
    assert c.login_inflight is False                    # 超时路径清旗标
    assert not c.available()                             # 二次失败 → 静默窗


def test_shutdown_clears_flag(tmp_path):
    c, fac = mk(tmp_path, echo_responder)
    c.login_inflight = True
    c.shutdown()
    assert c.login_inflight is False


# ==================== (e) 旗标只对 login_interactive 置位 ====================

def test_flag_only_set_for_login_interactive(tmp_path):
    seen: dict = {}

    def responder(obj):
        seen[obj["cmd"]] = c.login_inflight             # 写命令时刻（同步回包前）的旗标
        return echo_responder(obj)
    c, _ = mk(tmp_path, responder)
    for cmd in ({"cmd": "poll"}, {"cmd": "status"},
                {"cmd": "save_creds", "username": "u", "password": "p"}):
        assert c.request(cmd).get("ok")
        assert c.login_inflight is False
    assert seen["poll"] is False and seen["status"] is False
    assert seen["save_creds"] is False                  # 其他命令绝不置位
    assert c.request({"cmd": "login_interactive"},
                     timeout=LOGIN_TIMEOUT_SECONDS).get("ok")
    assert seen["login_interactive"] is True            # login：写前已置位


# ==================== 兼容：旧签名 client（无 timeout 形参）仍可交互登录 ====================

class _Alive:
    def poll(self):
        return None


class OldSigClient:
    def __init__(self):
        self.cmds: list[dict] = []
        self.on_event = None
        self._proc = _Alive()

    def available(self):
        return True

    def request(self, cmd):                             # 无 timeout 形参（他车道替身形态）
        self.cmds.append(cmd)
        return {"ok": True, "state": "live"}


def test_interactive_login_compat_old_signature():
    c = OldSigClient()
    s = BailianSource(mode="helper", client=c)
    assert s.interactive_login() == {"ok": True, "state": "live"}
    assert c.cmds == [{"cmd": "login_interactive"}]
