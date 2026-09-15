"""M3 自测：设置面板 / 凭据续期流 / 自启 dry-run。

运行：`python tests\\test_settings.py`。安全红线：
- config.json / state.json / cookie 全部重定向临时文件；
- 真实 local/bailian_cookie.dpapi 前后字节比对，确认未被覆盖；
- 注册表只做只读快照比对（dry-run 不写；enable/disable 用假函数打桩，不真调）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import auth, autostart, config as config_mod, state as state_mod   # noqa: E402
from src import settings_panel                                              # noqa: E402
from src import version as version_mod                                      # noqa: E402
from src.scheduler import Scheduler                                         # noqa: E402
from src.sources.base import Usage, Window                                  # noqa: E402
from src.state import DEFAULTS                                              # noqa: E402
from src.ui import FAINT, NoteApp                                          # noqa: E402
import main as main_mod                                                     # noqa: E402

REAL_COOKIE = ROOT / "local" / "bailian_cookie.dpapi"
_NOW = datetime.now(timezone.utc)

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian"]}


def u_ok():
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=36700.0, total=60000.0, remaining=16870.0 + 1509.0,
                 pct_used=0.616, resets_at=_NOW + timedelta(hours=7, minutes=9),
                 windows=[Window("7d", 0.616, _NOW + timedelta(hours=7, minutes=9))],
                 addon_remaining=1509.0)


def run(tmp: Path) -> int:
    checks: list[tuple[str, bool, str]] = []

    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            fn()
            checks.append((name, True, ""))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:200]))

    # ---- 全部落盘路径重定向到 tmp ----
    cookie_bytes_before = REAL_COOKIE.read_bytes() if REAL_COOKIE.exists() else None
    cfg_path = tmp / "config.json"
    state_path = tmp / "state.json"
    fake_cookie = tmp / "cookie_test.dpapi"
    orig_cfg_path = config_mod.CONFIG_PATH
    orig_state_path, orig_state_dir = state_mod.STATE_PATH, state_mod.LOCAL_DIR
    orig_cookie_file = auth.BAILIAN_COOKIE_FILE
    config_mod.CONFIG_PATH = cfg_path
    state_mod.STATE_PATH = state_path
    state_mod.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = fake_cookie          # 面板创建时取默认路径 → 落 tmp

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    sched = Scheduler([], poll_seconds=300)
    app = NoteApp(root, dict(CFG), sched, state=dict(DEFAULTS))
    root.withdraw()

    try:
        # ============ 1) auth.save_bailian_cookie 往返（临时路径） ============
        def cookie_roundtrip():
            secret = "login_aliyunid_ticket=FAKE-ticket-value; XSRF-TOKEN=abc123; c=d" * 3
            auth.save_bailian_cookie(secret, path=fake_cookie)
            got = auth.dpapi_unprotect(fake_cookie.read_bytes())
            assert got == secret, "DPAPI 往返不一致"
            assert fake_cookie.read_bytes() != secret.encode("utf-8"), "密文=明文？"
            # 空输入拒绝
            try:
                auth.save_bailian_cookie("", path=fake_cookie)
                raise AssertionError("空 cookie 应报错")
            except ValueError:
                pass

        case("cookie_save_roundtrip_tmp", cookie_roundtrip)

        # ============ 2) 凭据面板：粘贴→保存→清屏→验证成功/失败分支 ============
        def cred_panel_ok():
            app.usages = []
            app.meta = {}
            panel = settings_panel.CredentialPanel(app)   # 默认路径已指 tmp
            panel.withdraw()
            assert any("浏览器打开并登录 bailian.console.aliyun.com" in t
                       for t in _all_text(panel)), "M3c⑧ 步骤1文案"
            panel.txt.insert("1.0", "  fake-cookie=a1b2c3; login_aliyunid_ticket=x"
                                    "9y8z7w6v5u4t3s2r1q; more=1 \n")
            panel._save()
            assert panel.txt.get("1.0", "end").strip() == "", "保存后输入框应清空"
            saved = auth.dpapi_unprotect(fake_cookie.read_bytes())
            assert saved == "fake-cookie=a1b2c3;login_aliyunid_ticket=x9y8z7w6v5u4t3s2r1q;more=1"
            assert "fake-cookie" not in panel.status.cget("text"), "状态行不得含 Cookie"
            # 模拟保存后的成功轮
            app.usages = [u_ok()]
            app.meta = {"ts": time.time() + 5, "next_delay": 300}
            panel._verify()
            assert "验证成功" in panel.status.cget("text"), panel.status.cget("text")
            panel.destroy()

        case("cred_panel_save_verify_ok", cred_panel_ok)

        def cred_panel_fail_still_cred():
            panel = settings_panel.CredentialPanel(app)
            panel.withdraw()
            panel.txt.insert("1.0", "x" * 50 + "=1")
            panel._save()
            app.usages = [Usage(provider="bailian", ok=False,
                                error_code="LOGIN_EXPIRED", error_msg="gone")]
            app.meta = {"ts": time.time() + 5, "next_delay": 300}
            panel._verify()
            st = panel.status.cget("text")
            assert "LOGIN_EXPIRED" in st and panel.alive(), "仍凭据错应保留面板并提示"
            panel.destroy()

        case("cred_panel_verify_still_expired", cred_panel_fail_still_cred)

        def cred_panel_bad_input():
            panel = settings_panel.CredentialPanel(app)
            panel.withdraw()
            panel.txt.insert("1.0", "short")           # 太短
            before = fake_cookie.read_bytes()
            panel._save()
            assert "不是完整 Cookie" in panel.status.cget("text")
            assert fake_cookie.read_bytes() == before, "非法输入不得落盘"
            panel.destroy()

        case("cred_panel_rejects_short_input", cred_panel_bad_input)

        # ============ 3) 设置面板：渲染 + 改即写 config + 双向同步 ============
        def settings_render():
            # M11a（用户裁决移除 OpenAI API 侧）：供应商 3 家（百炼/Go/Codex），
            # 旁注计数 4→3；旧「OpenAI 复选框/预算占位行」断言随之退场。
            panel = settings_panel.SettingsPanel(app)
            panel.withdraw()
            texts = _all_text(panel)
            assert "设置" in texts and "供应商" in texts
            assert not any("OpenAI" in t for t in texts), "M11a：OpenAI 行应已移除"
            assert any("OpenCode Go" in t for t in texts)
            assert not any("Codex（实验性）" in t for t in texts), "M12②：供应商标签已去后缀"
            assert any(t == "Codex" for t in texts), "Codex 复选框仍在（纯标签）"
            assert sum(1 for t in texts if "点击配置" in t) == 3, "三家均应有动态旁注"
            assert any("已绑定" in t or "未绑定" in t for t in texts)
            assert not any("未配置凭据）" in t for t in texts), "旧置灰旁注应已移除"
            assert not any("占位" in t for t in texts), "预算占位行应已移除（入绑定面板）"
            assert any("轮询周期" in t for t in texts)
            # ---- M13：右下角版本签名（逐字校验 + 单一事实源 + 随 build 同步看门） ----
            footer = [t for t in texts if "Jerry Wu" in t]
            assert len(footer) == 1, f"M13：应恰有 1 条署名行，实得 {footer}"
            assert footer[0] == f"v{version_mod.APP_VERSION} · by Jerry Wu", \
                f"M13：署名行文本异常 {footer[0]!r}"
            assert "by Jerry Wu" in footer[0], "署名文本须逐字含 by Jerry Wu"
            # M13 基线 pin 去静态化（fix-2 v1.6.5 门禁冲突定档：静态 pin 与
            # 181-183 双源同步看门矛盾——任何升版必红。改为格式校验，漂移防呆由看门承担）
            _segs = version_mod.APP_VERSION.split(".")
            assert len(_segs) == 3 and all(s.isdigit() for s in _segs), \
                f"M13 版本号须为 X.Y.Z，实得 {version_mod.APP_VERSION!r}"
            assert panel.lbl_ver.cget("foreground") == FAINT, "签名须 FAINT 小字档"
            # 来源校验：改 version.py 的值 → 面板文本跟着变（证明非硬编码）
            orig_ver = version_mod.APP_VERSION
            try:
                version_mod.APP_VERSION = "9.9.9"
                p2 = settings_panel.SettingsPanel(app)
                p2.withdraw()
                assert any(t == "v9.9.9 · by Jerry Wu" for t in _all_text(p2)), \
                    "署名未取自 version.APP_VERSION（硬编码？）"
                p2.destroy()
            finally:
                version_mod.APP_VERSION = orig_ver
            vi = (ROOT / "build" / "version_info.txt").read_text(encoding="utf-8")
            assert version_mod.APP_VERSION in vi, \
                "version.py 与 build/version_info.txt 漂移（fix-2 换装须同步两处）"
            panel.destroy()

        case("settings_render", settings_render)

        def settings_poll():
            panel = settings_panel.SettingsPanel(app)
            panel.withdraw()
            panel.var_poll.set("90")
            panel._save_poll()
            saved = json.loads(cfg_path.read_text(encoding="utf-8"))
            assert saved["poll_seconds"] == 90 and app.sched.poll == 90.0
            # 非法值 → 拒绝并回滚显示
            panel.var_poll.set("30")
            panel._save_poll()
            saved2 = json.loads(cfg_path.read_text(encoding="utf-8"))
            assert saved2["poll_seconds"] == 90, "越界值不得写入"
            assert panel.var_poll.get() == "90", "越界后应回显旧值"
            panel.destroy()

        case("settings_poll_save_rollback", settings_poll)

        def settings_thresholds():
            panel = settings_panel.SettingsPanel(app)
            panel.withdraw()
            panel.var_yellow.set("20"); panel.var_red.set("8")
            panel._save_thr()
            saved = json.loads(cfg_path.read_text(encoding="utf-8"))
            assert abs(saved["low_yellow_pct"] - 0.20) < 1e-9
            assert abs(saved["low_red_pct"] - 0.08) < 1e-9
            assert app.low_yellow == 0.20 and app.low_red == 0.08
            panel.var_yellow.set("5"); panel.var_red.set("10")   # 红>黄 非法
            before = cfg_path.read_bytes()
            panel._save_thr()
            assert cfg_path.read_bytes() == before, "非法阈值不得写盘"
            panel.destroy()

        case("settings_thresholds", settings_thresholds)

        def settings_topmost_sync():
            panel = settings_panel.SettingsPanel(app)
            panel.withdraw()
            app._settings = panel                          # 模拟 open_settings 的登记
            app.set_topmost(not app.topmost)               # 菜单侧改 → 面板同步
            assert panel.var_top.get() == app.topmost
            panel.var_top.set(not panel.var_top.get())   # 面板侧改 → 窗口/菜单/状态同步
            app.set_topmost(bool(panel.var_top.get()))
            st = json.loads(state_path.read_text(encoding="utf-8"))
            assert st["always_on_top"] == app.topmost
            assert bool(root.attributes("-topmost")) == app.topmost
            panel.destroy()

        case("settings_topmost_sync", settings_topmost_sync)

        def settings_providers():
            panel = settings_panel.SettingsPanel(app)
            panel.withdraw()
            panel._pvars["bailian"].set(False)
            panel._apply_providers()
            saved = json.loads(cfg_path.read_text(encoding="utf-8"))
            assert saved["enabled_providers"] == []
            assert app.sched.sources == []
            panel._pvars["bailian"].set(True)
            panel._apply_providers()
            saved = json.loads(cfg_path.read_text(encoding="utf-8"))
            assert saved["enabled_providers"] == ["bailian"]
            assert [s.name for s in app.sched.sources] == ["bailian"]
            panel.destroy()

        case("settings_providers_hotswap", settings_providers)

        def settings_autostart_stub():
            calls = {"en": 0, "dis": 0}
            orig = (autostart.enable, autostart.disable, autostart.is_enabled)
            autostart.enable = lambda: (calls.__setitem__("en", calls["en"] + 1),
                                        autostart.command_line())[1]
            autostart.disable = lambda: calls.__setitem__("dis", calls["dis"] + 1)
            autostart.is_enabled = lambda: False
            try:
                panel = settings_panel.SettingsPanel(app)
                panel.withdraw()
                assert panel.var_auto.get() is False
                panel.var_auto.set(True)
                panel._apply_autostart()
                assert calls["en"] == 1 and calls["dis"] == 0
                panel.var_auto.set(False)
                panel._apply_autostart()
                assert calls["dis"] == 1
                # 写失败 → 复选框回滚
                def boom():
                    raise OSError("denied")
                autostart.enable = boom
                panel.var_auto.set(True)
                panel._apply_autostart()
                assert panel.var_auto.get() is False, "失败后应回滚勾选"
                panel.destroy()
            finally:
                autostart.enable, autostart.disable, autostart.is_enabled = orig

        case("settings_autostart_stub_only", settings_autostart_stub)

        # ============ 4) 自启：命令行 + dry-run 不写注册表 ============
        def autostart_cmdline():
            cmd = autostart.command_line()
            assert cmd.startswith('"') and cmd.endswith('"'), cmd
            assert cmd.count('"') == 4, cmd
            parts = [p.strip('"') for p in cmd.split('" "')]
            assert len(parts) == 2, parts
            for p in parts:
                assert Path(p).is_absolute(), p
            assert "pythonw.exe" in parts[0].lower() or "python.exe" in parts[0].lower()
            assert Path(parts[1]).name == "main.py"
            assert autostart.VALUE_NAME == "token-widget"

        case("autostart_command_line", autostart_cmdline)

        def autostart_dryrun_no_write():
            before = _run_value_names()
            out = subprocess.run(
                [sys.executable, "main.py", "--autostart-dry-run"],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30)
            assert out.returncode == 0, out.stderr
            txt = out.stdout
            assert "dry-run" in txt and "不会写入" in txt
            assert "token-widget" in txt and "CurrentVersion\\Run" in txt.replace("/", "\\")
            assert "main.py" in txt and ("pythonw" in txt.lower() or "python" in txt.lower())
            assert "cookie" not in txt.lower(), "输出不得涉及 Cookie"
            time.sleep(0.3)
            after = _run_value_names()
            assert before == after, "dry-run 改变了注册表 Run 内容！"

        case("autostart_dryrun_no_registry_write", autostart_dryrun_no_write)

    finally:
        try:
            app.quit()
        except Exception:                                # noqa: BLE001
            pass
        config_mod.CONFIG_PATH = orig_cfg_path
        state_mod.STATE_PATH, state_mod.LOCAL_DIR = orig_state_path, orig_state_dir
        auth.BAILIAN_COOKIE_FILE = orig_cookie_file

    # ============ 5) 真实 cookie 文件未被触碰 ============
    cookie_bytes_after = REAL_COOKIE.read_bytes() if REAL_COOKIE.exists() else None
    checks.append(("real_cookie_untouched",
                   cookie_bytes_before == cookie_bytes_after, ""))

    bad = [c for c in checks if not c[1]]
    for name, ok, err in checks:
        print(f"  {'PASS' if ok else 'FAIL':4} {name} {err}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过")
    return 1 if bad else 0


def _all_text(w) -> list[str]:
    out = []
    try:
        t = w.cget("text")
        if isinstance(t, str) and t:
            out.append(t)
    except tk.TclError:
        pass
    for child in w.winfo_children():
        out.extend(_all_text(child))
    return out


def _run_value_names() -> set[str]:
    import winreg
    names = set()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY, 0,
                            winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    names.add(winreg.EnumValue(k, i)[0])
                    i += 1
                except OSError:
                    break
    except FileNotFoundError:
        pass
    return names


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m3_test_") as d:
        raise SystemExit(run(Path(d)))
