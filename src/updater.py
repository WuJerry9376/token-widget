"""M15 更新：GitHub Releases 检查 / 下载 / 替换重启（stdlib-only）。

设计（任务书定案）：
- 仓库 slug 走配置 config.update.repo（"owner/name"，可带 https://github.com/ 前缀），
  **代码零写死**；空 slug → 未配置态，零网络。
- DEFAULTS: "update": {"enabled": True, "repo": "", "last_check": 0}。
  enabled=自动检查开关（设置页「自动更新」勾选）；last_check 由调用方在每次
  检查完成（含 skipped 以外的网络尝试）后写回并保存。
- check()：GET https://api.github.com/repos/{slug}/releases/latest（UA 固定、
  Accept github+json、超时 20s）。频控：距 last_check <6h 的**定时**检查跳过
  （skipped=True；手动 force 无视）。代理：github api 国内一般可达 → 默认直连；
  proxy_targets 不含 "update"（netconfig 零改动），但直连失败且代理开启+URL 合法
  时回落经代理重试一次（fallback opener 现场 build，语义不变）。
- 安全纪律：**下载/替换仅在用户明确动作下发生**——定时路径只读发现新版；
  设置页手动「立即下载并更新」+ 二次确认后才 download+apply（防无感替换惊吓）。
- apply：一次性 restart_update.cmd（ping 等本进程退出 → 旧 exe 改名 .old →
  move new 就位 → start → 删 .old → 自删；改名失败按次重试）。全程只动
  local\\update\\ 与 exe 本体，**旧 .dpapi / auth.json 等凭据数据零触碰**。
- 任何失败路径：清理 .part、返回已脱敏原因、不 crash。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import config as _config
from . import netconfig

GITHUB_API = "https://api.github.com/repos/{slug}/releases/latest"
GITHUB_WEB = "https://github.com/"                    # M17：项目页前缀（webbrowser 用，零 API）
UA = "token-widget/updater"                         # GitHub API 无 UA 直接 403
TIMEOUT = 20
CHECK_INTERVAL_SECONDS = 6 * 3600                   # 定时检查频控窗口（6h）
ASSET_NAME = "TokenWidget.exe"                      # 主匹配资源名（大小写不敏感）

_UPDATE_REL = Path("update")
NEW_EXE_NAME = "TokenWidget.new.exe"
CMD_NAME = "restart_update.cmd"
FAILED_NAME = "FAILED.txt"                          # M16：cmd 失败兜底落档
DAILY_START_HOUR = 5                                # M16：每日 5 点后首帧触发窗
NEED_ELEVATION = "NEED_ELEVATION:"                  # 前缀标记（面板据此出「提权更新」钮）


@dataclass
class UpdateInfo:
    """releases/latest 解析结果（check 成功时携带）。"""
    version: str                    # 去 v 前缀的 tag
    url: str                        # 目标 exe 下载直链（可空串=无可用资源）
    notes: str = ""                 # release body（原文，展示端截断）


@dataclass
class CheckResult:
    """check() 统一返回：ok→有 info；skipped→6h 内定时检查被频控；否则 err 文案。"""
    ok: bool = False
    info: UpdateInfo | None = None
    err: str = ""
    skipped: bool = False


def update_dir() -> Path:
    """staging 目录：local\\update\\（frozen=exe 同级 local；dev=项目 local）。"""
    return _config.LOCAL_DIR / _UPDATE_REL


def parse_repo(repo) -> str:
    """"owner/name" / "https://github.com/owner/name(.git)" → "owner/name"；非法 → ""。"""
    if not isinstance(repo, str):
        return ""
    t = repo.strip().rstrip("/")
    if not t:
        return ""
    if "://" in t:
        t = t.split("://", 1)[1]
        t = t.partition("/")[2] if "/" in t else ""
    t = t.removesuffix(".git").strip("/")
    parts = [p for p in t.split("/") if p]
    if len(parts) < 2:
        return ""
    owner, name = parts[-2], parts[-1]
    if not re.fullmatch(r"[\w.\-]+", owner) or not re.fullmatch(r"[\w.\-]+", name):
        return ""
    return f"{owner}/{name}"


def repo_url(repo) -> str:
    """M17：由 slug（或原始 repo 串）派生项目页 URL；非法/空 → ""。零网络。"""
    slug = parse_repo(repo)
    return GITHUB_WEB + slug if slug else ""


def _ver_tuple(v) -> tuple[int, int, int]:
    """'1.6.10' / 'v1.6' / '1.6.6-build1' → 三段 int 元组（缺位补 0，尾缀截断）。"""
    if not isinstance(v, str):
        return (0, 0, 0)
    t = v.strip().lstrip("vV")
    out: list[int] = []
    for seg in t.split(".")[:3]:
        m = re.match(r"\d+", seg)
        out.append(int(m.group()) if m else 0)
    while len(out) < 3:
        out.append(0)
    return (out[0], out[1], out[2])


def is_newer(candidate, current) -> bool:
    """semver 三段**数字**比较（1.6.10 > 1.6.6；禁字符串比较）。等值/更旧 → False。"""
    return _ver_tuple(candidate) > _ver_tuple(current)


def parse_release(j) -> tuple[str, str, str]:
    """releases/latest JSON → (version, url, notes)。

    - tag_name 去 v 前缀；缺失/非 dict → version=""；
    - 资源：先按名匹配 TokenWidget.exe（大小写不敏感）；无则**唯一** .exe 兜底；
      多个 .exe 且无主名 → url=""（宁缺勿错下）。draft/prerelease 不在本函数判定范围
      （latest 端点已过滤）。
    """
    if not isinstance(j, dict):
        return "", "", ""
    tag = j.get("tag_name")
    version = ""
    if isinstance(tag, str) and tag.strip():
        version = tag.strip()
        if version[:1] in ("v", "V"):
            version = version[1:]
    assets = j.get("assets")
    assets = assets if isinstance(assets, list) else []
    named, exes = [], []
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        url = str(a.get("browser_download_url") or "")
        if not url:
            continue
        if name.lower() == ASSET_NAME.lower():
            named.append(url)
        if name.lower().endswith(".exe"):
            exes.append(url)
    url = named[0] if named else (exes[0] if len(exes) == 1 else "")
    notes = j.get("body")
    return version, url, notes if isinstance(notes, str) else ""


def _req(url: str, headers: dict, opener=None) -> tuple[int, dict, bytes]:
    """GET 传输层（测试 monkeypatch 注入点）。返回 (status, headers-dict, body)。"""
    r = urllib.request.Request(url, headers=headers, method="GET")
    target = opener if opener is not None else urllib.request.build_opener()
    try:
        with target.open(r, timeout=TIMEOUT) as resp:
            hd = {k.lower(): v for k, v in resp.headers.items()}
            return int(getattr(resp, "status", 200) or 200), hd, resp.read()
    except urllib.error.HTTPError as e:
        hd = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        return e.code, hd, (e.read() if e.fp else b"")


def _headers() -> dict:
    return {"User-Agent": UA, "Accept": "application/vnd.github+json"}


def check(cfg: dict, force: bool = False, now: float | None = None,
          req=None) -> CheckResult:
    """检查 releases/latest。req 参数供测试注入传输层（默认模块 _req）。

    频控：非 force 且距 last_check <6h → skipped（零网络）。
    代理回落：默认直连；失败且 network.proxy_enabled+URL 合法 → 经代理重试一次。
    """
    sec = _section(cfg)
    slug = parse_repo(sec.get("repo"))
    if not slug:
        return CheckResult(err="未配置仓库：请在 local\\config.json 的 update.repo 填入 owner/name")
    t = time.time() if now is None else float(now)
    if not force:
        try:
            last = float(sec.get("last_check") or 0)
        except (TypeError, ValueError):
            last = 0.0
        if t - last < CHECK_INTERVAL_SECONDS:
            return CheckResult(skipped=True)
    reqf = req if req is not None else _req
    url = GITHUB_API.format(slug=slug)
    attempts: list = [None]                            # ① 直连
    proxy = netconfig.normalize_proxy_url(
        (_config_net(cfg) or {}).get("proxy_url"))
    fallback_ok = bool(proxy) and bool((_config_net(cfg) or {}).get("proxy_enabled"))
    if fallback_ok:
        attempts.append(netconfig.build_opener(proxy))  # ② 仅直连失败后重试一次
    err = ""
    for i, opener in enumerate(attempts):
        try:
            st, _hd, body = reqf(url, _headers(), opener)
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = netconfig.sanitize_proxy_msg(
                f"网络错误：{str(getattr(e, 'reason', e))[:120]}")
            continue
        if st != 200:
            return CheckResult(err=f"GitHub API 返回 HTTP {st}（稍后再试）")
        try:
            j = json.loads(body)
        except ValueError:
            return CheckResult(err="GitHub API 响应非 JSON")
        ver, dl, notes = parse_release(j)
        if not ver:
            return CheckResult(err="响应缺少 tag_name（仓库无 release？）")
        return CheckResult(ok=True, info=UpdateInfo(version=ver, url=dl, notes=notes))
    return CheckResult(err=err + ("（直连与代理均失败）" if fallback_ok else "（直连失败）"))


def _section(cfg: dict) -> dict:
    d = dict(_config.DEFAULTS.get("update") or {})
    v = cfg.get("update") if isinstance(cfg, dict) else None
    if isinstance(v, dict):
        d.update(v)
    return d


def _config_net(cfg: dict) -> dict:
    v = cfg.get("network") if isinstance(cfg, dict) else None
    return v if isinstance(v, dict) else {}


def mark_checked(cfg: dict, now: float | None = None) -> None:
    """就地更新 cfg['update']['last_check']（调用方负责 save_cfg）。"""
    sec = _section(cfg)
    sec["last_check"] = int(time.time() if now is None else now)
    cfg["update"] = sec


# ---------------- M16：自动检查触发点判定（纯函数，ui 15s tick 复用） ----------------

def _local_dt(now: float | None):
    import datetime as _dt
    return _dt.datetime.fromtimestamp(time.time() if now is None else now)


def next_trigger(cfg: dict, startup_done: bool, now: float | None = None) -> str:
    """返回 "" | "startup" | "daily"（只判定不改 cfg；执行与落戳由调用方做）。

    - enabled 关 / slug 空 → 恒 ""（零动作）；
    - 启动首触发：进程内 startup_done=False 即 "startup"（挂现有 5s 首 tick=
      「首帧渲染后延迟数秒」；6h 频控在 check() 内消化，与开设置页同日自然合并）；
    - 每日 5 点后：本地钟点 ≥5 且 last_auto_date≠今日 → "daily"（睡眠错过由
      下一 tick 补跑；无论实际执行还是被频控 skipped，"daily" 发起一次即由
      stamp_auto_trigger 记日期戳防每 15s 重发）。
    """
    sec = _section(cfg)
    if not bool(sec.get("enabled", True)) or not parse_repo(sec.get("repo")):
        return ""
    if not startup_done:
        return "startup"
    dt = _local_dt(now)
    if dt.hour < DAILY_START_HOUR:
        return ""
    if str(sec.get("last_auto_date") or "") == dt.strftime("%Y-%m-%d"):
        return ""
    return "daily"


def stamp_auto_trigger(cfg: dict, trig: str, now: float | None = None,
                       attempted: bool = True) -> None:
    """发起一次自动检查后的落戳：attempted（实际打了网络，含 HTTP/解析错）刷 last_check；
    daily 无论实际执行还是被频控 skipped 均记日期戳（防 5 点后每 15s 反复起线程）。
    """
    t = time.time() if now is None else now
    if attempted:
        mark_checked(cfg, now=t)
    if trig == "daily":
        sec = _section(cfg)
        sec["last_auto_date"] = _local_dt(t).strftime("%Y-%m-%d")
        cfg["update"] = sec


def download_and_stage(url: str, dest_dir: Path | str | None = None,
                       opener=None, req_open=None, chunk: int = 65536
                       ) -> tuple[Path | None, str]:
    """流式下载到 <dest>/TokenWidget.new.exe（.part → 校验 → rename）。

    返回 (最终路径|None, 错误文案)。Content-Length 必存在且与实收一致才就位；
    任何失败清理 .part。只写 update 目录，不触碰既有凭据/配置。
    """
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        return None, "下载链接非法（仅支持 https）"
    base = Path(dest_dir) if dest_dir is not None else update_dir()
    try:
        base.mkdir(parents=True, exist_ok=True)
        part = base / (NEW_EXE_NAME + ".part")
        final = base / NEW_EXE_NAME
        if part.exists():
            part.unlink()
        r = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
        target = opener if opener is not None else urllib.request.build_opener()
        opened = req_open or target.open
        got = 0
        with opened(r, timeout=TIMEOUT) as resp:
            st = int(getattr(resp, "status", 200) or 200)
            if st != 200:
                return None, f"下载返回 HTTP {st}"
            cl = None
            getter = getattr(resp.headers, "get", None)
            if callable(getter):
                cl = getter("content-length")
            try:
                cl_n = int(cl)
            except (TypeError, ValueError):
                return None, "响应缺 Content-Length，无法校验完整性（已放弃）"
            with part.open("wb") as fh:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    fh.write(buf)
                    got += len(buf)
        if got != cl_n:
            part.unlink(missing_ok=True)
            return None, f"长度不符：声明 {cl_n} 实收 {got}（已放弃）"
        os.replace(part, final)
        return final, ""
    except (urllib.error.URLError, OSError) as e:
        try:
            (base / (NEW_EXE_NAME + ".part")).unlink(missing_ok=True)
        except OSError:
            pass
        return None, netconfig.sanitize_proxy_msg(
            f"下载失败：{str(getattr(e, 'reason', e))[:120]}")


def probe_replace_permission(exe_path: Path | str | None = None) -> bool:
    """exe 所在目录可替换预检：试建 .write_test.tmp → 立即删（同目录写权限探测）。

    永不抛：任何 OSError/PermissionError → False。只碰临时名，不触碰既有文件。
    """
    target = Path(exe_path) if exe_path is not None else Path(sys.executable)
    probe = target.parent / ".write_test.tmp"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        try:
            probe.unlink(missing_ok=True)             # 半截产物兜底清理
        except OSError:
            pass
        return False


def render_restart_cmd(new_exe: Path | str, old_exe: Path | str,
                       cmd_path: Path | str,
                       failed_path: Path | str | None = None) -> str:
    """一次性替换脚本（纯函数，测试对文本）。

    时序：ping 等本进程退出 → 旧 exe 改名 .old（占用则重试至多 10 次）→ move new
    就位（失败回滚改名）→ start 新 exe → 删 .old → 自删 cmd。**只涉两个 exe 路径
    与 cmd 本身**，local\\ 其余数据零触碰。
    M16：任一步失败先 echo 步进原因+errorlevel 到 failed_path（默认 cmd 同目录
    FAILED.txt），供程序下次启动在设置页橙字提示，杜绝静默失败。
    """
    new = str(Path(new_exe))
    old = str(Path(old_exe))
    cmd = str(Path(cmd_path))
    fail = str(Path(failed_path)) if failed_path is not None else \
        str(Path(cmd).parent / FAILED_NAME)
    return "\r\n".join([
        "@echo off",
        "ping -n 4 127.0.0.1 >nul",
        "set TRIES=0",
        ":retry",
        f'move /Y "{old}" "{old}.old" >nul 2>&1',
        "if not errorlevel 1 goto moved",
        "set /a TRIES+=1",
        "if %TRIES% LSS 10 (ping -n 2 127.0.0.1 >nul & goto retry)",
        f'echo rename_old_failed rc=%errorlevel% tries=%TRIES%> "{fail}"',
        "goto cleanup",
        ":moved",
        f'move /Y "{new}" "{old}" >nul 2>&1',
        "if not errorlevel 1 goto launch",
        f'echo move_new_failed rc=%errorlevel%> "{fail}"',
        f'move /Y "{old}.old" "{old}" >nul 2>&1',
        "goto cleanup",
        ":launch",
        f'start "" "{old}"',
        f"del /Q \"{old}.old\" 2>nul",
        ":cleanup",
        'del /Q "%~f0" 2>nul',
        "",
    ])


def _writable_dir(base: Path) -> bool:
    try:
        base.mkdir(parents=True, exist_ok=True)
        t = base / ".write_test.tmp"
        t.write_bytes(b"")
        t.unlink()
        return True
    except OSError:
        return False


def apply_update_and_restart(new_exe: Path | str | None = None,
                             current_exe: Path | str | None = None,
                             spawn=None, exit_fn=None, elevated: bool = False,
                             probe=None) -> str:
    """写 restart_update.cmd → 分离进程执行 → 本进程退出。返回 ""=已接管，否则原因。

    - current_exe：默认 sys.executable（frozen=TokenWidget.exe 本体）；测试注入。
    - new_exe：默认 staging 的 TokenWidget.new.exe；调用前须已 download_and_stage。
    - probe：目录可写预检替身（测试注入；None=真 probe_replace_permission）。
    - M16 权限加固：预检失败且未提权 → 返回 NEED_ELEVATION 前缀原因（不退出、
      不 spawn）；面板据此出「提权更新」钮，提权重试 elevated=True 经
      PowerShell Start-Process -Verb RunAs（一次 UAC；cmd 逻辑不变仅借提权执行）。
      连 staging/cmd 目录都不可写 → 直接给移动位置指引。
    - spawnv/exit_fn：测试注入替身（默认 os.spawnv P_DETACH + os._exit(0)）。
    """
    cur = Path(current_exe) if current_exe is not None else Path(sys.executable)
    new = Path(new_exe) if new_exe is not None else update_dir() / NEW_EXE_NAME
    if not new.is_file():
        return "尚未下载更新包（先「立即下载并更新」）"
    if cur.name.lower() == new.name.lower():
        return "当前运行体不是 TokenWidget.exe（dev 模式不支持自更新）"
    check = probe_replace_permission if probe is None else probe
    if not check(cur):                               # 预检失败 → 不退出，交回面板决策
        if not elevated:
            return NEED_ELEVATION + "当前目录无写入权限，可选提权更新或移动位置"
        # 提权路径：cmd 必须落在可写处（exe 目录不可写时退 %TEMP%）
        base = update_dir()
        if not _writable_dir(base):
            base = Path(os.environ.get("TEMP", str(Path.home()))) / "token-widget-update"
            if not _writable_dir(base):
                return "当前目录无写入权限：请先把程序移到可写目录（如用户目录）再更新"
    else:
        base = update_dir()
        base.mkdir(parents=True, exist_ok=True)
    cmd_path = base / CMD_NAME
    fail_path = base / FAILED_NAME
    try:
        cmd_path.write_text(render_restart_cmd(new, cur, cmd_path, fail_path),
                            encoding="gbk", errors="replace")
    except OSError as e:
        return f"无法写入重启脚本：{str(e)[:80]}"
    spawnv = spawn if spawn is not None else os.spawnv
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    try:
        if elevated:
            ps = os.environ.get("SystemRoot", r"C:\Windows") + \
                r"\System32\WindowsPowerShell\v1.0\powershell.exe"
            # 一次 UAC：Start-Process -Verb RunAs 包 cmd；PowerShell 自身不需要管理员
            spawnv(os.P_DETACH, ps, [
                ps, "-NoProfile", "-Command",
                f"Start-Process -FilePath cmd.exe -ArgumentList '/c','{cmd_path}' "
                "-Verb RunAs -WindowStyle Hidden"])
        else:
            spawnv(os.P_DETACH, comspec, [comspec, "/c", str(cmd_path)])
    except OSError as e:
        try:
            cmd_path.unlink(missing_ok=True)
        except OSError:
            pass
        return f"无法启动更新脚本：{str(e)[:80]}"
    (exit_fn or os._exit)(0)
    return ""
