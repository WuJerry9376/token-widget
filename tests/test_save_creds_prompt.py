"""§6.4 交互登录成功后「是否保存凭据」：纯决策函数 + drain/模态接线。

- 无 Tk mainloop、无真实 CM、无 local\\ 文件：auth.load/save_bailian_login 一律
  monkeypatch 成假函数（真实 CM_TARGET 永不被读写）；messagebox 与 tk 控件族
  同样打假（test_helper_ui_state 的借未绑定方法风格）。
- 覆盖：四象限决策矩阵、once-per-run 标志、保存实参精确、异常→错误弹窗且
  无明文回显、取消/关闭静默、老 FakeApp（无钩子）行为保持。
"""
from __future__ import annotations

import queue
import sys
import tkinter.messagebox
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import auth, ui as ui_mod                              # noqa: E402
from src.ui import NoteApp, should_prompt_save_creds            # noqa: E402

FAKE_USER = "alice@example.com"
FAKE_PASS = "pw-Sz-secret-123"

# 守护：本文件只打假 auth 函数，真实 CM 目标必须原样不动
assert auth.CM_TARGET == "token-widget/bailian-login"


# ==================== 纯决策函数 ====================

@pytest.mark.parametrize(
    "ok,has_cred,prompted,expect",
    [(True, False, False, True),      # 成功 & 无凭据 & 未问过 → 问
     (False, False, False, False),    # 登录未成功 → 不问
     (True, True, False, False),      # CM 已有凭据 → 不问
     (True, False, True, False),      # 本 run 已问过 → 不再问
     (False, True, True, False)])
def test_should_prompt_save_creds_matrix(ok, has_cred, prompted, expect):
    assert should_prompt_save_creds(ok, has_cred, prompted) is expect


# ==================== 假 widget / 假 messagebox 基建 ====================

class FakeWidget:
    """tk 控件通用替身：记录 kind/opts，暴露 get/destroy 等接线所需方法。"""

    def __init__(self, kind, parent=None, **opts):
        self.kind = kind
        self.parent = parent
        self.opts = opts
        self.text = ""                   # Entry 内容（测试直接赋值）
        self.destroyed = False
        self.protocols: dict = {}
        self.bound: dict = {}

    # 布局/窗口方法（全为 no-op 记账面）
    def grid(self, *a, **k): pass
    def pack(self, *a, **k): pass
    def title(self, t=None): self.title_text = t
    def transient(self, p=None): pass
    def resizable(self, *a): pass
    def bind(self, seq, func=None, **k): self.bound[seq] = func
    def protocol(self, name, func): self.protocols[name] = func
    def focus_set(self): pass
    def grab_set(self): pass
    def destroy(self): self.destroyed = True
    def get(self): return self.text
    def delete(self, *_a): self.text = ""     # Entry.delete(0, END) → 模拟清空


def install_widgets(monkeypatch) -> list[FakeWidget]:
    """把 ui 用的 tk 控件族换成工厂函数，返回创建流水（按 kind 检索）。"""
    made: list[FakeWidget] = []

    def factory(kind):
        def mk(parent=None, **opts):
            w = FakeWidget(kind, parent, **opts)
            made.append(w)
            return w
        return mk

    for kind, cls in (("toplevel", "Toplevel"), ("label", "Label"),
                      ("entry", "Entry"), ("frame", "Frame"),
                      ("button", "Button")):
        monkeypatch.setattr(ui_mod.tk, cls, factory(kind))
    return made


def install_messagebox(monkeypatch, askyesno_answer: bool = True) -> dict:
    log: dict = {"ask": [], "err": [], "warn": []}

    def ask(title, msg, **kw):
        log["ask"].append((title, msg))
        return askyesno_answer

    log["save_calls"] = []

    def showerror(title, msg, **kw): log["err"].append((title, msg))
    def showwarning(title, msg, **kw): log["warn"].append((title, msg))
    monkeypatch.setattr(tkinter.messagebox, "askyesno", ask)
    monkeypatch.setattr(tkinter.messagebox, "showerror", showerror)
    monkeypatch.setattr(tkinter.messagebox, "showwarning", showwarning)
    return log


def install_auth(monkeypatch, load_ret=None, load_exc=None, save_exc=None) -> list:
    calls: list = []

    def load():
        if load_exc is not None:
            raise load_exc
        return load_ret

    def save(u, p):
        calls.append((u, p))
        if save_exc is not None:
            raise save_exc

    monkeypatch.setattr(auth, "load_bailian_login", load)
    monkeypatch.setattr(auth, "save_bailian_login", save)
    return calls


class FakeApp:
    """借 NoteApp 实现做纯接线驱动（同 test_helper_ui_state 风格，含 §6.4 钩子）。"""
    _cred_login_drain = NoteApp._cred_login_drain
    _maybe_prompt_save_creds = NoteApp._maybe_prompt_save_creds
    _ask_save_creds_modal = NoteApp._ask_save_creds_modal

    def __init__(self):
        self._login_q: queue.Queue = queue.Queue()
        self._login_busy = False
        self._quitting = False
        self._creds_prompted = False
        self.root = object()             # 占位：控件侧已全部打假
        self.refreshed = 0
        self.rendered = 0

    def refresh(self): self.refreshed += 1
    def _render(self): self.rendered += 1
    def open_credentials(self): pass


def _entry_pair(made):
    user = next(w for w in made if w.kind == "entry" and "show" not in w.opts)
    pwd = next(w for w in made if w.kind == "entry" and w.opts.get("show") == "*")
    return user, pwd


def _button(made, text):
    return next(w for w in made
                if w.kind == "button" and w.opts.get("text") == text)


# ==================== 接线：drain(ok) → 询问 → 模态 → 保存 ====================

def test_drain_ok_no_cred_prompts_and_saves_exact_args(monkeypatch):
    saves = install_auth(monkeypatch, load_ret=None)
    log = install_messagebox(monkeypatch, askyesno_answer=True)
    made = install_widgets(monkeypatch)
    app = FakeApp()
    app._login_q.put({"ok": True, "state": "live"})
    app._cred_login_drain()

    assert app.refreshed == 1                        # 先刷新（既有语义不动）
    assert len(log["ask"]) == 1                      # 询问一次
    title, msg = log["ask"][0]
    assert title == "保存自动登录凭据?"
    assert "token-widget/bailian-login" in msg
    assert app._creds_prompted is True               # once-per-run 标志置位

    dlg = next(w for w in made if w.kind == "toplevel")
    user, pwd = _entry_pair(made)
    assert user.text == "" and pwd.text == ""        # 密码/账号绝不预填
    user.text, pwd.text = FAKE_USER, FAKE_PASS
    _button(made, "保存").opts["command"]()
    assert saves == [(FAKE_USER, FAKE_PASS)]         # 精确实参转发
    assert not log["err"] and dlg.destroyed
    assert user.text == ""                           # 明文不留在控件里


def test_no_modal_when_answer_no(monkeypatch):
    saves = install_auth(monkeypatch, load_ret=None)
    log = install_messagebox(monkeypatch, askyesno_answer=False)
    made = install_widgets(monkeypatch)
    app = FakeApp()
    app._maybe_prompt_save_creds(True)
    assert len(log["ask"]) == 1
    assert not any(w.kind == "toplevel" for w in made)   # 答否：静默，不开模态
    assert saves == []
    assert app._creds_prompted is True                    # 问过即止


def test_prompt_at_most_once_across_drains(monkeypatch):
    install_auth(monkeypatch, load_ret=None)
    log = install_messagebox(monkeypatch, askyesno_answer=False)
    made = install_widgets(monkeypatch)
    app = FakeApp()
    for _ in range(3):                               # 轮询风暴：连投三次 ok 回包
        app._login_q.put({"ok": True})
        app._cred_login_drain()
    assert len(log["ask"]) == 1                      # 仅询问一次（标志拦截后续）
    assert sum(1 for w in made if w.kind == "toplevel") == 0   # 答否 → 不开模态


def test_no_prompt_when_cred_exists_or_not_ok(monkeypatch):
    install_auth(monkeypatch, load_ret=(FAKE_USER, FAKE_PASS))
    log = install_messagebox(monkeypatch, askyesno_answer=True)
    install_widgets(monkeypatch)
    app = FakeApp()
    app._maybe_prompt_save_creds(True)               # 已有凭据 → 不问
    assert log["ask"] == []
    assert app._creds_prompted is False              # 未问过，标志不动
    app2 = FakeApp()
    install_auth(monkeypatch, load_ret=None)
    app2._maybe_prompt_save_creds(False)             # 登录未成功 → 不问
    assert log["ask"] == []


def test_load_exception_treated_as_no_cred_once(monkeypatch):
    install_auth(monkeypatch, load_exc=RuntimeError("CredReadW failed (error 5)"))
    log = install_messagebox(monkeypatch, askyesno_answer=False)
    install_widgets(monkeypatch)
    app = FakeApp()
    app._maybe_prompt_save_creds(True)
    app._maybe_prompt_save_creds(True)               # 二次触发 → 标志拦截
    assert len(log["ask"]) == 1


# ==================== 模态内部：错误 / 取消 ====================

def _open_modal(monkeypatch):
    log = install_messagebox(monkeypatch, askyesno_answer=True)
    made = install_widgets(monkeypatch)
    app = FakeApp()
    app._ask_save_creds_modal()
    dlg = next(w for w in made if w.kind == "toplevel")
    return app, dlg, made, log


def test_save_error_messagebox_without_secret_echo(monkeypatch):
    saves = install_auth(monkeypatch,
                         save_exc=ValueError("password UTF-16-LE 编码长度 514B "
                                             "超过 512B 上限"))
    _, dlg, made, log = _open_modal(monkeypatch)
    user, pwd = _entry_pair(made)
    user.text, pwd.text = FAKE_USER, FAKE_PASS
    _button(made, "保存").opts["command"]()
    assert saves == [(FAKE_USER, FAKE_PASS)]         # 确实尝试过保存
    assert len(log["err"]) == 1
    joined = " ".join(t + m for t, m in log["err"])
    assert FAKE_PASS not in joined and FAKE_USER not in joined   # 无明文回显
    assert dlg.destroyed


def test_modal_empty_field_warns_without_save(monkeypatch):
    saves = install_auth(monkeypatch)
    _, dlg, made, log = _open_modal(monkeypatch)
    _button(made, "保存").opts["command"]()          # 两字段皆空
    assert saves == [] and log["err"] == []
    assert len(log["warn"]) == 1 and not dlg.destroy()


def test_modal_cancel_and_close_destroy_silently(monkeypatch):
    saves = install_auth(monkeypatch)
    _, dlg, made, log = _open_modal(monkeypatch)
    _button(made, "取消").opts["command"]()
    assert dlg.destroyed and saves == [] and not log["err"]
    # WM_DELETE_WINDOW（右上角 ×）与取消同语义
    _, dlg2, made2, _ = _open_modal(monkeypatch)
    dlg2.protocols["WM_DELETE_WINDOW"]()
    assert dlg2.destroyed and saves == []


# ==================== 行为保持：无钩子的老 FakeApp ====================

def test_drain_backward_compat_without_prompt_hook(monkeypatch):
    """模仿 test_helper_ui_state.FakeApp（只借旧方法）：ok 回包仅刷新，不炸。"""
    class LegacyApp:
        _cred_login_drain = NoteApp._cred_login_drain

        def __init__(self):
            self._login_q: queue.Queue = queue.Queue()
            self._login_busy = False
            self._quitting = False
            self.refreshed = 0

        def refresh(self): self.refreshed += 1

    app = LegacyApp()
    app._login_q.put({"ok": True})
    app._cred_login_drain()                          # 不得 AttributeError
    assert app.refreshed == 1
