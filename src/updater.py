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
- apply（M28 去 cmd 化）：写 pending_swap marker → Popen **staged 新 exe 本体**
  （DETACHED|NEW_PROCESS_GROUP，零 shell/零可见窗口，带 --post-update-swap
  --start-marker）→ 本进程退出；新实例启动早期完成改名序列（旧 exe→.old、
  自身 .new→正名——Windows 允许改运行中映像文件名）。旧 cmd 脚本链因分离态父链
  触发 Windows「Security validation failure」弹窗且掐死 start，已整体退役。
  全程只动 local\\update\\ 与 exe 本体，**旧 .dpapi / auth.json 等凭据数据零触碰**。
- 任何失败路径：清理 .part、返回已脱敏原因、不 crash。

M18（镜像备用源 + SHA-256 信任锚，镜像源裁决落地）：
- config.update.mirror：下载备用源前缀（""=不使用）。回退链 download_and_stage：
  ①直连 → ②代理开启则经 build_opener → ③镜像配置则拼「前缀+原URL」重试；
  成功返回值携带 used_channel（channel 字段），三链全败才报失败（错误脱敏）。
- 信任锚=sha256：parse_release 增读 asset.digest（GitHub API "sha256:<hex>"，
  2025+ 提供；缺失/畸形 → None）；download_and_stage 流式 hashlib 校验——
  digest 有值必校验（不符删文件报错）；digest 缺失：镜像通道**拒收**（第三方可
  篡改字节且无哈希可验），直连/代理放行并在返回 note 说明。
- **API 元数据（check）永不走镜像**：api.github.com 直连/代理，失败如实报错——
  镜像只救二进制，不救信任链。
- normalize_mirror：宽进（无 scheme 补 https://、占位式「前缀/https://…」与纯
  前缀两形态统一存 "scheme://host[:port]/" 拼接式）；非法/空 → ""（不使用）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
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
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")         # M18 digest 归一判据
PROGRESS_STEP_BYTES = 512 * 1024                    # M19 下载进度节流步长（512KB）

_UPDATE_REL = Path("update")
NEW_EXE_NAME = "TokenWidget.new.exe"
FAILED_NAME = "FAILED.txt"                          # M16：swap 失败兜底落档（消费链不变）
DAILY_START_HOUR = 5                                # M16：每日 5 点后首帧触发窗
NEED_ELEVATION = "NEED_ELEVATION:"                  # 前缀标记（面板据此出「提权更新」钮）
# M28：去 cmd 化重启链——marker 驱动的「新实例自我替换」
MARKER_NAME = "pending_swap.json"                   # 换装请求（old/new/ts，JSON）
MARKER_TTL_SECONDS = 600                            # >10min 未消费=陈旧（例外：自 rescuing 见 run_pending_swap）
SWAP_FLAG = "--post-update-swap"
SWAP_MARKER_FLAG = "--start-marker"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
SWAP_DETACH_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


@dataclass
class UpdateInfo:
    """releases/latest 解析结果（check 成功时携带）。"""
    version: str                    # 去 v 前缀的 tag
    url: str                        # 目标 exe 下载直链（可空串=无可用资源）
    notes: str = ""                 # release body（原文全文，展示端截断）
    digest: str | None = None       # M18：asset.digest "sha256:<hex64>"；无/畸形=None
    size: int = 0                   # M19：asset.size 字节（0=未知，弹窗展示 MB）
    published: str = ""             # M19：release published_at 原文（ISO8601，""=无）


@dataclass
class CheckResult:
    """check() 统一返回：ok→有 info；skipped→6h 内定时检查被频控；否则 err 文案。"""
    ok: bool = False
    info: UpdateInfo | None = None
    err: str = ""
    skipped: bool = False


@dataclass
class DownloadResult:
    """M18 download_and_stage 统一返回。

    - path：就位后的 new exe（失败=None）；err：脱敏失败文案（成功=""）；
    - channel：成功所用通道 "direct"|"proxy"|"mirror"（失败时=已尝试链描述）；
    - note：审计说明（如「官方 API 未提供 SHA-256 digest，未校验放行」），永不抛。
    """
    path: Path | None = None
    err: str = ""
    channel: str = ""
    note: str = ""


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


def _asset_digest(a: dict) -> str | None:
    """M18：asset.digest → 归一 "sha256:<hex64>"；缺失/畸形/非 sha 前缀裸非 64hex → None。

    GitHub Releases API 2025+ 在 asset 上提供 digest（形如 "sha256:abcd…"）；
    兼容裸 64-hex 形态。宁缺勿错：解析不出一把可信哈希就按 None 处理。"""
    d = a.get("digest")
    if not isinstance(d, str):
        return None
    t = d.strip().lower()
    if t.startswith("sha256:"):
        t = t.split(":", 1)[1].strip()
    return f"sha256:{t}" if _SHA256_HEX.fullmatch(t) else None


def parse_release(j) -> tuple[str, str, str, str | None, int, str]:
    """releases/latest JSON → (version, url, notes, digest, size, published)。

    - tag_name 去 v 前缀；缺失/非 dict → version=""；
    - 资源：先按名匹配 TokenWidget.exe（大小写不敏感）；无则**唯一** .exe 兜底；
      多个 .exe 且无主名 → url=""（宁缺勿错下）。draft/prerelease 不在本函数判定范围
      （latest 端点已过滤）。
    - M18：digest 取自**选中的那个 asset** 的 digest 字段（None=API 未提供）。
    - M19：size=选中 asset 的 size 字节（非 int/缺失 → 0，展示端换算 MB）；
      published=顶层 published_at 原文（非 str → ""，展示端格式化容错）。
    """
    if not isinstance(j, dict):
        return "", "", "", None, 0, ""
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
        sz = a.get("size")
        ent = (url, _asset_digest(a), sz if isinstance(sz, int) and not isinstance(sz, bool) else 0)
        if name.lower() == ASSET_NAME.lower():
            named.append(ent)
        if name.lower().endswith(".exe"):
            exes.append(ent)
    pick = named[0] if named else (exes[0] if len(exes) == 1 else ("", None, 0))
    url, digest, size = pick
    notes = j.get("body")
    pub = j.get("published_at")
    return (version, url, notes if isinstance(notes, str) else "", digest, size,
            pub if isinstance(pub, str) else "")


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
    M18：**本函数永不走镜像**（api.github.com 是信任锚，镜像只救二进制下载；
    元数据失败如实报错，不做第三方中转）。
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
        ver, dl, notes, digest, size, pub = parse_release(j)
        if not ver:
            return CheckResult(err="响应缺少 tag_name（仓库无 release？）")
        return CheckResult(ok=True, info=UpdateInfo(version=ver, url=dl, notes=notes,
                                                    digest=digest, size=size,
                                                    published=pub))
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


# ---------------- M18：镜像备用源（仅救二进制；元数据永不走镜像） ----------------

def normalize_mirror(s) -> str:
    """用户输入 → 规范拼接前缀 "scheme://host[:port]/"；空/非法 → ""（不使用）。

    两种输入形态统一收敛为「前缀 + 原URL」拼接式：
    - 纯前缀："ghfast.top" / "https://ghfast.top" / "https://ghfast.top/" → 补
      https:// 前缀、去路径、补尾 "/"；
    - 占位式："https://ghfast.top/https://github.com/…" → 视 "/" 后为被加速 URL，
      同样只取 origin 段 → "https://ghfast.top/"。
    即**路径段一律丢弃**（两形态 normalize 后拼原 URL 语义一致）。拒绝：非法字符、
    端口越界、socks 等非标 scheme、含 userinfo（镜像不携带凭据）。永不抛。
    """
    if not isinstance(s, str):
        return ""
    t = s.strip()
    if not t:
        return ""
    if "://" not in t:
        t = "https://" + t
    try:
        p = urllib.parse.urlsplit(t)
        port = p.port                                 # 非数字/越界 → ValueError
    except ValueError:
        return ""
    scheme = (p.scheme or "").lower()
    if scheme not in ("http", "https") or not p.hostname:
        return ""
    if p.username is not None or p.password is not None:
        return ""
    if not re.fullmatch(r"[\w.\\-]+|\[[0-9a-fA-F:]+]", p.hostname):
        return ""                                     # 域名/IPv6 字面量之外视为畸形
    hb = p.hostname if p.hostname.startswith("[") else p.hostname
    host = f"{hb}:{port}" if port else hb
    return f"{scheme}://{host}/"


def mirror_join(mirror: str, url: str) -> str:
    """拼接式套用：normalize 后的前缀 + 原 URL（占位式镜像的自然形态）。"""
    return (mirror + url) if mirror else url


def _dl_attempts(cfg, url: str) -> list[tuple[str, str, object]]:
    """回退链 (channel, target_url, opener)：①直连 ②代理开启+合法 ③镜像配置。

    与 check() 的代理回落语义同源（netconfig.build_opener）；镜像腿走直连
    （国内镜像无需代理）。cfg=None/非 dict → 只有直连腿（旧调用零改动语义）。
    """
    attempts: list[tuple[str, str, object]] = [("direct", url, None)]
    if isinstance(cfg, dict):
        net = _config_net(cfg)
        proxy = netconfig.normalize_proxy_url(net.get("proxy_url")) \
            if net.get("proxy_enabled") else None
        if proxy:
            attempts.append(("proxy", url, netconfig.build_opener(proxy)))
        mir = normalize_mirror(_section(cfg).get("mirror"))
        if mir:
            attempts.append(("mirror", mirror_join(mir, url), None))
    return attempts


def _digest_expect(digest) -> str | None:
    """digest 入参归一（"sha256:<hex64>" / 裸 64hex → 标准形态；其余 → None）。"""
    if not isinstance(digest, str):
        return None
    t = digest.strip().lower()
    if t.startswith("sha256:"):
        t = t.split(":", 1)[1].strip()
    return f"sha256:{t}" if _SHA256_HEX.fullmatch(t) else None


def _dl_open(req, timeout: float, att_opener, req_open):
    """传输接缝：req_open(r, timeout=, opener=) 注入点（测试记录通道三要素）。"""
    if req_open is not None:
        return req_open(req, timeout=timeout, opener=att_opener)
    target = att_opener if att_opener is not None else urllib.request.build_opener()
    return target.open(req, timeout=timeout)


def download_and_stage(url: str, cfg: dict | None = None, digest: str | None = None,
                       dest_dir: Path | str | None = None, opener=None,
                       req_open=None, chunk: int = 65536, progress_cb=None) -> DownloadResult:
    """流式下载到 <dest>/TokenWidget.new.exe（.part → 校验 → rename）。

    M18 回退链（_dl_attempts）：直连 → 代理（开启则经 build_opener）→ 镜像
    （配置则「前缀+原URL」重试）；每腿失败进下一腿，返回值 channel 记录**成功**
    所用通道，三链全败 err 汇总（脱敏）。
    M19：progress_cb(done_bytes, total_bytes)——每读满 ≥512KB 节流回调一次
    （total=Content-Length 声明值；回调异常吞掉，绝不因展示层打断下载）。
    完整性判据（按优先级）：
    1. Content-Length 必存在且与实收一致；
    2. digest 有值 → 流式 sha256 **必校验**，不符删 .part 报错（换腿重试）；
    3. digest 缺失：mirror 腿**拒收**（第三方字节无官方哈希不可信，删 .part）；
       direct/proxy 腿放行，note 说明「官方 API 未提供 digest，未做哈希校验」。
    任何失败清理 .part；只写 update 目录，不触碰既有凭据/配置。opener 参数为
    直连腿 opener 显式覆盖（历史测试/注入用），代理/镜像腿由 cfg 决定。
    """
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        return DownloadResult(err="下载链接非法（仅支持 https）")
    want = _digest_expect(digest)
    base = Path(dest_dir) if dest_dir is not None else update_dir()
    last_err = ""
    tried: list[str] = []
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return DownloadResult(err=netconfig.sanitize_proxy_msg(
            f"无法创建下载目录：{str(e)[:80]}"))
    for label, target_url, att_opener in _dl_attempts(cfg, url):
        tried.append(label)
        if label == "mirror" and want is None:
            last_err = "镜像源下载缺少官方 SHA-256 校验值，已拒收（镜像腿不可信裸字节）"
            continue
        part = base / (NEW_EXE_NAME + ".part")
        final = base / NEW_EXE_NAME
        try:
            if part.exists():
                part.unlink()
            r = urllib.request.Request(target_url, headers={"User-Agent": UA},
                                       method="GET")
            got = 0
            hasher = hashlib.sha256()
            with _dl_open(r, TIMEOUT, opener if label == "direct" else att_opener,
                          req_open) as resp:
                st = int(getattr(resp, "status", 200) or 200)
                if st != 200:
                    last_err = f"下载返回 HTTP {st}"
                    continue
                cl = None
                getter = getattr(resp.headers, "get", None)
                if callable(getter):
                    cl = getter("content-length")
                try:
                    cl_n = int(cl)
                except (TypeError, ValueError):
                    last_err = "响应缺 Content-Length，无法校验完整性（已放弃）"
                    continue
                with part.open("wb") as fh:
                    last_rep = 0
                    while True:
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        fh.write(buf)
                        hasher.update(buf)
                        got += len(buf)
                        # M19：≥512KB 节流回投（每腿独立计数）；展示层异常不断下载
                        if (progress_cb is not None
                                and got - last_rep >= PROGRESS_STEP_BYTES):
                            last_rep = got
                            try:
                                progress_cb(got, cl_n)
                            except Exception:       # noqa: BLE001
                                pass
            if got != cl_n:
                part.unlink(missing_ok=True)
                last_err = f"长度不符：声明 {cl_n} 实收 {got}（已放弃）"
                continue
            if want is not None:
                got_hex = f"sha256:{hasher.hexdigest()}"
                if got_hex != want:
                    part.unlink(missing_ok=True)
                    last_err = ("SHA-256 完整性校验不符（可能遭篡改或截断，已删除）："
                                f"期望 {want[:18]}… 实收 {got_hex[:18]}…")
                    continue
                note = ""
            else:
                note = "官方 API 未提供 SHA-256 digest，本次未做哈希校验（直连/代理放行）"
            os.replace(part, final)
            return DownloadResult(path=final, channel=label, note=note)
        except (urllib.error.URLError, OSError) as e:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
            last_err = netconfig.sanitize_proxy_msg(
                f"下载失败：{str(getattr(e, 'reason', e))[:120]}")
            continue
    suffix = "" if len(tried) <= 1 else f"（{'→'.join(tried)} 全部失败）"
    return DownloadResult(err=(last_err or "下载失败") + suffix)


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


def _writable_dir(base: Path) -> bool:
    try:
        base.mkdir(parents=True, exist_ok=True)
        t = base / ".write_test.tmp"
        t.write_bytes(b"")
        t.unlink()
        return True
    except OSError:
        return False


# ---------------- M28：去 cmd 化重启链（marker 驱动，新实例自我替换，零可见窗口） ----------------
#
# 旧链（≤v1.9.0）病灶：os.spawnv(P_DETACH, cmd /c restart_update.cmd) 的分离态父链
# 令 Windows「Security validation failure: failed to obtain executable path for
# parent process」校验在 cmd 内 start 步骤查询父 exe 路径失败 → 弹窗且新实例不被
# 拉起（改名/搬运在弹窗前已完成，替换本身成功）。新链：下载校验完成后写 marker →
# 直接 Popen **staged 新 exe 本体**（DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP，
# 不经任何 shell）带 --post-update-swap --start-marker <path> → 旧实例退出；
# 新实例启动早期执行改名序列（old→.old 占用重试 → **改名自身 .new→正名**（Windows
# 允许改运行中 exe 映像文件名，进程继续跑）→ 删 marker → 以正身运行）。
# 失败路径：写 FAILED.txt（面板既有消费链）→ 照常运行 staged 位置不 brick。
# 双向兼容硬要求：无 marker 时 run_pending_swap 零副作用（老用户正常启动不受影响）；
# marker 过期(>10min)视为陈旧自清——唯一例外当前进程即 marker.new（请求是给"我"的，
# 过期也执行，否则更新链断头）。

def marker_dir_and_path(base: Path | None = None) -> tuple[Path, Path]:
    """(marker 目录, marker 路径)。默认 update_dir()；提权路径可指 TEMP 可写处。"""
    d = base if base is not None else update_dir()
    return d, d / MARKER_NAME


def write_marker(old: Path, new: Path, base: Path | None = None,
                 now: float | None = None) -> Path:
    """写换装请求 marker（JSON：old/new/ts）。目录不可写抛 OSError 由调用方兜。"""
    d, mp = marker_dir_and_path(base)
    d.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps({"old": str(old), "new": str(new),
                              "ts": int(time.time() if now is None else now)},
                             ensure_ascii=False), encoding="utf-8")
    return mp


def _read_marker(mp: Path) -> dict | None:
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict):
        return None
    old, new = m.get("old"), m.get("new")
    if not (isinstance(old, str) and old and isinstance(new, str) and new):
        return None
    try:
        ts = int(m.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0
    return {"old": Path(old), "new": Path(new), "ts": ts}


def _prune_old_files(exe_dir: Path, keep: int = 1) -> None:
    """启动顺手清理：tokenwidget*.old 陈旧副本按 mtime 只保留最新 keep 个。永不抛。"""
    try:
        olds = sorted((p for p in exe_dir.glob("*.old")
                       if p.is_file() and p.name.lower().startswith("tokenwidget")),
                      key=lambda p: p.stat().st_mtime)
        for p in (olds[:-keep] if keep else olds):
            try:
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _rename_retry(src: Path, dst: Path, tries: int = 10, delay: float = 0.5,
                  sleeper=None) -> None:
    """占用重试改名（旧实例可能尚未完全退出）。全败抛最后一次 OSError。"""
    import time as _t
    sleep = sleeper if sleeper is not None else _t.sleep
    last: OSError | None = None
    for i in range(tries):
        try:
            os.rename(src, dst)
            return
        except OSError as e:
            last = e
            if i < tries - 1:
                sleep(delay)
    raise last or OSError("rename failed")


def _image_holder_alive(exe_path: Path) -> bool:
    """是否有存活进程仍持 exe_path 映像（改名后的 .old 归属判据）。

    仅 CreateToolhelp32Snapshot 快照（TH32CS_SNAPMODULE32|SNAPMODULE），零提权、
    对 64 位同构进程足够；任何不可读（权限/架构差）→ 保守 False=孤儿判。
    """
    import ctypes
    from ctypes import wintypes
    name = exe_path.name.lower()

    class ME32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("glbcntUsage", ctypes.c_void_p), ("modcntUsage", wintypes.DWORD),
                    ("hModule", wintypes.HINSTANCE),
                    ("modBaseAddr", ctypes.c_void_p), ("modSize", ctypes.c_size_t),
                    ("szModule", ctypes.c_wchar * 256),
                    ("szExePath", ctypes.c_wchar * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x18, 0)      # MODULE32|MODULE
    if snap == -1:
        return False
    me = ME32W()
    me.dwSize = ctypes.sizeof(ME32W)
    alive = False
    try:
        ok = k32.Module32FirstW(snap, ctypes.byref(me))
        while ok:
            try:
                if me.szExePath.lower().endswith("\\" + name):
                    alive = True
                    break
            except ValueError:
                pass
            ok = k32.Module32NextW(snap, ctypes.byref(me))
    finally:
        k32.CloseHandle(snap)
    return alive


def run_pending_swap(current_exe: Path | str | None = None,
                     marker_override: Path | str | None = None,
                     now: float | None = None, sleeper=None) -> str:
    """新实例启动早期调用：有 marker 才动作，无 marker 零副作用（双向兼容硬要求）。

    序列：先处理**仍占用正名的历史 .old**（旧实例仍持映像=刚完成的换装竞态——
    仅清 marker 收尾绝不搬回；真孤儿=崩溃残留——搬回正名自修复，防 staged 起不来）
    → old→old.old（占用重试 10×500ms）→ new→正名
    （os.replace 同卷原子；new 可能就是**当前运行的自己**——Windows 允许改运行中
    exe 的文件名，进程续跑）→ 删 marker → 清历史 .old（只留最新 1）。
    失败：写 FAILED.txt（既有消费链）→ 删 marker（防重启循环）→ 返回 "failed"，
    调用方照常以 staged 位置运行（不 brick）。
    marker 过期(>MARKER_TTL_SECONDS)：默认视为陈旧自清不执行；**例外**——本进程
    即 marker.new（flag 拉起但消费前崩过一次等），过期也执行。
    返回 ""=无事可做 / "swapped"=已就位 / "failed"=见 FAILED.txt。
    """
    cur = Path(current_exe) if current_exe is not None else Path(sys.executable)
    mp = Path(marker_override) if marker_override is not None else marker_dir_and_path()[1]
    m = _read_marker(mp)
    if m is None:
        if mp.exists():                                   # 坏 marker：清掉防每次启动白读
            try:
                mp.unlink()
            except OSError:
                pass
        return ""
    old, new, ts = m["old"], m["new"], m["ts"]
    t = time.time() if now is None else float(now)
    try:
        self_is_new = new.is_file() and cur.resolve() == new.resolve()
    except OSError:
        self_is_new = False
    if t - ts > MARKER_TTL_SECONDS and not self_is_new:
        try:
            mp.unlink()
        except OSError:
            pass
        return ""
    side = old.with_name(old.name + ".old")
    if not new.is_file():
        if not old.is_file() and side.is_file():
            if _image_holder_alive(side):
                try:                                      # 旧实例仍在跑 .old：换装已
                    mp.unlink()                           # 实质完成——仅收尾，禁搬回
                except OSError:
                    pass
                return "swapped"
            try:                                          # 真孤儿 .old（旧实例崩溃
                os.replace(side, old)                     # 残留）：搬回正名自修复
                mp.unlink()
            except OSError:
                pass
            return ""
        if old.is_file():                                 # 正名已在（成功换装的收尾竞态
            try:                                          # /重复消费）：清 marker 即止
                mp.unlink()
            except OSError:
                pass
            return "swapped"
        return ""
    fail_path = mp.parent / FAILED_NAME
    try:
        _prune_old_files(old.parent, keep=0)              # 历史 .old 全清，腾名位给本轮
        _rename_retry(old, side, sleeper=sleeper)
        os.replace(new, old)                              # .new→正名（可改名自己）
        try:
            mp.unlink()
        except OSError:
            pass
        return "swapped"
    except (OSError, ValueError) as e:
        try:
            fail_path.write_text(
                f"swap_failed: {str(e)[:120]} old={old.name} new={new.name}",
                encoding="gbk", errors="replace")
        except OSError:
            pass
        try:
            mp.unlink()
        except OSError:
            pass
        return "failed"


def _shell_runas(exe: Path, args: list[str]) -> int:
    """ShellExecuteW "runas"（一次 UAC，替代 PS -Verb RunAs 包 cmd）；返回 HINSTANCE。

    >32=成功；≤32 含 1223（用户取消 UAC）。独立函数=测试注入点。
    """
    import ctypes
    from ctypes import wintypes
    params = " ".join(f'"{a}"' for a in args)
    se = ctypes.windll.shell32.ShellExecuteW
    se.restype = ctypes.c_long
    se.argtypes = (wintypes.HWND, ctypes.c_wchar_p, ctypes.c_wchar_p,
                   ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int)
    return se(None, "runas", str(exe), params, None, 0)       # SW_HIDE


def apply_update_and_restart(new_exe: Path | str | None = None,
                             current_exe: Path | str | None = None,
                             popen=None, exit_fn=None, elevated: bool = False,
                             probe=None, runas=None) -> str:
    """M28 新链：写 marker → Popen staged 新 exe 本体（--post-update-swap +
    --start-marker，DETACHED|NEW_PROCESS_GROUP，零 shell）→ 本进程退出。
    返回 ""=已接管，否则原因（不退出）。

    - current_exe：默认 sys.executable（frozen=TokenWidget.exe 本体）；测试注入。
    - new_exe：默认 staging 的 TokenWidget.new.exe；调用前须已 download_and_stage。
    - probe/exit_fn：测试注入（预检、退出替身）；popen：Popen 替身；runas：_shell_runas 替身。
    - 预检失败且未提权 → NEED_ELEVATION 前缀（面板出「提权更新」钮，行为不变）；
      elevated=True → ShellExecuteW runas 直接提权拉新 exe（一次 UAC；exe 目录
      不可写时 marker 落 %TEMP% 可写处、路径随参数传）；runas 被拒 → 既有指路文案。
    """
    cur = Path(current_exe) if current_exe is not None else Path(sys.executable)
    new = Path(new_exe) if new_exe is not None else update_dir() / NEW_EXE_NAME
    if not new.is_file():
        return "尚未下载更新包（先「立即更新」）"
    if cur.name.lower() == new.name.lower():
        return "当前运行体不是 TokenWidget.exe（dev 模式不支持自更新）"
    check = probe_replace_permission if probe is None else probe
    marker_base: Path | None = None
    if not check(cur):                               # 预检失败 → 不退出，交回面板决策
        if not elevated:
            return NEED_ELEVATION + "当前目录无写入权限，可选提权更新或移动位置"
        base = update_dir()
        if not _writable_dir(base):
            base = Path(os.environ.get("TEMP", str(Path.home()))) / "token-widget-update"
            if not _writable_dir(base):
                return "当前目录无写入权限：请先把程序移到可写目录（如用户目录）再更新"
        marker_base = base
    try:
        mp = write_marker(cur, new, base=marker_base)
    except OSError as e:
        return f"无法写入换装请求：{str(e)[:80]}"
    if elevated:
        rf = runas if runas is not None else _shell_runas
        try:
            rc = rf(new, [SWAP_FLAG, SWAP_MARKER_FLAG, str(mp)])
        except OSError as e:
            try:
                mp.unlink()
            except OSError:
                pass
            return f"提权启动失败：{str(e)[:80]}"
        if rc <= 32 or rc == 1223:                    # 1223=ERROR_CANCELLED（UAC 被拒，
            # 该失败码数值上 >32，是 ShellExecuteW 返回约定的唯一例外）
            try:
                mp.unlink()
            except OSError:
                pass
            return "提权被取消：请把程序移到可写目录（如用户目录）再更新"
        (exit_fn or os._exit)(0)
        return ""
    import subprocess
    popenf = popen if popen is not None else subprocess.Popen
    try:
        popenf([str(new), SWAP_FLAG, SWAP_MARKER_FLAG, str(mp)],
               creationflags=SWAP_DETACH_FLAGS, close_fds=True)
    except OSError as e:
        try:
            mp.unlink()
        except OSError:
            pass
        return f"无法启动新实例：{str(e)[:80]}"
    (exit_fn or os._exit)(0)
    return ""
