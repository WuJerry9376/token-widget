r"""CM 通用凭据（百炼登录账密，协议 §8）回归：save/load/delete 往返 + 512B 上限。

- 一次性测试目标：monkeypatch auth.CM_TARGET 为 token-widget-test-<rand>，
  全程不触碰真实 CM_TARGET，绝不读写 local\ 文件（bailian_cookie.dpapi 等）；
- teardown 幂等再删（fixture 内），真实机凭据不留痕；
- TOKENWIDGET_NO_CM=1 → 跳过（CM 写入类案例无法在受限环境跑）。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import auth  # noqa: E402

no_cm = pytest.mark.skipif(os.environ.get("TOKENWIDGET_NO_CM") == "1",
                           reason="CM 写入类测试被 TOKENWIDGET_NO_CM=1 禁用")

FAKE_USER = "cm-test-user"
FAKE_PASS = "cm-test-passw0rd"


@pytest.fixture
def cm_target(monkeypatch):
    """一次性随机测试目标；teardown 幂等删除。"""
    target = f"token-widget-test-{uuid.uuid4().hex[:8]}"
    assert target != auth.CM_TARGET  # 守护：绝不落在真实目标上
    monkeypatch.setattr(auth, "CM_TARGET", target)
    yield target
    try:
        auth.delete_bailian_login()
    except Exception:
        pass


@no_cm
def test_roundtrip_save_load_delete(cm_target):
    auth.save_bailian_login(FAKE_USER, FAKE_PASS)
    assert auth.load_bailian_login() == (FAKE_USER, FAKE_PASS)
    assert auth.delete_bailian_login() is True
    assert auth.load_bailian_login() is None
    assert auth.delete_bailian_login() is False   # 幂等：不存在→False


@no_cm
def test_save_overwrites_existing(cm_target):
    auth.save_bailian_login(FAKE_USER, FAKE_PASS)
    auth.save_bailian_login(FAKE_USER + "-2", FAKE_PASS + "-2")
    assert auth.load_bailian_login() == (FAKE_USER + "-2", FAKE_PASS + "-2")


@no_cm
def test_load_absent_returns_none(cm_target):
    assert auth.load_bailian_login() is None


@no_cm
def test_unicode_password_roundtrip(cm_target):
    pw = "pässwörd-中文-🎉"   # 含增补平面字符，UTF-16-LE 代理对不得被截断
    auth.save_bailian_login(FAKE_USER, pw)
    assert auth.load_bailian_login() == (FAKE_USER, pw)


def test_size_limit_rejects_over_512_bytes(cm_target):
    pw = "x" * 257               # UTF-16-LE = 514B > 512
    with pytest.raises(ValueError) as ei:
        auth.save_bailian_login(FAKE_USER, pw)
    msg = str(ei.value)
    assert pw not in msg and FAKE_USER not in msg   # 异常不含明文
    assert auth.load_bailian_login() is None        # 未写入（该断言需 CM 可读）


@no_cm
def test_size_limit_boundary_512_bytes_ok(cm_target):
    pw = "x" * 256               # UTF-16-LE 恰 512B，允许
    auth.save_bailian_login(FAKE_USER, pw)
    assert auth.load_bailian_login() == (FAKE_USER, pw)
