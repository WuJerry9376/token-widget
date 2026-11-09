"""自动续期（auto-renewal）测试：LOGIN_EXPIRED 会话掉线 → 自动走既有交互登录机器。

零真实 CM、零 Tk mainloop、零网络（除最后一条线程集成用假 client）。覆盖：
- should_auto_renew 纯决策矩阵（触发 + 每个否决条件）；
- _bailian_error_code 取数（成功/LOGIN_EXPIRED/NO_CREDENTIAL/无 bailian 行）；
- _maybe_auto_renew 接线（假 app，计数 _bailian_cred_click：全条件真命中恰一次并消费
  冷却；各否决条件不触发；无源/退出态不炸；CM 读异常按无凭据处理）；
- 真 _bailian_cred_click 线程机器：触发→起 worker→交互成功→刷新→后续正常轮不再触发；
- BailianSource.has_saved_creds 属性（有凭据 True / 无 None→False / 读异常→False）。
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

import pytest                                        # noqa: E402

from typing import Any                                 # noqa: E402

from src import auth as auth_mod                      # noqa: E402
from src import ui as ui_mod                          # noqa: E402
from src.sources.bailian import BailianSource         # noqa: E402
from src.sources.base import Usage                    # noqa: E402

COOLDOWN = ui_mod.AUTO_RENEW_COOLDOWN


def _cooldown_done_ts() -> float:
    """恒满足冷却的戳：锚在当前 monotonic 之前 2×COOLDOWN。
    不用 0.0——Windows 上 monotonic≈开机秒数，开机 600s 内 0.0 会落进冷却
    窗口造成假红（2026-11-09 重启后实测 3 例），本函数使断言与开机时长无关。"""
    return time.monotonic() - 2 * COOLDOWN


# ==================== should_auto_renew：纯决策矩阵 ====================

def _flags(**over) -> Any:
    d = dict(error_code="LOGIN_EXPIRED", mode="auto", helper_running=True,
             has_creds=True, login_busy=False, elapsed=COOLDOWN + 1.0)
    d.update(over)
    return d


def test_should_auto_renew_all_true_fires():
    assert ui_mod.should_auto_renew(**_flags()) is True


@pytest.mark.parametrize("key,val", [
    ("error_code", "NO_CREDENTIAL"),      # 首登态：不自动弹
    ("error_code", None),                 # 成功轮
    ("mode", "legacy"),                   # 粘贴 Cookie 路径，无 helper
    ("helper_running", False),            # 助手没起来 → 自动弹也没用
    ("has_creds", False),                 # CM 无账密 → 无法静默续期
    ("login_busy", True),                 # 单飞：在途不重复起
    ("elapsed", COOLDOWN - 1.0),          # 冷却未满
])
def test_should_auto_renew_blocked_each_condition(key, val):
    assert ui_mod.should_auto_renew(**_flags(**{key: val})) is False


def test_should_auto_renew_cooldown_boundary_inclusive():
    assert ui_mod.should_auto_renew(**_flags(elapsed=COOLDOWN)) is True
    assert ui_mod.should_auto_renew(**_flags(elapsed=COOLDOWN - 0.001)) is False


# ==================== _bailian_error_code：本轮 bailian 错误码取数 ====================

def _usage(ok, code=None):
    return Usage(provider="bailian", ok=ok, error_code=code)


def test_bailian_error_code_success_none():
    assert ui_mod._bailian_error_code([_usage(True)]) is None


def test_bailian_error_code_login_expired():
    assert ui_mod._bailian_error_code([_usage(False, "LOGIN_EXPIRED")]) == "LOGIN_EXPIRED"


def test_bailian_error_code_no_credential():
    assert ui_mod._bailian_error_code([_usage(False, "NO_CREDENTIAL")]) == "NO_CREDENTIAL"


def test_bailian_error_code_absent_row():
    assert ui_mod._bailian_error_code([Usage(provider="codex", ok=False,
                                              error_code="LOGIN_EXPIRED")]) is None
    assert ui_mod._bailian_error_code([]) is None
    assert ui_mod._bailian_error_code(None) is None


# ==================== _maybe_auto_renew 接线（假 app，计数 _bailian_cred_click）====================

class FakeSource:
    name = "bailian"

    def __init__(self, mode="auto", helper_running=True, creds: Any = True):
        self.mode = mode
        self.helper_running = helper_running
        self._creds = creds

    @property
    def has_saved_creds(self):
        if self._creds == "raise":
            raise RuntimeError("CredReadW failed")
        return self._creds


class ClickCountApp:
    """借 NoteApp 的取数 + 决策接线，仅把 _bailian_cred_click 换成计数器（无 worker）。"""
    _bailian_source = ui_mod.NoteApp._bailian_source
    _maybe_auto_renew = ui_mod.NoteApp._maybe_auto_renew

    def __init__(self, src, code="LOGIN_EXPIRED", cooldown_done=True, busy=False,
                 quitting=False):
        self.sched = types.SimpleNamespace(sources=[s for s in (src,) if s])
        self.usages = [_usage(code is None, code)] if src is not None else []
        self._login_busy = busy
        self._quitting = quitting
        self._auto_renew_ts = _cooldown_done_ts() if cooldown_done else time.monotonic()
        self.verbose = False
        self.clicks = 0

    def _bailian_cred_click(self):
        self.clicks += 1


def _ready_app(**src_over):
    return ClickCountApp(FakeSource(**src_over))


def test_hook_fires_exactly_once_and_consumes_cooldown():
    app = _ready_app()
    app._maybe_auto_renew()
    assert app.clicks == 1                          # 命中 → 调用同路 _bailian_cred_click
    assert app._auto_renew_ts > 0.0                 # 冷却时间戳已消费
    app._maybe_auto_renew()                          # 紧接着再判 → 冷却未满被挡
    assert app.clicks == 1


@pytest.mark.parametrize("over,clicks", [
    ({"creds": False}, 0),                           # 无凭据
    ({"mode": "legacy"}, 0),                         # legacy
    ({"helper_running": False}, 0),                  # helper 未运行
])
def test_hook_blocked_each_source_condition(over, clicks):
    app = ClickCountApp(FakeSource(**over))
    app._maybe_auto_renew()
    assert app.clicks == clicks


@pytest.mark.parametrize("code", ["NO_CREDENTIAL", None])
def test_hook_blocked_by_error_code(code):
    app = ClickCountApp(FakeSource())
    app.usages = [_usage(code is None, code)]
    app._maybe_auto_renew()
    assert app.clicks == 0


def test_hook_blocked_cooldown_fresh():
    app = ClickCountApp(FakeSource(), cooldown_done=False)
    app._maybe_auto_renew()
    assert app.clicks == 0


def test_hook_blocked_login_busy():
    app = _ready_app()
    app._login_busy = True
    app._maybe_auto_renew()
    assert app.clicks == 0


def test_hook_no_source_is_noop():
    app = ClickCountApp(None)
    app._maybe_auto_renew()                          # _bailian_source → None，不得抛
    assert app.clicks == 0


def test_hook_quitting_is_noop():
    app = _ready_app()
    app._quitting = True
    app._maybe_auto_renew()
    assert app.clicks == 0


def test_hook_cm_read_exception_treated_as_no_creds():
    """source.has_saved_creds 抛异常（getattr 触发 property）→ 整体 try 兜住：
    不起 worker、不抛出（= 按无凭据处理）。"""
    app = ClickCountApp(FakeSource(creds="raise"))
    app._maybe_auto_renew()                          # 不得冒泡
    assert app.clicks == 0


# ==================== 线程集成：触发→起 worker→交互成功→刷新→后续正常不触发 ====================

class LiveClientApp:
    """真 _bailian_cred_click/_cred_login_work/_cred_login_drain（起 daemon 线程）。"""
    _bailian_source = ui_mod.NoteApp._bailian_source
    _bailian_cred_click = ui_mod.NoteApp._bailian_cred_click
    _cred_login_work = ui_mod.NoteApp._cred_login_work
    _cred_login_drain = ui_mod.NoteApp._cred_login_drain
    _maybe_auto_renew = ui_mod.NoteApp._maybe_auto_renew

    def __init__(self, src):
        self.sched = types.SimpleNamespace(sources=[src])
        self.usages = [_usage(False, "LOGIN_EXPIRED")]
        self._login_q = queue.Queue()
        self._login_busy = False
        self._quitting = False
        self._auto_renew_ts = _cooldown_done_ts()
        self.verbose = False
        self.refreshed = 0
        self.rendered = 0
        self.opened = 0

    def refresh(self):
        self.refreshed += 1

    def _render(self):
        self.rendered += 1

    def open_credentials(self):
        self.opened += 1

    def interactive_login(self):
        return {"ok": True, "state": "live"}


class _LoginSource:
    name = "bailian"
    mode = "auto"
    helper_running = True
    has_saved_creds = True

    def __init__(self):
        self.calls = 0

    def interactive_login(self):
        self.calls += 1
        return {"ok": True, "state": "live"}


def _wait_busy(app, timeout=2.0):
    deadline = time.time() + timeout
    while app._login_q.empty() and time.time() < deadline:
        time.sleep(0.01)


def test_hook_starts_real_login_thread_and_success_later_round_normal():
    src = _LoginSource()
    app = LiveClientApp(src)
    # 触发口应调真 _bailian_cred_click → 起 worker → 走 src.interactive_login
    app._maybe_auto_renew()
    assert app._login_busy is True                   # 单飞位被占用
    assert src.calls == 1
    _wait_busy(app)
    app._cred_login_drain()                           # 回包：成功 → refresh + 释放 busy
    assert app._login_busy is False
    assert app.refreshed == 1
    # 后续正常轮（成功）→ 不再触发自动续期
    app.usages = [_usage(True)]
    app._auto_renew_ts = _cooldown_done_ts()
    app._maybe_auto_renew()
    assert src.calls == 1
    # 再冷却到点后仍为成功轮 → 依然不触发
    assert src.calls == 1


def test_hook_worker_single_flight_blocks_second_click():
    """在途（busy=True）时后续判定不得再起第二个 worker（冷却之外再加一层保险）。"""
    started = []

    class Slow(_LoginSource):
        def interactive_login(self):
            started.append(1)
            time.sleep(0.2)
            return {"ok": True}

    src = Slow()
    app = LiveClientApp(src)
    app._maybe_auto_renew()
    # 第二次判定：busy 仍 True（未 drain）→ 前置闸挡；且冷却时间戳已消费
    app._auto_renew_ts = _cooldown_done_ts()          # 假造冷却已过，单靠 busy 守
    app._maybe_auto_renew()
    assert app._login_busy is True
    _wait_busy(app, timeout=3.0)
    app._cred_login_drain()
    assert len(started) == 1


# ==================== BailianSource.has_saved_creds 属性（monkeypatch auth）====================

def _src_with_client():
    # 给一个可用 client 桩，确保构造不吞掉 _client（属性本身不碰 client）
    class C:
        def available(self):
            return True
        _proc = None
        on_event = None
    return BailianSource(mode="helper", client=C())


def test_has_saved_creds_true_when_present(monkeypatch):
    monkeypatch.setattr(auth_mod, "load_bailian_login", lambda: ("u", "p"))
    assert _src_with_client().has_saved_creds is True


def test_has_saved_creds_false_when_none(monkeypatch):
    monkeypatch.setattr(auth_mod, "load_bailian_login", lambda: None)
    assert _src_with_client().has_saved_creds is False


def test_has_saved_creds_false_on_read_exception(monkeypatch):
    def boom():
        raise RuntimeError("CredReadW failed (1168)")
    monkeypatch.setattr(auth_mod, "load_bailian_login", boom)
    assert _src_with_client().has_saved_creds is False
