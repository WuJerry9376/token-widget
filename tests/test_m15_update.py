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
M16 增补：next_trigger 六路判定/stamp 日期戳/权限预检 probe/NEED_ELEVATION+提权 RunAs
路径/FAILED.txt 消费/橙点亮点灭点+点击路由/开关与缺 update 节双静默/勾选文案纯「自动更新」。
M18 增补：u26 改造为 foot GitHub 图标案例（渲染/隐藏零占位/点击 URL 打桩/失败橙字）；
u28 mirror normalize 两形态+回退链 direct→proxy→mirror 顺序与 digest 校验路径；
u29 digest 不符拒收+文件清理+镜像缺 digest 拒收（直连缺 digest 放行带 note）。
M19 增补：u21 改造为发现新版自动弹 UpdateDialog（标题/vX→vY/发布时间/包大小/发行说明/
两按钮）+ 取消后「查看」重开 + 旧内联按钮文案禁回流；u30 弹窗执行链（立即更新→
download_and_stage/apply 桩、512KB 节流 %、通道审计、失败重试、NEED_ELEVATION 提权档、
关窗后残余事件安全）；u31 纯函数（published/size/notes≤6 行截断）；定时路径 u22 加
「绝不自动弹窗」断言。
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
from src.ui import FAINT, OK, ORANGE, PAPER, NoteApp                                  # noqa: E402
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
                  "last_check": int(_now) - 999999,
                  "last_auto_date": time.strftime("%Y-%m-%d"),
                  "mirror": ""}}   # 当日=已消费，tick 不野触发；M18 mirror 默认不使用


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


def rel_body(tag="v9.9.9", assets=None, body="release notes", digest=None,
             published="2026-09-18T01:02:00Z", size=11263948):
    a: list = assets if assets is not None else [
        {"name": "TokenWidget.exe", "size": size,
         "browser_download_url": "https://dl.example/TokenWidget.exe"},
        {"name": "sha256.txt",
         "browser_download_url": "https://dl.example/sha256.txt"}]
    if digest is not None and assets is None:
        a = [dict(a[0], digest=digest), a[1]]
    return json.dumps({"tag_name": tag, "body": body, "assets": a,
                       "published_at": published}).encode()


# ------------------------------------------------------- 纯函数 ----

def u1_parse_release_forms() -> str:
    a = up.parse_release(json.loads(rel_body("v1.7.0")))
    assert a == ("1.7.0", "https://dl.example/TokenWidget.exe", "release notes",
                 None, 11263948, "2026-09-18T01:02:00Z"), a
    b = up.parse_release(json.loads(rel_body("1.7.0", assets=[   # 无主名但唯一 .exe → 兜底
        {"name": "other.exe", "browser_download_url": "https://dl.example/other.exe"}])))
    assert b[0] == "1.7.0" and b[1] == "https://dl.example/other.exe", b
    assert b[4] == 0, "兜底腿 asset 无 size → 0"
    assert b[5] == "2026-09-18T01:02:00Z", "published 是顶层字段，与选中腿无关"
    c = up.parse_release(json.loads(rel_body(assets=[            # 多 .exe 无主名 → 宁缺勿错
        {"name": "a.exe", "browser_download_url": "u1"},
        {"name": "b.exe", "browser_download_url": "u2"}])))
    assert c[1] == "", c
    d = up.parse_release(json.loads(rel_body(assets=[])))        # 无 asset
    assert d[1] == "" and d[0] == "9.9.9" and d[3] is None and d[4] == 0, d
    assert up.parse_release("garbage") == ("", "", "", None, 0, "")
    assert up.parse_release({}) == ("", "", "", None, 0, "")
    # M18：digest 归一——"sha256:<hex>" / 裸 64hex → "sha256:<hex64>"；畸形 → None
    h = "ab" * 32
    e = up.parse_release(json.loads(rel_body(digest=f"sha256:{h.upper()}")))
    assert e[3] == f"sha256:{h}", e
    f = up.parse_release(json.loads(rel_body(digest=h)))          # 裸 hex 兼容
    assert f[3] == f"sha256:{h}", f
    g = up.parse_release(json.loads(rel_body(digest="sha256:short")))   # 非 64hex → None
    assert g[3] is None, g
    gh = up.parse_release(json.loads(rel_body(digest="md5:" + h)))      # 非 sha256 → None
    assert gh[3] is None, gh
    # M18/M19：digest/size 跟随**选中 asset**（主名匹配腿），不被兜底腿污染
    hi = "cd" * 32
    k = up.parse_release(json.loads(rel_body(assets=[
        {"name": "TokenWidget.exe", "browser_download_url": "https://dl/t.exe",
         "digest": f"sha256:{hi}", "size": 111},
        {"name": "other.exe", "browser_download_url": "https://dl/o.exe",
         "digest": "sha256:" + "ee" * 32, "size": 99999}])))
    assert k[3] == f"sha256:{hi}" and k[4] == 111, k
    # published 非 str → ""；size 非 int（bool/str）→ 0（展示端换算容错）
    m = up.parse_release({"tag_name": "v1", "published_at": 42,
                          "assets": [{"name": "TokenWidget.exe",
                                      "browser_download_url": "u", "size": True}]})
    assert m[4] == 0 and m[5] == "", m
    return "主名/兜底/多exe/无asset/坏JSON/digest 归一跟腿/size·published 容错 九态"


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
    """req_open 注入桩：M18 记录 (full_url, opener) 供回退链顺序/通道断言。"""

    def __init__(self, resp):
        self.resp = resp
        self.calls: list[tuple[str, object]] = []

    def open(self, req, timeout=None, opener=None):
        self.calls.append((str(req.full_url), opener))
        r = self.resp.pop(0) if isinstance(self.resp, list) else self.resp
        if isinstance(r, Exception):
            raise r
        return r


def u11_download_atomic() -> str:
    d = config_mod.LOCAL_DIR / "update"
    body = b"A" * 1000 + b"B" * 500
    ctx = FakeCtx(FakeResp([b"A" * 1000, b"B" * 500], cl=1500))
    r = up.download_and_stage("https://dl.example/TokenWidget.exe",
                              dest_dir=d, req_open=ctx.open)
    assert r.err == "" and r.path is not None and r.path.name == up.NEW_EXE_NAME, r.err
    assert r.path.read_bytes() == body and not (d / (up.NEW_EXE_NAME + ".part")).exists()
    assert r.channel == "direct" and "digest" in r.note, "无 digest 直连放行+note 说明"
    # M18：digest 匹配路径（流式 sha256 校验通过）
    body2 = b"C" * 777
    dig = "sha256:" + hashlib.sha256(body2).hexdigest()
    ctx2 = FakeCtx(FakeResp([body2], cl=len(body2)))
    r2 = up.download_and_stage("https://dl.example/TokenWidget.exe", digest=dig,
                               dest_dir=d, req_open=ctx2.open)
    assert r2.err == "" and r2.channel == "direct" and r2.note == "", (r2.err, r2.note)
    assert r2.path.read_bytes() == body2
    return "流式 .part → 长度符 → rename 就位，无 .part 残留；digest 匹配放行"


def u12_download_len_mismatch() -> str:
    d = config_mod.LOCAL_DIR / "update"
    for f in (d / up.NEW_EXE_NAME, d / (up.NEW_EXE_NAME + ".part")):
        if f.exists():
            f.unlink()                                # 前案残留清理（独立断言）
    ctx = FakeCtx(FakeResp([b"X" * 100], cl=999))
    r = up.download_and_stage("https://dl.example/x.exe", dest_dir=d,
                              req_open=ctx.open)
    assert r.path is None and "长度不符" in r.err
    assert not (d / (up.NEW_EXE_NAME + ".part")).exists() and not (d / up.NEW_EXE_NAME).exists()
    return "Content-Length 不符 → 弃+清理 .part"


def u13_download_no_cl_and_crash() -> str:
    d = config_mod.LOCAL_DIR / "update"
    ctx = FakeCtx(FakeResp([b"Y" * 10], cl=None))
    r = up.download_and_stage("https://dl.example/x.exe", dest_dir=d, req_open=ctx.open)
    assert r.path is None and "Content-Length" in r.err
    ctx2 = FakeCtx(FakeResp([b"Z" * 10, b"W" * 10], cl=999, boom_after=1))
    r2 = up.download_and_stage("https://dl.example/x.exe", dest_dir=d,
                               req_open=ctx2.open)
    assert r2.path is None and "下载失败" in r2.err                     # 中途断流
    assert not (d / (up.NEW_EXE_NAME + ".part")).exists(), "断流后 .part 必须清理"
    for bad in ("http://insecure/x.exe", "", None):
        r3 = up.download_and_stage(bad, dest_dir=d)
        assert r3.path is None and "https" in r3.err
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
    # M16：失败兜底落档（两步各有 echo + rc，路径指向 FAILED.txt）
    assert 'rename_old_failed rc=%errorlevel% tries=%TRIES%> "c:\\w\\local\\update\\failed.txt"'.lower() in low
    assert "move_new_failed rc=%errorlevel%" in low
    s2 = up.render_restart_cmd(r"n.exe", r"o.exe", r"c2\cmd.cmd", failed_path=r"x\f.txt")
    assert 'x\\f.txt' in s2, "failed_path 显式覆盖生效"
    return "cmd 文本：引号/重试/自删/凭据零触碰/FAILED 落档"


def u15_apply_flow() -> str:
    d = config_mod.LOCAL_DIR / "update"
    d.mkdir(parents=True, exist_ok=True)
    new = d / up.NEW_EXE_NAME
    new.write_bytes(b"MZ fake exe")
    W = lambda p: True                                # M16：正常路径=预检通过注入
    spawned: list = []
    exited: list = []
    err = up.apply_update_and_restart(
        new, current_exe=r"C:\fake\TokenWidget.exe", probe=W,
        spawn=lambda mode, exe, args: spawned.append((mode, exe, args)),
        exit_fn=lambda code: exited.append(code))
    assert err == "", err
    assert spawned and spawned[0][0] == os.P_DETACH
    assert spawned[0][2][-1] == str(d / up.CMD_NAME), "cmd 路径作为参数"
    text = (d / up.CMD_NAME).read_text(encoding="gbk")
    assert "TokenWidget.new.exe" in text and ".dpapi" not in text
    assert "failed.txt" in text.lower(), "M16 失败落档行入 cmd"
    assert exited == [0], "成功后本进程退出"
    # 缺包 → 原因且不 spawn
    spawned.clear(); exited.clear()
    err2 = up.apply_update_and_restart(d / "nope.exe", probe=W,
                                       spawn=lambda *a: spawned.append(a),
                                       exit_fn=lambda c: exited.append(c))
    assert "尚未下载" in err2 and not spawned and not exited
    # dev 模式（current=new 同名）拒绝
    err3 = up.apply_update_and_restart(new, current_exe=new, probe=W,
                                       spawn=lambda *a: None, exit_fn=lambda c: None)
    assert "dev 模式" in err3
    # spawn 失败 → 清理 cmd、不 exit
    def boom(*a):
        raise OSError("spawn denied")
    err4 = up.apply_update_and_restart(new, current_exe=r"C:\fake\TokenWidget.exe",
                                       probe=W, spawn=boom, exit_fn=lambda c: exited.append(c))
    assert "无法启动更新脚本" in err4 and not (d / up.CMD_NAME).exists() and not exited
    return "写cmd→DETACHED spawn→exit；缺包/dev同名/spawn败 三拒绝路径"


def u16_next_trigger_matrix() -> str:
    """三触发点判定（纯函数）：enabled 关/空 slug 零动作；startup 一次性；daily 5 点+日期戳。"""
    today_noon = time.mktime(time.strptime("2026-09-20 12:00", "%Y-%m-%d %H:%M"))
    early = time.mktime(time.strptime("2026-09-20 04:30", "%Y-%m-%d %H:%M"))
    d = "2026-09-20"
    assert up.next_trigger(cfg_with(enabled=False), False, today_noon) == ""   # 开关关
    assert up.next_trigger(cfg_with(repo=""), False, today_noon) == ""          # slug 空
    assert up.next_trigger(cfg_with(), False, today_noon) == "startup"
    assert up.next_trigger(cfg_with(), True, early) == ""                       # 未到 5 点
    assert up.next_trigger(cfg_with(), True, today_noon) == "daily"             # 5 点后今日未跑
    assert up.next_trigger(cfg_with(last_auto_date=d), True, today_noon) == ""  # 日期戳防重
    assert up.next_trigger(cfg_with(last_auto_date="2026-09-19"), True,
                           today_noon) == "daily"                               # 跨日再触发
    return "startup/daily/开关/slug/时点/日期戳 六路判定"


def u17_stamp() -> str:
    cfg = cfg_with(last_auto_date="")
    up.stamp_auto_trigger(cfg, "startup", now=1000.4)
    assert cfg["update"]["last_check"] == 1000
    assert cfg["update"].get("last_auto_date", "") == ""            # startup 不记日戳
    up.stamp_auto_trigger(cfg, "daily", now=2000.0)
    assert cfg["update"]["last_check"] == 2000 and len(cfg["update"]["last_auto_date"]) == 10
    c2 = cfg_with()
    up.stamp_auto_trigger(c2, "daily", now=3000.0, attempted=False)  # skipped：只记日戳
    assert c2["update"]["last_check"] == int(_now) - 999999 and c2["update"]["last_auto_date"]
    return "startup 刷 last_check；daily 另记日期戳；skipped 仅日戳"


def u18_probe() -> str:
    ok_dir = tmp_root / "writable"
    ok_dir.mkdir(exist_ok=True)
    assert up.probe_replace_permission(ok_dir / "TokenWidget.exe") is True
    assert not (ok_dir / ".write_test.tmp").exists(), "探测临时文件必删"
    # Windows 目录 chmod 不可靠（readonly 属性不拦创建），用"父目录不存在"模拟不可写
    ghost = tmp_root / "no_such_dir" / "TokenWidget.exe"
    assert up.probe_replace_permission(ghost) is False
    return "可写 True/不可写路径 False；.write_test.tmp 零残留"


def u19_elevation() -> str:
    d = config_mod.LOCAL_DIR / "update"
    d.mkdir(parents=True, exist_ok=True)
    new = d / up.NEW_EXE_NAME
    new.write_bytes(b"MZ")
    spawned: list = []
    exited: list = []
    NO = lambda p: False
    err = up.apply_update_and_restart(new, current_exe=r"C:\ro\TokenWidget.exe", probe=NO,
                                      spawn=lambda *a: spawned.append(a),
                                      exit_fn=lambda c: exited.append(c))
    assert err.startswith(up.NEED_ELEVATION) and "移动位置" in err, err
    assert not spawned and not exited, "预检失败必须不退出、不 spawn"
    # 提权重试：经 PowerShell Start-Process -Verb RunAs（一次 UAC）；cmd 落 TEMP
    err2 = up.apply_update_and_restart(new, current_exe=r"C:\ro\TokenWidget.exe",
                                       elevated=True, probe=NO,
                                       spawn=lambda mode, exe, args: spawned.append((exe, args)),
                                       exit_fn=lambda c: exited.append(c))
    assert err2 == "" and len(spawned) == 1
    exe, args = spawned[0]
    assert "powershell" in exe.lower(), exe
    joined = " ".join(args)
    assert "-Verb RunAs" in joined and "Start-Process" in joined and up.CMD_NAME in joined
    staged_cmd = Path(str(args[-1]))
    assert (staged_cmd.parent / up.FAILED_NAME).name == up.FAILED_NAME
    assert exited == [0]
    # staging 与 TEMP 双不可写 → 指路移动位置（不 spawn 不退出；Windows chmod 不可靠，
    # 用 _writable_dir 注入模拟）
    orig_w = up._writable_dir
    try:
        up._writable_dir = lambda b: False
        spawned.clear(); exited.clear()
        err5 = up.apply_update_and_restart(new, current_exe=r"C:\ro\TokenWidget.exe",
                                           elevated=True, probe=NO,
                                           spawn=lambda *a: spawned.append(a),
                                           exit_fn=lambda c: exited.append(c))
        assert "可写目录" in err5 and not spawned and not exited, err5
    finally:
        up._writable_dir = orig_w
    return "NEED_ELEVATION 不退出；提权=PS -Verb RunAs；双不可写指路移动"


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
    # M16 文案锁：勾选文字纯「自动更新」，旧括注已删（用户点名）
    assert any(t == "自动更新" for t in texts), "勾选文案=自动更新（无括注）"
    assert all("打开本页自动检查一次" not in t for t in texts), "旧括注文案不得回流"
    assert any(f"v{APP_VERSION}" in t for t in texts), "当前版本灰字"
    assert panel.btn_up_check.cget("text") == "检查更新"
    assert any("未配置" in t for t in texts), "空 repo → 源未配置提示（零网络）"
    # M18：镜像源行渲染 + 信任链注记
    assert any(t == "镜像源（可选）" for t in texts), "镜像 Entry 行标签"
    assert any("版本信息始终来自 GitHub 官方 API" in t for t in texts), "FAINT 注记"
    assert panel.ent_mirror.winfo_manager() != "", "Entry 在位"
    assert panel.var_up_auto.get() is True, "DEFAULTS enabled=True"
    panel.var_up_auto.set(False)
    panel._save_update_cfg()
    saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
    assert saved["update"]["enabled"] is False, "勾选改即存"
    panel.destroy()
    return "分组渲染/未配置提示/自动更新勾选即存"


def u21_panel_manual_flow(app, root) -> str:
    """M19 改造（案例迁移非删）：手动发现新版→**自动弹 UpdateDialog**（路径 a）+
    弹窗渲染三要素两按钮 + 取消后「查看」重开（c）+ 单例换新 + 关面板级联散 +
    旧内联下载/确认按钮文案禁回流。等版态不弹。"""
    clear_cfg(repo="fake-owner/fake-repo", enabled=False)   # 关自动路径，专测手动
    orig_check = up.check
    up.check = lambda cfg, force=False, **kw: up.CheckResult(
        ok=True, info=up.UpdateInfo(version="9.9.9", url="https://dl.example/t.exe",
                                    notes="新版说明", size=11263948,
                                    published="2026-09-18T01:02:00Z"))
    try:
        panel = settings_panel.SettingsPanel(app)
        panel.withdraw()
        panel._up_refresh(True)                       # 手动检查
        ok = pump_until(root, lambda: panel._up_dialog is not None
                        and panel._up_dialog.alive())
        assert ok, panel.lbl_up.cget("text")          # a：发现即自动弹
        assert "发现新版本 v9.9.9" in panel.lbl_up.cget("text")
        assert panel.lbl_up.cget("fg").lower() == ORANGE.lower()
        dlg = panel._up_dialog
        dtexts = texts_of(dlg, [])
        assert any(t == "发现新版本 v9.9.9" for t in dtexts), "弹窗标题条"
        assert any(f"当前版本 v{APP_VERSION} → v9.9.9" in t for t in dtexts), "版本行"
        assert any("2026-09-18 01:02 (UTC)" in t for t in dtexts), "发布时间"
        assert any("10.7 MB" in t for t in dtexts), "包大小字节→MB 一位小数"
        assert any("新版说明" in t for t in dtexts), "发行说明"
        assert dlg.btn_go.cget("text") == "立即更新" and dlg.btn_no.cget("text") == "取消"
        assert dlg.btn_go.winfo_manager() != "" and dlg.btn_no.winfo_manager() != ""
        # 旧内联语言禁回流（面板体内；弹窗不在面板子树=独立 Toplevel）
        ptexts = texts_of(panel, [])
        for taboo in ("立即下载并更新", "确认更新", "提权更新"):
            assert all(taboo not in t for t in ptexts), f"{taboo} 回流"
        assert not hasattr(panel, "btn_up_dl") and not hasattr(panel, "btn_up_elev")
        saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
        assert saved["update"]["last_check"] > 0, "检查后 last_check 落盘"
        # 取消 → 弹窗散；状态行「查看」入口仍在（c）且可重开
        dlg.btn_no.invoke()
        assert pump_until(root, lambda: not dlg.alive()), "取消即散"
        assert panel.btn_up_view.winfo_manager() != "", "「查看」入口仍在"
        panel._up_open_dialog()
        assert panel._up_dialog is not dlg and panel._up_dialog.alive(), "查看=重开"
        old = panel._up_dialog
        panel._up_open_dialog()
        assert not old.alive() and panel._up_dialog.alive() \
            and panel._up_dialog is not old, "重复开=先关旧（单例）"
        last = panel._up_dialog
        panel.destroy()
        assert not last.alive(), "关面板级联散弹窗"
    finally:
        up.check = orig_check
    # 已是最新态：绿字、不弹
    up.check = lambda cfg, force=False, **kw: up.CheckResult(
        ok=True, info=up.UpdateInfo(version=APP_VERSION, url="u"))
    try:
        clear_cfg(repo="fake-owner/fake-repo", enabled=False)
        p2 = settings_panel.SettingsPanel(app)
        p2.withdraw()
        p2._up_refresh(True)
        assert pump_until(root, lambda: "已是最新" in p2.lbl_up.cget("text"))
        assert p2.lbl_up.cget("fg").lower() == OK.lower()
        assert p2._up_dialog is None and p2.btn_up_view.winfo_manager() == "", \
            "等版=无弹窗无查看"
        p2.destroy()
    finally:
        up.check = orig_check
    return "手动发现→自动弹窗(标题/三信息/两钮)→取消查看重开→单例→级联散→等版不弹"


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
        # M19 d 路径：定时发现（即便用户在设置页）→ 只读提示，**绝不自动弹窗**、
        # 不给「查看」（橙点出口在 ui 侧），也不触任何下载。
        assert panel._up_dialog is None, "定时路径绝不自动弹（防打扰）"
        assert panel.btn_up_view.winfo_manager() == "", "定时不给「查看」按钮"
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


def u23_panel_failed_note_and_force_open(app, root) -> str:
    """M16：FAILED.txt 消费（橙字一行+读后即删）；橙点 force 路由（面板消费标记并强检一次）。"""
    clear_cfg(repo="fake-owner/fake-repo", enabled=False)
    d = config_mod.LOCAL_DIR / "update"
    d.mkdir(parents=True, exist_ok=True)
    (d / up.FAILED_NAME).write_text("rename_old_failed rc=5 tries=10", encoding="gbk")
    orig_check = up.check
    calls: list = []
    up.check = lambda cfg, force=False, **kw: (calls.append(force),
                                               up.CheckResult(skipped=True))[1]
    try:
        panel = settings_panel.SettingsPanel(app)
        panel.withdraw()
        txt = panel.lbl_up.cget("text")
        assert "上次自动更新未成功" in txt and "rename_old_failed" in txt, txt
        assert not (d / up.FAILED_NAME).exists(), "读后即删（防每次开页重复提醒）"
        panel.destroy()
        # 橙点入口：force 标记 → 面板构建即消费 + 无视 enabled 关也刷一次
        app._upd_force_open = True
        p2 = settings_panel.SettingsPanel(app)
        p2.withdraw()
        assert app._upd_force_open is False, "force 标记面板构建时消费"
        assert pump_until(root, lambda: any(c is True for c in calls)), "force=True 检查发生"
        p2.destroy()
    finally:
        up.check = orig_check
    return "FAILED 消费提醒 + 橙点 force 路由"


def u24_tick_triggers_and_dot(app, root) -> str:
    """M16：三触发点之 tick 接线——startup 一次性/daily 由日期戳消；发现新版亮橙点、
    无新版灭点、点击路由开设置；enabled 关与 update 节缺失双静默。"""
    orig_check = up.check
    keep_cfg, keep = dict(app.cfg), (app._upd_startup_done, app._upd_new, app._upd_busy)
    calls: list = []
    up.check = lambda cfg, force=False, **kw: (calls.append(force), up.CheckResult(
        ok=True, info=up.UpdateInfo(version="9.9.9", url="u")))[1]
    try:
        today = time.strftime("%Y-%m-%d")
        app.cfg = cfg_with(last_check=0, last_auto_date=today)  # daily 今日已占 → 测 startup
        app._upd_startup_done, app._upd_busy, app._upd_new = False, False, None
        app._upd_tick()
        assert app._upd_startup_done is True, "startup 触发即消费（每进程一次）"
        app._upd_tick()
        assert len(calls) == 1, "startup 已毕 + daily 日期戳占 → 二次 tick 零动作"
        assert pump_until(root, lambda: app._upd_new is not None), "回投后亮点"
        assert calls[0] is False, "定时触发用 force=False"
        assert app.canvas.find_withtag("updot"), "橙点画布项存在"
        saved = json.loads((tmp_root / "config.json").read_text(encoding="utf-8"))
        assert saved["update"]["last_check"] > 0, "stamp 落盘"
        tip = next(z[4]["tip"] for z in app.hits
                   if isinstance(z[4], dict) and "新版本" in z[4].get("tip", ""))
        assert "v9.9.9" in tip, tip
        cb = next(z[4] for z in app.clicks
                  if getattr(z[4], "__name__", "") == "_upd_open")
        cb()                                        # 点击橙点 → 设置页（force 消费在 u23 已验）
        assert pump_until(root, lambda: len(calls) >= 2), "force 检查发出"
        # M19 b 路径：橙点 force 发现新版 → 同样自动弹 UpdateDialog
        st = app._settings
        assert st is not None and pump_until(
            root, lambda: st._up_dialog is not None and st._up_dialog.alive(),
            timeout=6.0), "b：橙点 force 路径自动弹窗"
        assert texts_of(st._up_dialog, []) and st._up_dialog.btn_go.winfo_manager() != ""
        if app._settings is not None and app._settings.alive():
            app._settings.destroy()                 # 级联关弹窗（M19）
        # 已是最新 → 灭点（橙点此前亮着：9.9.9 发现态）
        assert app._upd_new is not None and app.canvas.find_withtag("updot"), "前置：点仍亮"
        up.check = lambda cfg, force=False, **kw: up.CheckResult(
            ok=True, info=up.UpdateInfo(version=APP_VERSION, url="u"))
        app.cfg = cfg_with(last_check=0, last_auto_date="")
        app._upd_startup_done, app._upd_busy = False, False
        app._upd_tick()
        assert pump_until(root, lambda: app._upd_new is None
                          and not app.canvas.find_withtag("updot")), "等版本 → 点灭"
        # enabled 关 → 零动作
        calls2: list = []
        up.check = lambda cfg, force=False, **kw: (calls2.append(1),
                                                   up.CheckResult(skipped=True))[1]
        app.cfg = cfg_with(enabled=False)
        app._upd_startup_done, app._upd_busy = False, False
        app._upd_tick()
        assert not calls2 and app._upd_busy is False, "自动更新关 → 触发点零动作"
        # cfg 无 update 节（旧手写配置）→ 整体静默
        app.cfg = {k: v for k, v in cfg_with().items() if k != "update"}
        app._upd_startup_done, app._upd_busy = False, False
        app._upd_tick()
        assert not calls2 and app._upd_busy is False, "无 update 节配置 → tick 触发点静默"
    finally:
        up.check = orig_check
        app.cfg = keep_cfg
        app._upd_startup_done, app._upd_new, app._upd_busy = keep
        if app._settings is not None and app._settings.alive():
            app._settings.destroy()
        app._render()
    return "startup 一次性/亮灭点/点击路由/开关与缺节双静默"


def u27_repo_url() -> str:
    """M17：项目页 URL 由 slug 派生（非法拒绝、零网络）。"""
    assert up.repo_url("o/r") == "https://github.com/o/r"
    assert up.repo_url("https://github.com/o/r.git") == "https://github.com/o/r"
    assert up.repo_url("") == "" and up.repo_url(None) == "" and up.repo_url("bad") == ""
    return "repo_url slug 派生+非法拒绝"


def u25_skipped_text_lock(app, root) -> str:
    """M17 文案锁：频控命中状态行=「上次检查：HH:MM」；禁词（频控/6 小时/随时/手动）
    不得回流；纯函数面覆盖无记录"--"与跨日形态。"""
    import webbrowser as _wb
    open_orig = _wb.open
    _wb.open = lambda u: (_net.append("browser!" + u), False)[1]   # 本案绝不该拉浏览器
    now = time.time()
    clear_cfg(repo="fake-owner/fake-repo", enabled=True, last_check=int(now - 600))
    calls: list = []

    def bump(url, headers, opener=None):
        calls.append(url)
        raise AssertionError("频控命中不应触网")
    orig_req = up._req
    up._req = bump
    try:
        panel = settings_panel.SettingsPanel(app)
        panel.withdraw()
        panel._up_refresh(False)                     # 定时路径→真 check() 在触网前判 skipped
        assert pump_until(root, lambda: panel.lbl_up.cget("text").startswith("上次检查：")), \
            panel.lbl_up.cget("text")
        t = panel.lbl_up.cget("text")
        assert t == "上次检查：" + time.strftime("%H:%M", time.localtime(now - 600)), t
        for taboo in ("频控", "6 小时", "随时", "手动"):
            assert taboo not in t, f"禁词回流：{taboo} in {t}"
        assert not calls, "skipped 判定发生在网络请求之前"
        panel.destroy()
    finally:
        up._req = orig_req
        _wb.open = open_orig
    lc = settings_panel._up_last_check_text
    assert lc({"last_check": 0}) == "上次检查：--"
    assert lc({"last_check": "bad"}) == "上次检查：--"
    y = now - 2 * 86400
    assert lc({"last_check": y}) == "上次检查：" + time.strftime("%m-%d %H:%M", time.localtime(y))
    return "skipped=上次检查时刻/四禁词/--与跨日形态"


def u26_gh_foot_icon(app, root) -> str:
    """M18（u26 改造非删案例）：foot GitHub 图标渲染/隐藏零占位/点击 URL 打桩/失败橙字。

    M17 星形按钮按用户改向删除：断言「☆ 给本项目加星」文本与 btn_star 控件不得回流；
    图标挂在 foot 行 lbl_ver 左侧（side=right 后 pack 者居左），有 slug=显示、
    空 slug=pack_forget 零占位；点击 webbrowser.open 打桩断 URL；失败/异常橙字。"""
    import webbrowser as _wb
    orig_open = _wb.open
    urls: list = []
    _wb.open = lambda u: (urls.append(u), True)[1]
    try:
        clear_cfg(repo="fake-owner/fake-repo", enabled=False)
        panel = settings_panel.SettingsPanel(app)
        panel.withdraw()
        texts = texts_of(panel, [])
        # 旧星形入口不得回流（改向案例的"删净"半边）
        assert all("加星" not in t for t in texts), "M17 星按钮文案不得回流"
        assert all("给本项目" not in t for t in texts)
        assert not hasattr(panel, "btn_star"), "btn_star 控件必须已删除"
        # 图标渲染态：已 pack、image 非空、尺寸≥12 物理px（foot 行高派生，DPI 自适应）
        assert panel.lbl_gh.winfo_manager() == "pack", "slug 有 → 图标 pack 在位"
        assert panel.lbl_gh.pack_info()["side"] == "right"
        assert str(panel.lbl_gh.cget("image")) != "", "PhotoImage 已挂上"
        assert panel._gh_px >= 12 and panel.lbl_gh.cget("cursor") == "hand2"
        assert panel.lbl_gh.bind("<Button-1>"), "点击绑定已挂"
        # 位置：lbl_gh 在 lbl_ver 左侧（foot 行 right-pack 序 → icon 先落位）
        panel.update_idletasks()
        assert panel.lbl_ver.winfo_manager() == "pack"
        # 点击：URL 派生自配置 slug（零写死）
        panel._up_open_repo()
        assert urls == ["https://github.com/fake-owner/fake-repo"], urls
        assert "未能拉起" not in panel.lbl_up.cget("text")            # 成功静默
        _wb.open = lambda u: False
        panel._up_open_repo()
        assert "未能拉起浏览器" in panel.lbl_up.cget("text")          # 失败→橙字兜底同 M17
        assert panel.lbl_up.cget("fg").lower() == ORANGE.lower()
        def boom(u):
            raise RuntimeError("no default browser")
        _wb.open = boom
        panel._up_open_repo()
        assert "未能拉起浏览器" in panel.lbl_up.cget("text")          # 异常同样兜底
        # hover 两档：Enter→SOFT 图、Leave→FAINT 图（image 对象切换）
        im0 = panel.lbl_gh.cget("image")
        panel._gh_enter()
        assert panel.lbl_gh.cget("image") != im0, "hover 换 SOFT 档"
        assert panel._gh_tipw is not None and "打开 GitHub 仓库页" in \
            panel._gh_tipw.winfo_children()[0].cget("text"), "tooltip 文案"
        panel._gh_leave()
        assert panel.lbl_gh.cget("image") == im0, "离 hover 回 FAINT 档"
        panel.destroy()
        # 空 slug → 隐藏零占位（foot 布局回原样）+ 点击零唤起
        urls.clear()
        clear_cfg(repo="", enabled=False)
        p2 = settings_panel.SettingsPanel(app)
        p2.withdraw()
        assert p2.lbl_gh.winfo_manager() == "", "空 slug → pack_forget 零占位"
        assert p2.lbl_ver.winfo_manager() == "pack", "版本签名仍在（foot 回原样）"
        p2._up_open_repo()
        assert urls == [], "空 slug 绝不唤起浏览器"
        p2.destroy()
    finally:
        _wb.open = orig_open
    return "foot 图标：渲染/hover 换档/tooltip/URL 断言/失败橙字/空 slug 零占位/星钮不回流"


def u30_dialog_update_chain(app, root) -> str:
    """M19：弹窗「立即更新」执行链（download_and_stage/apply 全桩，零真网络零替换）——
    点击直接进下载（无内联再确认）→ 通道审计+校验态 → 失败橙字+重试/关闭 →
    staged 免重下 → NEED_ELEVATION 提权档（elevated=True 透传）→ 下载失败态 →
    关窗后残余事件安全（回调判存活）。"""
    clear_cfg(repo="fake-owner/fake-repo", enabled=False)
    info = up.UpdateInfo(version="9.9.9", url="https://dl.example/t.exe", notes="n",
                         digest="sha256:" + "ab" * 32, size=1500000,
                         published="2026-09-18T01:02:00Z")
    orig_dl, orig_ap = up.download_and_stage, up.apply_update_and_restart
    staged = config_mod.LOCAL_DIR / "update" / up.NEW_EXE_NAME
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"MZ-stub")
    seen: dict = {}

    def fake_dl(url, cfg=None, digest=None, progress_cb=None, **kw):
        seen["url"], seen["digest"] = url, digest
        if progress_cb is not None:
            progress_cb(300 * 1024, 1500000)              # <512KB：updater 内部已节流
            progress_cb(600 * 1024, 1500000)
        return up.DownloadResult(path=staged, channel="mirror", note="测试审计")

    up.download_and_stage = fake_dl
    up.apply_update_and_restart = lambda path, elevated=False, **kw: "stub：未真替换"
    try:
        panel = settings_panel.SettingsPanel(app)
        panel.withdraw()
        panel._up_info = info
        panel._up_open_dialog()
        dlg = panel._up_dialog
        dlg.btn_go.invoke()                                # 立即更新=直接下载（弹窗即确认）
        assert dlg.btn_go.winfo_manager() == "", "进度中按钮组隐去（无内联再确认环节）"
        # 状态迁移（同 tick 连排瞬态经 hist 留痕可断）：下载中→节流 %→审计校验→apply 败
        assert pump_until(root, lambda: "更新未完成" in dlg.lbl_prog.cget("text"),
                          timeout=4.0), dlg.lbl_prog.cget("text")
        assert any(h.startswith("正在下载更新包…") for h in dlg.hist)
        assert any("41.0%（已收 0.6 MB）" in h for h in dlg.hist), dlg.hist
        assert any("经镜像源" in h and "校验" in h and "测试审计" in h for h in dlg.hist), \
            "通道审计+note 上屏（瞬态）"
        assert seen["url"] == info.url and seen["digest"] == info.digest, "cfg/digest 透传"
        # 失败态（apply 桩给原因）：橙字 + 「重试」「关闭」恢复
        t = dlg.lbl_prog.cget("text")
        assert "stub：未真替换" in t
        assert dlg.lbl_prog.cget("fg").lower() == ORANGE.lower()
        assert dlg.btn_retry.winfo_manager() != "" and dlg.btn_close2.winfo_manager() != ""
        # 重试：staged 已缓存 → 不再下载，直接 apply
        ndl: list = []
        up.download_and_stage = lambda *a, **k: ndl.append(1) or up.DownloadResult(err="x")
        up.apply_update_and_restart = (
            lambda path, elevated=False, **kw: up.NEED_ELEVATION + "无写入权限")
        dlg.btn_retry.invoke()
        assert pump_until(root, lambda: "提权更新" in dlg.lbl_prog.cget("text"),
                          timeout=4.0), dlg.lbl_prog.cget("text")
        assert ndl == [], "staged 免重下"
        assert dlg.btn_elev.winfo_manager() != "" and dlg.btn_no.winfo_manager() != ""
        # 提权档：apply(elevated=True) 透传；失败→回失败档
        seen2: dict = {}
        def ap2(path, elevated=False, **kw):
            seen2["elev"] = elevated
            return "stub：提权未成就"
        up.apply_update_and_restart = ap2
        dlg.btn_elev.invoke()
        assert pump_until(root, lambda: "提权未成就" in dlg.lbl_prog.cget("text"),
                          timeout=4.0)
        assert seen2.get("elev") is True, "elevated=True 透传"
        # 取消=✕ 语义：立即更新按下前的取消键关窗（下载失败态的「关闭」同上）
        dlg.btn_close2.invoke()
        assert pump_until(root, lambda: not dlg.alive()), "关闭即散"
        # 下载失败态：err 上屏（橙字+重试档）
        up.download_and_stage = lambda *a, **k: up.DownloadResult(
            err="网络错误：全部失败（测试脱敏）")
        panel._up_open_dialog()
        d2 = panel._up_dialog
        d2.btn_go.invoke()
        assert pump_until(root, lambda: "更新未完成" in d2.lbl_prog.cget("text")
                          and "测试脱敏" in d2.lbl_prog.cget("text"), timeout=4.0)
        # 关窗时 worker 仍在跑：残余事件打到已销毁窗不崩（_poll alive 守卫）
        evq: list = []
        def slow_dl(url, cfg=None, digest=None, progress_cb=None, **kw):
            if progress_cb is not None:
                progress_cb(600 * 1024, 1500000)          # 关窗后才被消费的事件
            return up.DownloadResult(path=staged, channel="direct", note="")
        up.download_and_stage = slow_dl
        up.apply_update_and_restart = lambda path, elevated=False, **kw: evq.append(1) or "x"
        panel._up_open_dialog()
        d3 = panel._up_dialog
        d3.btn_go.invoke()
        d3.destroy()                                      # 立刻关窗
        pump(root, 400)                                   # 残余事件冲刷：不抛=过
        panel.destroy()
    finally:
        up.download_and_stage, up.apply_update_and_restart = orig_dl, orig_ap
    return "立即更新直下/审计校验/失败重试/免重下/提权透传/下载败态/关窗残余安全"


def u28_mirror_normalize_chain() -> str:
    """M18：mirror normalize 两形态统一 + 回退链顺序 direct→proxy→mirror 与 digest 校验路径。"""
    nm = up.normalize_mirror
    # 形态①纯前缀：补 https://、去尾 /、统一带尾 / 拼接式
    assert nm("ghfast.top") == "https://ghfast.top/"
    assert nm("https://ghfast.top") == "https://ghfast.top/"
    assert nm("https://ghfast.top/") == "https://ghfast.top/"
    assert nm("http://127.0.0.1:8080/mirror") == "http://127.0.0.1:8080/"   # 路径丢弃
    # 形态②占位式：/https://… 段视为被加速 URL → 统一存带尾 / 前缀拼接式
    assert nm("https://ghfast.top/https://github.com/o/r/releases/download/a.exe") \
        == "https://ghfast.top/"
    assert nm("  ") == "" and nm("") == "" and nm(None) == ""               # 空=不使用
    for bad in ("socks://ghfast.top", "https://user:pw@ghfast.top/",
                "not a url!", "https://bad..port:99999/"):
        assert nm(bad) == "", bad
    # 拼接语义：两形态 normalize 后拼原 URL 一致（占位式的自然形态）
    u = "https://github.com/o/r/releases/download/v1/TokenWidget.exe"
    assert up.mirror_join(nm("https://ghfast.top/"), u) == "https://ghfast.top/" + u
    assert up.mirror_join("", u) == u
    # ---- 回退链：直连炸 → 代理腿炸 → 镜像腿成（digest 必校验）----
    d = config_mod.LOCAL_DIR / "update"
    for f in (d / up.NEW_EXE_NAME, d / (up.NEW_EXE_NAME + ".part")):
        if f.exists():
            f.unlink()
    body = b"M" * 1234
    dig = "sha256:" + hashlib.sha256(body).hexdigest()
    cfg = cfg_with(mirror="https://ghfast.top/")
    cfg["network"] = {**CFG["network"], "proxy_enabled": True, "proxy_url": PX}
    ctx = FakeCtx([urllib.error.URLError("direct down"),
                   urllib.error.URLError("proxy down"),
                   FakeResp([body], cl=len(body))])
    r = up.download_and_stage(u, cfg=cfg, digest=dig, dest_dir=d, req_open=ctx.open)
    assert r.err == "" and r.channel == "mirror", (r.err, r.channel)
    assert [c[0] for c in ctx.calls] == [u, u, "https://ghfast.top/" + u], \
        "调用序列：直连→代理（同 URL 换 opener）→镜像（拼接 URL）"
    assert ctx.calls[0][1] is None, "第一趟直连（无 opener）"
    assert isinstance(ctx.calls[1][1], urllib.request.OpenerDirector), "第二趟经 build_opener"
    assert ctx.calls[2][1] is None, "镜像腿走直连（国内镜像不需代理）"
    assert r.path.read_bytes() == body
    # 代理未开+镜像已配：两腿 direct→mirror（proxy 腿缺席）
    ctx2 = FakeCtx([urllib.error.URLError("d"), FakeResp([body], cl=len(body))])
    r2 = up.download_and_stage(u, cfg=cfg_with(mirror="ghfast.top"), digest=dig,
                               dest_dir=d, req_open=ctx2.open)
    assert r2.channel == "mirror" and len(ctx2.calls) == 2, (r2.err, ctx2.calls)
    # 三链全败：报错含链描述且脱敏（代理 URL 认证段不打漏）
    ctx3 = FakeCtx([urllib.error.URLError("a"), urllib.error.URLError("b"),
                    urllib.error.URLError("c")])
    cfg3 = cfg_with(mirror="https://ghfast.top/")
    cfg3["network"] = {**CFG["network"], "proxy_enabled": True,
                       "proxy_url": "http://user:pass@127.0.0.1:7890"}
    r3 = up.download_and_stage(u, cfg=cfg3, digest=dig, dest_dir=d, req_open=ctx3.open)
    assert r3.path is None and "direct→proxy→mirror 全部失败" in r3.err, r3.err
    assert "user:pass" not in r3.err, "错误脱敏"
    # check 不走镜像：API URL 恒官方（Req 桩断言零 mirror 拼接）
    rec = RecReq([(200, {}, rel_body("v9.9.9"))])
    up.check(cfg_with(mirror="https://ghfast.top/"), req=rec, now=_now)
    assert rec.calls[0][0] == up.GITHUB_API.format(slug="fake-owner/fake-repo"), \
        "元数据永远取自官方 API（镜像只救二进制）"
    return "normalize 两形态/拒绝态 + 链序 direct→proxy→mirror + 镜像腿 digest 校验"


def u29_digest_guard() -> str:
    """M18：digest 不符拒收+清理；镜像缺 digest 拒收；直连/代理缺 digest 放行带 note。"""
    d = config_mod.LOCAL_DIR / "update"
    u = "https://github.com/o/r/releases/download/v1/TokenWidget.exe"
    body = b"T" * 500
    good = "sha256:" + hashlib.sha256(body).hexdigest()

    def wipe():
        for f in (d / up.NEW_EXE_NAME, d / (up.NEW_EXE_NAME + ".part")):
            if f.exists():
                f.unlink()

    # ① digest 不符 → 删文件报错（单腿失败无链后缀）
    wipe()
    ctx = FakeCtx(FakeResp([body], cl=len(body)))
    r = up.download_and_stage(u, digest="sha256:" + "0" * 64, dest_dir=d,
                              req_open=ctx.open)
    assert r.path is None and "SHA-256 完整性校验不符" in r.err, r.err
    assert not (d / (up.NEW_EXE_NAME + ".part")).exists() and not (d / up.NEW_EXE_NAME).exists(), \
        "校验败 .part 与成品双清"
    # ①b 镜像腿 digest 不符 → 换腿语义：三腿皆败（不符错误透传+链描述）
    wipe()
    ctx2 = FakeCtx([FakeResp([b"F" * 100], cl=100)] * 1 +
                   [FakeResp([b"F" * 100], cl=100)] +
                   [FakeResp([b"F" * 100], cl=100)])
    r2 = up.download_and_stage(u, cfg=cfg_with(mirror="https://ghfast.top/"),
                               digest=good, dest_dir=d, req_open=ctx2.open)
    assert r2.path is None and "SHA-256" in r2.err and "全部失败" in r2.err, r2.err
    assert not (d / (up.NEW_EXE_NAME + ".part")).exists()
    # ② 镜像腿缺 digest → 拒收（即便字节流完好）
    wipe()
    cfgm = cfg_with(mirror="https://ghfast.top/")
    ctx3 = FakeCtx([urllib.error.URLError("direct down"),
                    FakeResp([body], cl=len(body))])       # 只到 mirror 腿（代理未开）
    r3 = up.download_and_stage(u, cfg=cfgm, digest=None, dest_dir=d, req_open=ctx3.open)
    assert r3.path is None and "镜像" in r3.err and "SHA-256" in r3.err, r3.err
    assert not (d / (up.NEW_EXE_NAME + ".part")).exists(), "拒收后零残留"
    # ③ 直连缺 digest → 放行 + note 说明（信任锚缺失如实标注，不静默）
    wipe()
    ctx4 = FakeCtx(FakeResp([body], cl=len(body)))
    r4 = up.download_and_stage(u, digest=None, dest_dir=d, req_open=ctx4.open)
    assert r4.path is not None and r4.channel == "direct" and "digest" in r4.note
    # ④ 直连坏 digest 入参（畸形）→ 按缺省路径处理（不炸）
    wipe()
    ctx5 = FakeCtx(FakeResp([body], cl=len(body)))
    r5 = up.download_and_stage(u, digest="sha256:zzz", dest_dir=d, req_open=ctx5.open)
    assert r5.path is not None and "digest" in r5.note
    # ⑤ M19 进度节流：600KB 体、64KB chunk → 仅跨过 512KB 时回调一次（末段不再刷）
    wipe()
    calls: list = []
    big = b"Q" * (600 * 1024)
    chunks = [big[i:i + 65536] for i in range(0, len(big), 65536)]
    ctx6 = FakeCtx(FakeResp(chunks, cl=len(big)))
    r6 = up.download_and_stage(u, dest_dir=d, req_open=ctx6.open,
                               progress_cb=lambda done, total: calls.append(done))
    assert r6.path is not None and calls == [524288], calls
    # ⑥ 回调抛异常不断下载（展示层故障隔离）
    wipe()

    def badcb(_d, _t):
        raise RuntimeError("ui boom")
    ctx7 = FakeCtx(FakeResp(list(chunks), cl=len(big)))
    r7 = up.download_and_stage(u, dest_dir=d, req_open=ctx7.open, progress_cb=badcb)
    assert r7.path is not None and r7.err == "", r7.err
    return "不符拒收双清/换腿/镜像缺哈希拒收/直连缺哈希 note/畸形入参/512KB 节流/坏 cb 不断流"


def u31_dialog_helpers() -> str:
    """M19 纯函数：发布时间/包大小换算 + 发行说明 ≤6 行截断（弹窗信息区数据面）。"""
    sp = settings_panel
    assert sp._up_pub_text("2026-09-18T01:02:00Z") == "2026-09-18 01:02 (UTC)"
    assert sp._up_pub_text("") == "—" and sp._up_pub_text(None) == "—"
    assert sp._up_pub_text("garbage") == "garbage"          # 非 ISO 原样截 16
    assert sp._up_size_text(11263948) == "10.7 MB"
    assert sp._up_size_text(1048576) == "1.0 MB"
    assert sp._up_size_text(0) == "—" and sp._up_size_text("x") == "—" and sp._up_size_text(-5) == "—"
    # notes：硬换行 10 行 → 前 6 行 + 尾 …
    notes = "标题行\n" + ("行内容一二三\n" * 10)
    clip = sp._up_notes_clip(notes)
    lines = clip.splitlines()
    assert len(lines) == 6 and lines[-1].endswith("…"), clip
    assert sp._up_notes_clip("") == "（无发行说明）"
    assert sp._up_notes_clip("short one") == "short one"
    # 单一超长段软换行（textwrap 52 列）→ 同样 ≤6 行 + …；wraplength=420 不溢出
    big = "中英 mixed 词 " * 200
    c2 = sp._up_notes_clip(big)
    assert len(c2.splitlines()) == 6 and c2.endswith("…"), c2
    return "published 容错/size MB 一位小数/notes 六行截断软换行/空说明占位"


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
    ("next_trigger_matrix", u16_next_trigger_matrix),
    ("stamp", u17_stamp),
    ("probe", u18_probe),
    ("elevation", u19_elevation),
    ("repo_url", u27_repo_url),
    ("mirror_chain", u28_mirror_normalize_chain),
    ("digest_guard", u29_digest_guard),
    ("dialog_helpers", u31_dialog_helpers),
]

CASES_TK = [
    ("panel_render_toggle", u20_panel_render_and_toggle),
    ("panel_manual_flow", u21_panel_manual_flow),
    ("panel_auto_readonly_err", u22_panel_auto_readonly_and_err),
    ("panel_failed_forceopen", u23_panel_failed_note_and_force_open),
    ("tick_triggers_dot", u24_tick_triggers_and_dot),
    ("skipped_text_lock", u25_skipped_text_lock),
    ("gh_foot_icon", u26_gh_foot_icon),
    ("dialog_update_chain", u30_dialog_update_chain),
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
    app._upd_startup_done = True       # M16：野跑防御——启动触发由 u24 显式复位后专测
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
