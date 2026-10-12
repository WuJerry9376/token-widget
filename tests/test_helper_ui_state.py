"""M25 车道测试：dev spawn 控制台闪烁修复（pythonw 替换）+ helper 感知凭据入口。

纯逻辑单测（无 Tk 窗口、零网络、零 spawn）：build_command 解释器替换、
BailianSource.helper_running/interactive_login 探测语义、NoteApp 凭据 pill
的 helper/粘贴分流（假 app 借用未绑定方法，queue 回投全同步驱动）。
"""
from __future__ import annotations

import queue
import sys
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import ui as ui_mod                                  # noqa: E402
from src.sources.bailian import BailianSource                 # noqa: E402
from src.sources.bailian_client import build_command          # noqa: E402
from src.sources.base import Usage                            # noqa: E402

# ==================== Task 1: build_command pythonw 替换 ====================

def _mk_exe(tmp_path, name="python.exe"):
    exe = tmp_path / name
    exe.write_text("")
    return exe


def test_dev_python_exe_swapped_to_sibling_pythonw(tmp_path, monkeypatch):
    py = _mk_exe(tmp_path)
    pw = tmp_path / "pythonw.exe"
    pw.write_text("")
    monkeypatch.setattr(sys, "executable", str(py))
    cmd = build_command("P:\\dir", frozen=False)
    assert cmd[0] == str(pw)                       # 仅换解释器
    assert cmd[1] == str((ROOT / "main.py").resolve())
    assert cmd[:1] != [str(py)]


def test_dev_keeps_python_exe_when_no_pythonw(tmp_path, monkeypatch):
    py = _mk_exe(tmp_path)
    monkeypatch.setattr(sys, "executable", str(py))
    cmd = build_command("P:\\dir", frozen=False)
    assert cmd[0] == str(py)                       # 无兄弟 pythonw → 原样


def test_frozen_path_not_swapped(tmp_path, monkeypatch):
    py = _mk_exe(tmp_path)
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(py))
    cmd = build_command("P:\\dir", frozen=True, executable=str(py))
    assert cmd == [str(py), "--bailian-helper", "--profile-dir", "P:\\dir"]


def test_other_executable_untouched(tmp_path):
    pw = _mk_exe(tmp_path, "pythonw.exe")          # 已是 pythonw → 不再动
    cmd = build_command("P:\\dir", frozen=False, executable=str(pw))
    assert cmd[0] == str(pw)
    # 红线：除解释器替换外不引入隐藏参数（默认 STARTUPINFO；plan §3.4）
    assert not any(f in cmd for f in ("/hidden", "-WindowStyle", "SW_HIDE"))


# ==================== Task 2.1: BailianSource helper 感知接口 ====================

class FakeProc:
    def __init__(self, alive=True):
        self._alive = alive

    def poll(self):
        return None if self._alive else 0


class FakeClient:
    def __init__(self, resp=None, alive=True, avail=True):
        self._proc = FakeProc(alive) if alive else None
        self._avail = avail
        self.resp = {"ok": True, "state": "logged_in"} if resp is None else resp
        self.cmds = []
        self.on_event = None

    def available(self):
        return self._avail

    def request(self, cmd):
        self.cmds.append(cmd)
        return self.resp


def make_source(client, mode="auto"):
    s = BailianSource(mode=mode, client=client)
    return s


def test_interactive_login_passthrough_when_helper_running():
    c = FakeClient()
    s = make_source(c, mode="helper")
    assert s.helper_running is True
    assert s.mode == "helper"
    assert s.interactive_login() == c.resp
    assert c.cmds == [{"cmd": "login_interactive"}]


def test_interactive_login_none_when_no_process():
    s = make_source(FakeClient(alive=False))
    assert s.helper_running is False
    assert s.interactive_login() is None


def test_interactive_login_none_when_silence_window():
    c = FakeClient(avail=False)                   # 15min 静默窗 → available False
    s = make_source(c)
    assert s.helper_running is False
    assert s.interactive_login() is None
    assert c.cmds == []                           # 未发起任何请求


def test_interactive_login_none_when_client_missing():
    s = make_source(FakeClient())
    s._client = None
    assert s.interactive_login() is None


def test_interactive_login_swallows_request_exception():
    c = FakeClient()
    c.request = lambda cmd: (_ for _ in ()).throw(RuntimeError("boom"))
    s = make_source(c)
    assert s.interactive_login() is None


# ==================== M26 Task: reauth（source 透传 + ui kind 分流） ====================

def test_reauth_login_passthrough_when_helper_running():
    c = FakeClient()
    s = make_source(c, mode="helper")
    assert s.reauth_login() == c.resp
    assert c.cmds == [{"cmd": "reauth"}]


def test_reauth_login_none_when_helper_down_or_client_missing():
    s = make_source(FakeClient(alive=False))
    assert s.reauth_login() is None               # 进程死 → 不发起
    c = FakeClient()
    s2 = make_source(c)
    assert s2.reauth_login() == c.resp
    s2._client = None
    assert s2.reauth_login() is None              # client 缺失 → None


def test_reauth_login_swallows_exception_and_clears_inflight():
    c = FakeClient()
    c.request = lambda cmd: (_ for _ in ()).throw(RuntimeError("boom"))
    s = make_source(c)
    assert s.reauth_login() is None
    assert s._reauth_inflight is False            # finally 必清，poll 不被永久压制


def test_reauth_inflight_suppresses_poll():
    """reauth 占用 helper 串行队列：在途时 _fetch_via_helper 不发 poll
    （client.login_inflight 只认 login_interactive，source 侧自补旗标）。"""
    c = FakeClient()
    s = make_source(c, mode="helper")
    s._reauth_inflight = True
    u = s._fetch_via_helper()
    assert u is not None and u.ok is False and u.error_code == "LOGIN_EXPIRED"
    assert c.cmds == []                            # 未写入任何命令


class TimeoutClient(FakeClient):
    """request 带 timeout 形参（真 client 签名）：reauth 应传 LOGIN_TIMEOUT。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.timeouts = []

    def request(self, cmd, timeout=None):
        self.cmds.append(cmd)
        self.timeouts.append(timeout)
        return self.resp


def test_reauth_login_uses_login_watchdog():
    from src.sources.bailian_client import LOGIN_TIMEOUT_SECONDS
    c = TimeoutClient()
    s = make_source(c, mode="helper")
    s.reauth_login()
    assert c.timeouts == [LOGIN_TIMEOUT_SECONDS]   # 660s：免 45s 看门狗杀弹窗


# ==================== Task 2.2: ui 凭据 pill 分流（假 app，无 Tk） ====================

class FakeApp:
    """借用 NoteApp 的实现做纯逻辑驱动（不建 root/不画布）。"""
    _bailian_source = ui_mod.NoteApp._bailian_source
    _bailian_cred_click = ui_mod.NoteApp._bailian_cred_click
    _cred_login_work = ui_mod.NoteApp._cred_login_work
    _cred_login_drain = ui_mod.NoteApp._cred_login_drain
    _cred_ui = ui_mod.NoteApp._cred_ui

    def __init__(self, src):
        self.sched = types.SimpleNamespace(sources=[s for s in (src,) if s])
        self._login_q: queue.Queue = queue.Queue()
        self._login_busy = False
        self._quitting = False
        self.opened = 0
        self.refreshed = 0
        self.rendered = 0

    def open_credentials(self):
        self.opened += 1

    def refresh(self):
        self.refreshed += 1

    def _render(self):
        self.rendered += 1


def u_cred(code="LOGIN_EXPIRED"):
    return Usage(provider="bailian", ok=False, error_code=code, error_msg="x")


def _drain_with_result(app, timeout=2.0):
    """等 worker 线程回包后在主线程手动 drain。"""
    deadline = time.time() + timeout
    while app._login_q.empty() and time.time() < deadline:
        time.sleep(0.01)
    app._cred_login_drain()


def test_click_opens_panel_when_no_source_in_sched():
    app = FakeApp(None)                            # 测试/空源环境（同 test_render 场景）
    app._bailian_cred_click()
    assert app.opened == 1


def test_click_opens_panel_in_legacy_mode():
    app = FakeApp(make_source(FakeClient(), mode="legacy"))
    app._bailian_cred_click()
    assert app.opened == 1                         # 旧行为保持：直接粘贴面板


def test_click_opens_panel_when_helper_not_running():
    app = FakeApp(make_source(FakeClient(alive=False)))
    app._bailian_cred_click()
    assert app.opened == 1


def test_click_threads_interactive_login_when_helper_running():
    c = FakeClient(resp={"ok": True})
    app = FakeApp(make_source(c))
    app._bailian_cred_click()
    assert app.opened == 0                         # 未同步开面板（不阻塞 mainloop）
    _drain_with_result(app)
    assert app._login_busy is False
    assert app.refreshed == 1                      # 登录成功 → 立即刷新
    assert c.cmds == [{"cmd": "login_interactive"}]


def test_click_busy_guard_starts_single_thread():
    c = FakeClient()
    c.request = lambda cmd: time.sleep(0.3) or {"ok": True}
    app = FakeApp(make_source(c))
    app._bailian_cred_click()
    n_threads = threading_count()
    app._bailian_cred_click()                      # 在途 → 直接吞掉
    assert app._login_busy is True
    assert threading_count() == n_threads          # 无第二个 worker
    _drain_with_result(app, timeout=3.0)


def test_drain_falls_back_to_panel_when_login_returns_none():
    """点击时 helper 尚活、回包前死掉（interactive_login → None）→ 回落粘贴面板。"""
    app = FakeApp(make_source(FakeClient()))
    app._login_q.put(None)
    app._cred_login_drain()
    assert app.opened == 1
    assert app._login_busy is False


def test_cred_ui_shows_event_text_when_helper_mode():
    src = make_source(FakeClient())
    src.last_event = {"event": "login_required"}
    app = FakeApp(src)
    warn, btn, cmd = app._cred_ui(u_cred())
    assert warn == "等待人工登录（助手已弹窗）"
    assert btn == "更新登录凭据…"                  # pill 文案不变（test_anomaly 口径）
    assert cmd == app._bailian_cred_click


def test_cred_ui_default_text_for_legacy_or_no_event():
    app = FakeApp(make_source(FakeClient(), mode="legacy"))
    warn, btn, _ = app._cred_ui(u_cred())
    assert warn == "需重新登录凭据（Cookie 过期）" and btn == "更新登录凭据…"
    app2 = FakeApp(make_source(FakeClient()))      # auto 但无事件 → 原文案
    assert app2._cred_ui(u_cred())[0] == "需重新登录凭据（Cookie 过期）"
    app3 = FakeApp(None)                           # 无源 → 原文案
    assert app3._cred_ui(u_cred())[0] == "需重新登录凭据（Cookie 过期）"


def test_helper_error_stays_out_of_credential_state():
    """Task 2.3 核查：HELPER_ERROR 是基础设施态，不得渲染为橙色凭据档（灰 stale）。"""
    assert "HELPER_ERROR" not in ui_mod.CRED_ERRORS
    assert ui_mod.CRED_ERRORS == {"LOGIN_EXPIRED", "NO_CREDENTIAL", "KEY_INVALID",
                                  "NO_SUBSCRIPTION", "REGION_BLOCKED"}


# ==================== M26: reauth 队列 kind 分流（假 app，无 Tk） ====================

class ReauthFakeApp(FakeApp):
    """在 FakeApp 上补 NoteApp.reauth_login（管理面板出口）；toast 由测试打桩。"""
    reauth_login = ui_mod.NoteApp.reauth_login


def test_reauth_dispatch_threads_reauth_login_and_toasts_on_ok(monkeypatch):
    """管理面板按钮 → daemon 线程 src.reauth_login → 队列 ("reauth", res) →
    drain：refresh + 「登录状态已刷新」toast（reauth 恒用户发起，必须可见）。"""
    toasts = []
    import tkinter.messagebox as mb
    monkeypatch.setattr(mb, "showinfo",
                        lambda title, msg, **k: toasts.append((title, msg)))
    c = TimeoutClient(resp={"ok": True, "state": "live"})
    app = ReauthFakeApp(make_source(c, mode="helper"))
    assert app.reauth_login() is True
    assert app.reauth_login() is False                 # busy 单飞共享：在途拒绝
    _drain_with_result(app)
    assert c.cmds == [{"cmd": "reauth"}]
    assert app.refreshed == 1
    assert toasts == [("重新登录", "登录状态已刷新")]
    assert app._login_busy is False


def test_reauth_login_false_when_helper_down_legacy_or_no_hook():
    app = ReauthFakeApp(make_source(FakeClient(), mode="legacy"))
    assert app.reauth_login() is False                 # legacy → 不起线程
    app2 = ReauthFakeApp(make_source(FakeClient(alive=False)))
    assert app2.reauth_login() is False                # helper 未运行
    app3 = ReauthFakeApp(None)
    assert app3.reauth_login() is False                # 无源（测试环境）


def test_login_kind_stays_silent_on_ok(monkeypatch):
    """pill 路 kind=login 成功：静默刷新，不弹 toast（行 pill 行为保持）。"""
    toasts = []
    import tkinter.messagebox as mb
    monkeypatch.setattr(mb, "showinfo",
                        lambda *a, **k: toasts.append(a))
    app = FakeApp(make_source(FakeClient(resp={"ok": True})))
    app._bailian_cred_click()
    _drain_with_result(app)
    assert app.refreshed == 1 and toasts == []


def test_drain_reauth_none_falls_back_to_paste_panel():
    """新形态元组 + None（helper 中途死）→ 仍回落粘贴面板（与裸 None 旧形态同义）。"""
    app = FakeApp(make_source(FakeClient()))
    app._login_q.put(("reauth", None))                 # 新形态 None → 回落面板
    app._cred_login_drain()
    assert app.opened == 1 and app._login_busy is False


def threading_count() -> int:
    return sum(1 for t in threading.enumerate()
               if t.name == "bailian-interactive-login" and t.is_alive())
