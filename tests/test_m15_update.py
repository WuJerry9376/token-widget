"""M15 更新（GitHub Releases 检查/下载/替换）验收（fixture 零真实网络）。

运行：`python tests\\test_m15_update.py`（Tk 段需可用桌面会话；窗口全程 withdraw）。
纪律：
- check 传输层经 req= 注入；download 经 req_open= 注入；面板段 monkeypatch
  updater.check —— 真实 urllib 触达=违规（updater._req 全局换成拦截桩）；
- config/state/auth.LOCAL_DIR 重定向 temp；真实 local\\ 前后哈希守护（含 update/ 目录
  不得出现在真实 local）；repo slug 全部用假值（零写死仓库）；
- apply 段 spawn/exit_fn 注入替身，**绝不真启动 cmd、绝不退出进程**。
覆盖（任务书）：parse_release 双形态/无 asset/多 exe、is_newer 数字位矩阵、6h 频控、
手动无视频控、空 slug 零网络、代理回落重试一次、download .part 原子 rename+长度校验、
apply cmd 文本断言（路径引号/自删/不涉 local 凭据）、失败清理、设置分组渲染+勾选即存、
手动→下载按钮→二次确认→取消、定时路径只读不自动下载、错误橙字脱敏。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import auth, config as config_mod, settings_panel, state as state_mod   # noqa: E402
from src import updater as up                                                     # noqa: E402
from src.scheduler import Scheduler                                               # noqa: E402
from src.state import DEFAULTS                                                    # noqa: E402
from src.ui import FAINT, OK, ORANGE, NoteApp                                     # noqa: E402
from src.version import APP_VERSION                                               # noqa: E402
import main as main_mod                                                           # noqa: E402

REAL_LOCAL = ROOT / "local"
PX = "http://127.0.0.1:7890"
_now = time.time()

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False, "enabled_providers": ["bailian"],
       "opencode_go": {"auto_detect": True},
       "network": {"proxy_enabled": False, "proxy_url": "",
                   "proxy_targets": ["opencode_go", "codex"]},
       "update": {"enabled": True, "repo": "fake-owner/fake-repo",
                  "last_check": int(_now) - 999999}}


def cfg_with(**upd) -> dict:
    return {**CFG, "update": {**CFG["update"], **upd}}


_net: list[str] = []


def blocked_req(url, headers, opener=None):
    _net.append(str(url)[:80])
    raise AssertionError("真实网络请求被拦截（测试违规）")


class RecReq:
    """check 传输层桩：按脚本返回 (status, hdrs, body) 或抛异常；记录 (url, headers, opener)。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[str, dict, object]] = []

    def __call__(self, url, headers, opener=None):
        self.calls.append((url, dict(headers), opener))
        r = self.script.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def rel_body(tag="v9.9.9", assets=None, body="release notes"):
    return json.dumps({"tag_name": tag, "body": body,
                       "assets": assets if assets is not None else [
                           {"name": "TokenWidget.exe",
                            "browser_download_url": "https://dl.example/TokenWidget.exe"},
                           {"name": "sha256.txt",
                            "browser_download_url": "https://dl.example/sha256.txt"}
                       ]}).encode()


# ------------------------------------------------------- 纯函数 ----

def u1_parse_release_forms() -> str:
    a = up.parse_release(json.loads(rel_body("v1.7.0")))
    assert a == ("1.7.0", "https://dl.example/TokenWidget.exe", "release notes"), a
    b = up.parse_release(json.loads(rel_body("1.7.0", assets=[   # 无主名但唯一 .exe → 兜底
        {"name": "other.exe", "browser_download_url": "https://dl.example/other.exe"}])))
    assert b[0] == "1.7.0" and b[1] == "https://dl.example/other.exe", b
    c = up.parse_release(json.loads(rel_body(assets=[            # 多 .exe 无主名 → 宁缺勿错
        {"name": "a.exe", "browser_download_url": "u1"},
        {"name": "b.exe", "browser_download_url": "u2"}])))
    assert c[1] == "", c
    d = up.parse_release(json.loads(rel_body(assets=[])))        # 无 asset
    assert d[1] == "" and d[0] == "9.9.9", d
    assert up.parse_release("garbage") == ("", "", "")
    assert up.parse_release({}) == ("", "", "")
    return "主名匹配/唯一.exe兜底/多exe留空/无asset/坏JSON 五态"


def u2_is_newer_matrix() -> str:
    cases = {("1.6.10", "1.6.6"): True, ("1.6.6", "1.6.10"): False,   # 数字位非字符串
             ("1.6.6", "1.6.6"): False, ("2.0.0", "1.99.99"): True,
             ("1.7", "1.6.9"): True, ("1.6", "1.6.0"): False,          # 缺位补 0
             ("v1.6.7", "1.6.6"): True, ("1.6.6-beta", "1.6.5"): True,
             ("bad", "1.0.0"): False, (None, "1.0.0"): False}
    for (a, b), want in cases.items():
        assert up.is_newer(a, b) is want, (a, b, want)
    assert up.is_newer("1.0.10", "1.0.9") and not ("1.0.10" > "1.0.9") is True, "反字符串比较"
    return "10 格矩阵（含 1.6.10>1.6.6 数字位）"


def u3_parse_repo() -> str:
    assert up.parse_repo("owner/name") == "owner/name"
    assert up.parse_repo("https://github.com/owner/name") == "owner/name"
    assert up.parse_repo("https://github.com/owner/name.git/") == "owner/name"
    assert up.parse_repo("owner/name ") == "owner/name"
    for bad in ("", None, 123, "just-one", "a/b/c/d", "http://x"):
        assert up.parse_repo(bad) == "" or bad == "a/b/c/d" and up.parse_repo(bad) == "c/d", bad
    return "slug 宽进（URL/.git/空格）与非法拒绝"


def u4_check_ok_and_url() -> str:
    rec = RecReq([(200, {}, rel_body("v9.9.9"))])
    r = up.check(cfg_with(), req=rec, now=_now)
    assert r.ok and r.info.version == "9.9.9", r
    assert r.info.url.endswith("TokenWidget.exe") and r.info.notes == "release notes"
    url, hd, op = rec.calls[0]
    assert url == up.GITHUB_API.format(slug="fake-owner/fake-repo"), url
    assert hd["User-Agent"] == up.UA and op is None, "默认直连 + 固定 UA"
    assert up.GITHUB_API.format(slug="{owner}/{repo}")  # slug 槽位在模板，代码零写死仓库
    return "200→UpdateInfo；URL 由 cfg.slug 拼装；直连"


def u5_rate_limit() -> str:
    rec = RecReq([])
    r = up.check(cfg_with(last_check=int(_now) - 3600), req=rec, now=_now)
    assert r.skipped and not r.ok and rec.calls == [], "6h 内定时检查跳过且零网络"
    rec2 = RecReq([(200, {}, rel_body())])
    r2 = up.check(cfg_with(last_check=int(_now) - 7 * 3600), req=rec2, now=_now)
    assert r2.ok and len(rec2.calls) == 1, "超 6h 放行"
    r3 = up.check(cfg_with(last_check="bad"), req=RecReq([(200, {}, rel_body())]),
                  now=_now)
    assert r3.ok, "last_check 坏型按 0 处理"
    return "6h 内 skipped/超窗放行/坏型兜底"


def u6_force_ignores_limit() -> str:
    rec = RecReq([(200, {}, rel_body())])
    r = up.check(cfg_with(last_check=int(_now) - 10), req=rec, force=True, now=_now)
    assert r.ok and len(rec.calls) == 1, "手动 force 无视频控"
    return "force=True 穿透 6h"


def u7_empty_slug_zero_net() -> str:
    rec = RecReq([])
    r = up.check(cfg_with(repo=""), req=rec)
    assert not r.ok and "update.repo" in r.err and rec.calls == [], r
    r2 = up.check(cfg_with(repo="garbage!!"), req=rec)
    assert not r2.ok and rec.calls == []
    return "空/非法 slug → 未配置文案 + 零网络"


def u8_proxy_fallback_once() -> str:
    refuse = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    rec = RecReq([refuse, (200, {}, rel_body("v9.9.9"))])
    cfg = cfg_with()
    cfg["network"] = {**CFG["network"], "proxy_enabled": True, "proxy_url": PX}
    r = up.check(cfg, req=rec, now=_now)
    assert r.ok, r
    assert rec.calls[0][2] is None, "第一趟直连"
    assert isinstance(rec.calls[1][2], urllib.request.OpenerDirector), "回落经代理"
    rec2 = RecReq([refuse, refuse])
    r2 = up.check(cfg, req=rec2, now=_now)
    assert not r2.ok and "直连与代理均失败" in r2.err, r2.err
    rec3 = RecReq([refuse])
    r3 = up.check(cfg_with(), req=rec3, now=_now)              # 代理未开：只试一次
    assert not r3.ok and "直连失败" in r3.err and len(rec3.calls) == 1
    return "直连败→代理重试一次；双败/无代理文案正确"


def u9_http_and_parse_err() -> str:
    r = up.check(cfg_with(), req=RecReq([(404, {}, b"{}")]), now=_now)
    assert not r.ok and "404" in r.err
    r2 = up.check(cfg_with(), req=RecReq([(200, {}, b"<html>")]), now=_now)
    assert not r2.ok and "非 JSON" in r2.err
    r3 = up.check(cfg_with(), req=RecReq([(200, {}, b'{"tag_name": ""}')]), now=_now)
    assert not r3.ok and "tag_name" in r3.err
    return "HTTP 码/非 JSON/缺 tag 三类错误"


def u10_mark_checked() -> str:
    cfg = cfg_with()
    up.mark_checked(cfg, now=1234.5)
    assert cfg["update"]["last_check"] == 1234
    return "last_check 写回 cfg（调用方保存）"


# ------------------------------------------------------- download ----

class FakeResp:
    def __init__(self, body_chunks, cl=None, status=200, boom_after=None):
        self.chunks = list(body_chunks)
        self.cl = cl
        self.status = status
        self.boom = boom_after
        self.headers = {} if cl is None else {"content-length": str(cl)}
        self.n = 0

    def read(self, _n=-1):
        if self.boom is not None and self.n >= self.boom:
            raise urllib.error.URLError("mid-stream break")
        if not self.chunks:
            return b""
        self.n += 1
        return self.chunks.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeCtx:
    def __init__(self, resp):
        self.resp = resp

    def open(self, req, timeout=None):
        return self.resp


def u11_download_atomic() -> str:
    d = config_mod.LOCAL_DIR / "update"
    body = b"A" * 1000 + b"B" * 500
    ctx = FakeCtx(FakeResp([b"A" * 1000, b"B" * 500], cl=1500))
    path, err = up.download_and_stage("https://dl.example/TokenWidget.exe",
                                      dest_dir=d, req_open=ctx.open)
    assert err == "" and path is not None and path.name == up.NEW_EXE_NAME, err
    assert path.read_bytes() == body and not (d / (up.NEW_EXE_NAME + ".part")).exists()
    return "流式 .part → 长度符 → rename 就位，无 .part 残留"


def u12_download_len_mismatch() -> str:
    d = config_mod.LOCAL_DIR / "update"
    for f in (d / up.NEW_EXE_NAME, d / (up.NEW_EXE_NAME + ".part")):
        if f.exists():
            f.unlink()                                # 前案残留清理（独立断言）
    ctx = FakeCtx(FakeResp([b"X" * 100], cl=999))
    path, err = up.download_and_stage("https://dl.example/x.exe", dest_dir=d,
                                      req_open=ctx.open)
    assert path is None and "长度不符" in err
    assert not (d / (up.NEW_EXE_NAME + ".part")).exists() and not (d / up.NEW_EXE_NAME).exists()
    return "Content-Length 不符 → 弃+清理 .part"


def u13_download_no_cl_and_crash() -> str:
    d = config_mod.LOCAL_DIR / "update"
    ctx = FakeCtx(FakeResp([b"Y" * 10], cl=None))
    path, err = up.download_and_stage("https://dl.example/x.exe", dest_dir=d,
                                      req_open=ctx.open)
    assert path is None and "Content-Length" in err
    ctx2 = FakeCtx(FakeResp([b"Z" * 10, b"W" * 10], cl=999, boom_after=1))
    path2, err2 = up.download_and_stage("https://dl.example/x.exe", dest_dir=d,
                                        req_open=ctx2.open)
    assert path2 is None and "下载失败" in err2                      # 中途断流
    assert not (d / (up.NEW_EXE_NAME + ".part")).exists(), "断流后 .part 必须清理"
    for bad in ("http://insecure/x.exe", "", None):
        p3, e3 = up.download_and_stage(bad, dest_dir=d)
        assert p3 is None and "https" in e3
    return "缺 CL 拒下/断流清理/非 https 拒绝（零网络）"


# ------------------------------------------------------- apply/cmd ----

def u14_cmd_text() -> str:
    s = up.render_restart_cmd(r"C:\w\local\update\TokenWidget.new.exe",
                              r"C:\w\TokenWidget.exe",
                              r"C:\w\local\update\restart_update.cmd")
    assert 'move /Y "C:\\w\\TokenWidget.exe" "C:\\w\\TokenWidget.exe.old"' in s
    assert 'move /Y "C:\\w\\local\\update\\TokenWidget.new.exe" "C:\\w\\TokenWidget.exe"' in s
    assert 'start "" "C:\\w\\TokenWidget.exe"' in s                  # 空标题参数引号语言
    assert 'del /Q "%~f0" 2>nul' in s, "cmd 自删"
    assert "ping -n 4" in s and "if %TRIES% LSS 10" in s, "延时等待+改名重试"
    low = s.lower()
    for taboo in (".dpapi", "auth.json", "config.json", "state.json", "cookie"):
        assert taboo not in low, f"cmd 不得触碰 local 数据：{taboo}"
    assert ".old" in low and low.count('del /q') == 2, "仅删 .old 与 cmd 自身"
    return "cmd 文本：引号/重试/自删/凭据零触碰"


def u15_apply_flow() -> str:
    d = config_mod.LOCAL_DIR / "update"
    d.mkdir(parents=True, exist_ok=True)
    new = d / up.NEW_EXE_NAME
    new.write_bytes(b"MZ fake exe")
    spawned: list = []
    exited: list = []
    err = up.apply_update_and_restart(
        new, current_exe=r"C:\fake\TokenWidget.exe",
        spawn=lambda mode, exe, args: spawned.append((mode, exe, args)),
        exit_fn=lambda code: exited.append(code))
    assert err == "", err
    assert spawned and spawned[0][0] == os.P_DETACH
    assert spawned[0][2][-1] == str(d / up.CMD_NAME), "cmd 路径作为参数"
    text = (d / up.CMD_NAME).read_text(encoding="gbk")
    assert "TokenWidget.new.exe" in text and ".dpapi" not in text
    assert exited == [0], "成功后本进程退出"
    # 缺包 → 原因且不 spawn
    spawned.clear(); exited.clear()
    err2 = up.apply_update_and_restart(d / "nope.exe",
                                       spawn=lambda *a: spawned.append(a),
                                       exit_fn=lambda c: exited.append(c))
    assert "尚未下载" in err2 and not spawned and not exited
    # dev 模式（current=new 同名）拒绝
    err3 = up.apply_update_and_restart(new, current_exe=new,
                                       spawn=lambda *a: None, exit_fn=lambda c: None)
    assert "dev 模式" in err3
    # spawn 失败 → 清理 cmd、不 exit
    def boom(*a):
        raise OSError("spawn denied")
    err4 = up.apply_update_and_restart(new, current_exe=r"C:\fake\TokenWidget.exe",
                                       spawn=boom, exit_fn=lambda c: exited.append(c))
    assert "无法启动更新脚本" in err4 and not (d / up.CMD_NAME).exists() and not exited
    return "写cmd→DETACHED spawn→exit；缺包/dev同名/spawn败 三拒绝路径"


# ------------------------------------------------------- 面板（Tk）----

def texts_of(w, out):
    try:
        t = w.cget("text")
        if isinstance(t, str) and t:
            out.append(t)
    except tk.TclError:
        pass
    for ch in w.winfo_children():
        texts_of(ch, out)
    return out


def pump(root, ms=1200):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        root.update()
        time.sleep(0.02)


def pump_until(root, pred, timeout=4.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        root.update()
        if pred():
            return True
        time.sleep(0.03)
    return False


def u20_panel_render_and_toggle(app, root) -> str:
    clear_cfg(repo="")                                # 未配置态
    panel = settings_panel.SettingsPanel(app)
    panel.withdraw()
    texts = texts_of(panel, [])
    assert any("更新" == t.strip() for t in texts), "分组标题「更新」"
    assert any(t.startswith("自动更新") for t in texts), "☑自动更新"
    assert any(f"v{APP_VERSION}" in t for t in texts), "当前版本灰字"
    assert panel.btn_up_check.cget("text") == "检查更新"
    assert any("未配置" in t for t in texts), "空 repo → 源未配置提示（零网络）"
    assert panel.var_up_auto.get() is True, "DEFAULTS enabled=True"
    panel.var_up_auto.set(False)
    panel._save_update_cfg()
    saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
    assert saved["update"]["enabled"] is False, "勾选改即存"
    panel.destroy()
    return "分组渲染/未配置提示/自动更新勾选即存"


def u21_panel_manual_flow(app, root) -> str:
    clear_cfg(repo="fake-owner/fake-repo", enabled=False)   # 关自动路径，专测手动（避免抢占 busy）
    orig_check = up.check
    up.check = lambda cfg, force=False, **kw: up.CheckResult(
        ok=True, info=up.UpdateInfo(version="9.9.9", url="https://dl.example/t.exe",
                                    notes="新版说明"))
    try:
        panel = settings_panel.SettingsPanel(app)
        panel.withdraw()
        panel._up_refresh(True)                       # 手动检查
        ok = pump_until(root, lambda: "发现新版本" in panel.lbl_up.cget("text"))
        assert ok, panel.lbl_up.cget("text")
        assert panel.lbl_up.cget("fg").lower() == ORANGE.lower()
        assert panel.btn_up_dl.winfo_manager() != "", "手动路径应出现「立即下载并更新」"
        panel._up_ask_confirm()
        assert "继续" in panel.lbl_up.cget("text"), "二次确认（简版内联）"
        assert panel.btn_up_go.winfo_manager() != "" and panel.btn_up_no.winfo_manager() != ""
        panel._up_confirm_cancel()
        assert panel.btn_up_dl.winfo_manager() != "", "取消回退到下载按钮"
        assert panel.btn_up_go.winfo_manager() == ""
        saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
        assert saved["update"]["last_check"] > 0, "检查后 last_check 落盘"
        panel.destroy()
    finally:
        up.check = orig_check
    # 已是最新态
    up.check = lambda cfg, force=False, **kw: up.CheckResult(
        ok=True, info=up.UpdateInfo(version=APP_VERSION, url="u"))
    try:
        clear_cfg(repo="fake-owner/fake-repo", enabled=False)
        p2 = settings_panel.SettingsPanel(app)
        p2.withdraw()
        p2._up_refresh(True)
        assert pump_until(root, lambda: "已是最新" in p2.lbl_up.cget("text"))
        assert p2.lbl_up.cget("fg").lower() == OK.lower()
        p2.destroy()
    finally:
        up.check = orig_check
    return "手动：发现→下载钮→确认→取消；等版=绿已是最新"


def u22_panel_auto_readonly_and_err(app, root) -> str:
    clear_cfg(repo="fake-owner/fake-repo")
    orig_check = up.check
    up.check = lambda cfg, force=False, **kw: up.CheckResult(
        ok=True, info=up.UpdateInfo(version="9.9.9", url="https://dl.example/t.exe"))
    try:
        panel = settings_panel.SettingsPanel(app)     # 开页自动路径（enabled=True）
        panel.withdraw()
        ok = pump_until(root, lambda: "只读" in panel.lbl_up.cget("text"), timeout=6.0)
        assert ok, panel.lbl_up.cget("text")
        assert panel.btn_up_dl.winfo_manager() == "", "定时路径不得给下载钮、绝不自动下载"
        panel.destroy()
    finally:
        up.check = orig_check
    # 错误路径：橙字脱敏
    up.check = lambda cfg, force=False, **kw: up.CheckResult(
        err="网络错误：tunnel http://user:***@1.2.3.4:1 refused")
    try:
        clear_cfg(repo="fake-owner/fake-repo", enabled=False)
        p2 = settings_panel.SettingsPanel(app)
        p2.withdraw()
        p2._up_refresh(True)
        assert pump_until(root, lambda: "检查失败" in p2.lbl_up.cget("text"))
        assert p2.lbl_up.cget("fg").lower() == ORANGE.lower()
        assert "user:pass" not in p2.lbl_up.cget("text")
        p2.destroy()
    finally:
        up.check = orig_check
    return "定时=只读提示无下载钮；错误橙字脱敏"


def clear_cfg(**upd) -> None:
    cfg = {**CFG, "update": {**CFG["update"], **upd}}
    (tmp_root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    if "app" in app_holder:                           # app 未建时仅落盘（run 前置写入）
        app_holder["app"].cfg = dict(cfg)


tmp_root = Path(".")
app_holder: dict = {}


def local_snapshot() -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(REAL_LOCAL.glob("*")) if p.is_file()}


CASES_PURE = [
    ("parse_release_forms", u1_parse_release_forms),
    ("is_newer_matrix", u2_is_newer_matrix),
    ("parse_repo", u3_parse_repo),
    ("check_ok_url", u4_check_ok_and_url),
    ("rate_limit", u5_rate_limit),
    ("force_bypass", u6_force_ignores_limit),
    ("empty_slug_zero_net", u7_empty_slug_zero_net),
    ("proxy_fallback", u8_proxy_fallback_once),
    ("http_parse_err", u9_http_and_parse_err),
    ("mark_checked", u10_mark_checked),
    ("download_atomic", u11_download_atomic),
    ("download_len_mismatch", u12_download_len_mismatch),
    ("download_no_cl_crash", u13_download_no_cl_and_crash),
    ("cmd_text", u14_cmd_text),
    ("apply_flow", u15_apply_flow),
]

CASES_TK = [
    ("panel_render_toggle", u20_panel_render_and_toggle),
    ("panel_manual_flow", u21_panel_manual_flow),
    ("panel_auto_readonly_err", u22_panel_auto_readonly_and_err),
]


def run(tmp: Path) -> int:
    global tmp_root
    tmp_root = tmp
    checks: list[tuple[str, bool, str]] = []
    _net.clear()
    before = local_snapshot()

    def case(name, fn, *a):
        print(f"· {name} …", flush=True)
        try:
            note = fn(*a) or ""
            checks.append((name, True, note))
        except Exception as e:                        # noqa: BLE001
            checks.append((name, False, repr(e)[:240]))

    orig = (auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE,
            config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            up._req, os.environ.get("USERPROFILE"))
    auth.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = tmp / "bailian_cookie.dpapi"
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    os.environ["USERPROFILE"] = str(tmp)
    up._req = blocked_req                             # 未注入传输 = 触网即违规
    clear_cfg()                                       # config 先落盘供 NoteApp
    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    sched = Scheduler([], poll_seconds=300)
    app = NoteApp(root, json.loads((tmp / "config.json").read_text(encoding="utf-8")),
                  sched, state=dict(DEFAULTS))
    app_holder["app"] = app
    root.withdraw()
    try:
        for name, fn in CASES_PURE:
            case(name, fn)
        for name, fn in CASES_TK:
            case(name, fn, app, root)
    finally:
        try:
            app.quit()
        except Exception:                             # noqa: BLE001
            pass
        (auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE,
         config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         up._req, _up) = orig
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
    with tempfile.TemporaryDirectory(prefix="m15_up_") as d:
        raise SystemExit(run(Path(d)))
