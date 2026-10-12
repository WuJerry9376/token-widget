"""M26 凭据管理面板测试：设置路由 / 面板按钮与状态行 / 删除凭据流 / drain 刷新钩子。

零真实凭据（auth.* 全 monkeypatch）、零真实弹窗（tkinter.messagebox 打桩）、
零网络零 helper 进程。Tk 段用 withdraw 的隐藏 root（同 test_m7/test_anomaly 纪律）。
"""
from __future__ import annotations

import queue
import sys
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as mb
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import settings_panel as sp                          # noqa: E402
from src import ui as ui_mod                                  # noqa: E402
from src.settings_panel import CredManagePanel                # noqa: E402
from src.sources.base import Usage                             # noqa: E402

# ==================== 路由：设置→百炼「点击配置」→ 管理面板优先 ====================

def _open_bind(app, name):
    panel = sp.SettingsPanel.__new__(sp.SettingsPanel)        # 绕开 Tk 构造，只借方法
    panel.app = app
    panel._open_bind_panel(name)


def test_bailian_entry_prefers_cred_manage_hook():
    calls = []
    app = types.SimpleNamespace(
        _bailian_cred_manage=lambda: calls.append("manage"),
        _bailian_cred_click=lambda: calls.append("click"),
        open_credentials=lambda: calls.append("paste"))
    _open_bind(app, "bailian")
    assert calls == ["manage"]          # 永远可见响应：管理面板优先


def test_bailian_entry_falls_back_to_click_then_paste():
    calls = []
    app = types.SimpleNamespace(
        _bailian_cred_click=lambda: calls.append("click"),
        open_credentials=lambda: calls.append("paste"))
    _open_bind(app, "bailian")
    assert calls == ["click"]           # M25 分流保持（无 manage 钩子的替身）
    calls.clear()
    _open_bind(types.SimpleNamespace(
        open_credentials=lambda: calls.append("paste")), "bailian")
    assert calls == ["paste"]           # 双无钩子 → 旧粘贴面板


def test_other_provider_routing_untouched():
    calls = []
    app = types.SimpleNamespace(
        _bailian_cred_manage=lambda: calls.append("manage"),
        open_key_panel=lambda n: calls.append(("key", n)))
    _open_bind(app, "codex")
    assert calls == [("key", "codex")]


# ==================== 面板（真 Tk，全程 withdraw；auth/messagebox 打桩） ====================

@pytest.fixture()
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无可用桌面会话")
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


class PanelApp:
    """面板所需的最小 app 替身（字体 + 状态取数口 + 四个动作出口计数）。"""

    def __init__(self, root, usages=None, src=None):
        self.root = root
        self.f_title = tkfont.Font(family="Microsoft YaHei UI", size=12,
                                   weight="bold")
        self.f_small = tkfont.Font(family="Microsoft YaHei UI", size=9)
        self.f_small_b = tkfont.Font(family="Microsoft YaHei UI", size=9,
                                     weight="bold")
        self.f_note = tkfont.Font(family="Microsoft YaHei UI", size=8)
        self.usages = usages if usages is not None else []
        self._src = src
        self._print_geo = False
        self._login_busy = False
        self.reauth_calls = 0
        self.reauth_ret = True
        self.opened = 0
        self.modal_calls: list = []

    def _bailian_source(self):
        return self._src

    def reauth_login(self):
        self.reauth_calls += 1
        return self.reauth_ret

    def open_credentials(self):
        self.opened += 1

    def _ask_save_creds_modal(self, on_saved=None):
        self.modal_calls.append(on_saved)


def _widget_texts(w) -> list[str]:
    out: list[str] = []
    for c in w.winfo_children():
        try:
            t = c.cget("text")
        except tk.TclError:
            t = ""
        if isinstance(t, str) and t:
            out.append(t)
        out.extend(_widget_texts(c))
    return out


def _make_panel(tk_root, **over) -> CredManagePanel:
    app = PanelApp(tk_root, **over)
    panel = CredManagePanel(app)
    panel.withdraw()                    # 测试期绝不让卡片闪现
    return panel


def test_panel_buttons_present_and_status_lines(tk_root, monkeypatch):
    monkeypatch.setattr(sp.auth, "load_bailian_login",
                        lambda: ("jerry_x", "SUP3R-SEKRIT"))
    src = types.SimpleNamespace(mode="helper", helper_running=True)
    panel = _make_panel(
        tk_root, usages=[Usage(provider="bailian", ok=True)], src=src)
    try:
        texts = _widget_texts(panel)
        for want in ("弹窗重新登录 / 切换账号", "保存/更新自动登录凭据",
                     "删除自动登录凭据", "手动粘贴 Cookie（兜底）", "关闭"):
            assert want in texts
        state = panel.lbl_state.cget("text")
        assert "会话状态：正常" in state
        assert "常驻助手：运行中" in state
        assert "已保存（j***）" in state
        joined = " | ".join(texts + [state])
        assert "SUP3R-SEKRIT" not in joined and "jerry_x" not in joined
    finally:
        panel.close_card()


def test_panel_status_error_and_down_states(tk_root, monkeypatch):
    monkeypatch.setattr(sp.auth, "load_bailian_login", lambda: None)
    src = types.SimpleNamespace(mode="helper", helper_running=False)
    panel = _make_panel(
        tk_root,
        usages=[Usage(provider="bailian", ok=False, error_code="LOGIN_EXPIRED")],
        src=src)
    try:
        state = panel.lbl_state.cget("text")
        assert "异常（LOGIN_EXPIRED）" in state
        assert "未运行" in state and "未保存" in state
    finally:
        panel.close_card()


def test_panel_cred_read_exception_masked(tk_root, monkeypatch):
    def boom():
        raise OSError("CredReadW failed (error 5)")
    monkeypatch.setattr(sp.auth, "load_bailian_login", boom)
    panel = _make_panel(tk_root, src=None)
    try:
        assert "读取失败" in panel.lbl_state.cget("text")
    finally:
        panel.close_card()


def test_delete_flow_confirms_and_updates(tk_root, monkeypatch):
    asked = []
    deleted = []

    def yesno(title, msg, **kw):
        asked.append((title, msg))
        return True

    monkeypatch.setattr(mb, "askyesno", yesno)
    monkeypatch.setattr(sp.auth, "load_bailian_login",
                        lambda: ("jerry_x", "SUP3R-SEKRIT"))

    def fake_delete():
        deleted.append(1)
        monkeypatch.setattr(sp.auth, "load_bailian_login", lambda: None)
        return True

    monkeypatch.setattr(sp.auth, "delete_bailian_login", fake_delete)
    panel = _make_panel(tk_root, src=None)
    try:
        panel._delete_creds()
        assert len(asked) == 1 and deleted == [1]
        assert "已删除" in panel.status.cget("text")
        assert "未保存" in panel.lbl_state.cget("text")
    finally:
        panel.close_card()


def test_delete_cancelled_does_not_touch_cm(tk_root, monkeypatch):
    monkeypatch.setattr(mb, "askyesno", lambda *a, **k: False)
    calls = []
    monkeypatch.setattr(sp.auth, "delete_bailian_login",
                        lambda: calls.append(1) or True)
    monkeypatch.setattr(sp.auth, "load_bailian_login", lambda: None)
    panel = _make_panel(tk_root, src=None)
    try:
        panel._delete_creds()
        assert calls == []
    finally:
        panel.close_card()


def test_reauth_button_dispatches_and_rejects_busy(tk_root):
    panel = _make_panel(tk_root, src=None)
    try:
        panel._reauth()
        assert panel.app.reauth_calls == 1
        assert "重新登录" in panel.status.cget("text")
        panel.app.reauth_ret = False            # 在途/不可用 → 文案提示
        panel._reauth()
        assert "请稍候" in panel.status.cget("text") or "未运行" in panel.status.cget("text")
    finally:
        panel.close_card()


def test_save_button_reuses_modal_with_refresh_hook(tk_root):
    panel = _make_panel(tk_root, src=None)
    try:
        panel._save_creds()
        assert len(panel.app.modal_calls) == 1
        assert panel.app.modal_calls[0] is panel.update_status or \
            callable(panel.app.modal_calls[0])
    finally:
        panel.close_card()


def test_paste_cookie_opens_panel_and_closes_manage(tk_root):
    panel = _make_panel(tk_root, src=None)
    assert panel.alive()
    panel._paste_cookie()
    assert panel.app.opened == 1
    assert not panel.alive()                    # 兜底接管：管理面板让位


# ==================== drain → 面板状态刷新钩子（getattr 纪律） ====================

def test_drain_updates_manage_panel_status_on_ok(monkeypatch):
    monkeypatch.setattr(mb, "showinfo", lambda *a, **k: None)   # 免真弹窗阻塞
    refreshed = []
    app = types.SimpleNamespace(
        _login_q=queue.Queue(), _login_busy=True, _quitting=False,
        refreshed=0,
        refresh=lambda: setattr(app, "refreshed", app.refreshed + 1),
        _cred_manage=types.SimpleNamespace(
            update_status=lambda: refreshed.append(1)))
    app._login_q.put(("reauth", {"ok": True}))
    _drain = ui_mod.NoteApp._cred_login_drain
    _drain(app)
    assert refreshed == [1]
    assert app.refreshed == 1


def test_drain_survives_dead_panel(tk_root, monkeypatch):
    """面板已关：update_status 内部 alive 守卫 + drain 外层 try 双保险。"""
    monkeypatch.setattr(mb, "showinfo", lambda *a, **k: None)
    panel = _make_panel(tk_root, src=None)
    app = types.SimpleNamespace(
        _login_q=queue.Queue(), _login_busy=True, _quitting=False,
        refresh=lambda: None, _render=lambda: None, _cred_manage=panel)
    panel.close_card()
    app._login_q.put(("reauth", {"ok": True}))
    ui_mod.NoteApp._cred_login_drain(app)       # 不得抛
