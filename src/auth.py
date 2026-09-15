"""凭据管理：Windows DPAPI(CurrentUser) 加解密的本地会话凭据。

存储约定（M0 起）：
- token-widget/local/bailian_cookie.dpapi  百炼控制台浏览器会话 Cookie（整串 UTF-8 → DPAPI）
- 明文 Cookie 不落盘；x-xsrf-token 由 login_aliyunid_csrf 字段派生；sec_token 运行时获取。
- M3：save_bailian_cookie() 供设置/续期流写回（DPAPI → .tmp → os.replace 原子写）。
  path 参数化是测试重定向的硬要求；本模块任何函数不打印/回显 Cookie 内容。

M6 扩展（不动上方百炼三函数）：
- 通用 secret：local/<name>.dpapi，同款原子写；现知名：opencode_go_key /
  codex_access_token（M11a 起 openai_admin_key/openai_user_key 已随 API 侧移除）。
- detect_go_key()：只读 %USERPROFILE%\\.local\\share\\opencode\\auth.json 顶层
  "opencode-go" 条目（type≠api 丢弃；**绝不读 "opencode" Zen 条目**——Zen key 打
  Go usage 端点必 403，规格 §2.3）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
from pathlib import Path

# frozen 时 local/ 落在 exe 同级（DPAPI 与用户绑定，同用户下 blob 可直接复用）
if getattr(sys, "frozen", False):
    LOCAL_DIR = Path(sys.executable).resolve().parent / "local"
else:
    LOCAL_DIR = Path(__file__).resolve().parent.parent / "local"
BAILIAN_COOKIE_FILE = LOCAL_DIR / "bailian_cookie.dpapi"


class _DATA(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt32():
    return ctypes.windll.crypt32


def _kernel32():
    return ctypes.windll.kernel32


def dpapi_unprotect(blob: bytes) -> str:
    """解密 CurrentUser 作用域的 DPAPI 数据（CryptUnprotectData）。"""
    din = _DATA(len(blob), ctypes.cast(ctypes.create_string_buffer(blob, len(blob)),
                                        ctypes.POINTER(ctypes.c_char)))
    dout = _DATA()
    ok = _crypt32().CryptUnprotectData(ctypes.byref(din), None, None, None, None, 0,
                                        ctypes.byref(dout))
    if not ok:
        raise OSError(f"CryptUnprotectData failed: {ctypes.GetLastError()}")
    try:
        return ctypes.string_at(dout.pbData, dout.cbData).decode("utf-8")
    finally:
        _kernel32().LocalFree(ctypes.cast(dout.pbData, ctypes.c_void_p))


def dpapi_protect(text: str) -> bytes:
    """加密为 CurrentUser 作用域的 DPAPI 数据。"""
    raw = text.encode("utf-8")
    din = _DATA(len(raw), ctypes.cast(ctypes.create_string_buffer(raw, len(raw)),
                                       ctypes.POINTER(ctypes.c_char)))
    dout = _DATA()
    ok = _crypt32().CryptProtectData(ctypes.byref(din), None, None, None, None, 0,
                                      ctypes.byref(dout))
    if not ok:
        raise OSError(f"CryptProtectData failed: {ctypes.GetLastError()}")
    try:
        return ctypes.string_at(dout.pbData, dout.cbData)
    finally:
        _kernel32().LocalFree(ctypes.cast(dout.pbData, ctypes.c_void_p))


def load_bailian_cookie() -> str:
    """读取并解密百炼控制台 Cookie 整串。"""
    return dpapi_unprotect(BAILIAN_COOKIE_FILE.read_bytes())


def save_bailian_cookie(cookie: str, path: Path = BAILIAN_COOKIE_FILE) -> None:
    """DPAPI 加密后原子写入（先 <path>.tmp 再 os.replace）。

    - path 参数化：测试必须传临时文件，禁止覆盖真实凭据。
    - 异常信息只含路径/系统错误码，绝不含 Cookie 内容。
    """
    if not isinstance(cookie, str) or not cookie:
        raise ValueError("cookie 不能为空")
    blob = dpapi_protect(cookie)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(blob)
        os.replace(tmp, path)          # 同目录原子替换，崩溃不留半个明文/密文
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


# ================= M6：通用 DPAPI secret（OpenCode Go / Codex keys） =================
# 文件约定 local\<name>.dpapi；原子写复用 save_bailian_cookie 范本。
# 现知名 name：opencode_go_key / codex_access_token（M11a：OpenAI 两枚已移除，
# 存量 local\openai_*.dpapi 文件由 M11a 清理；save/load 的 name 本就不限白名单）。
# 任何函数不打印/回显明面值；path 参数化是测试重定向的硬要求（真实 local\ 不碰）。

SECRET_NAMES = ("opencode_go_key", "codex_access_token")
_OPENCODE_AUTH_REL = Path(".local") / "share" / "opencode" / "auth.json"
_CODEX_AUTH_REL = Path(".codex") / "auth.json"


def _secret_file(name: str, path: Path | str | None = None) -> Path:
    """secret 落盘路径；path 显式给出时完全以其为准（测试重定向），否则 LOCAL_DIR/<name>.dpapi。"""
    if path is not None:
        return Path(path)
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError(f"secret 名称非法：{name!r}")
    return LOCAL_DIR / f"{name}.dpapi"


def save_secret(name: str, text: str, path: Path | str | None = None) -> None:
    """DPAPI 加密后原子写入（先 <path>.tmp 再 os.replace）。异常信息只含路径/错误码，无明文。"""
    if not isinstance(text, str) or not text:
        raise ValueError("secret 不能为空")
    target = _secret_file(name, path)
    blob = dpapi_protect(text)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_bytes(blob)
        os.replace(tmp, target)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def load_secret(name: str, path: Path | str | None = None) -> str:
    """读取并解密 secret；文件缺失/损坏 → OSError（调用方决定回退，不外泄内容）。"""
    return dpapi_unprotect(_secret_file(name, path).read_bytes())


def has_secret(name: str, path: Path | str | None = None) -> bool:
    """secret 文件是否存在（不解密、不读内容）。"""
    try:
        return _secret_file(name, path).exists()
    except ValueError:
        return False


def detect_go_key(auth_path: Path | str | None = None) -> str | None:
    """自动检测 OpenCode Go key：auth.json 顶层 "opencode-go" 条目 {type:"api", key}。

    - type≠"api"、条目/文件缺失、JSON 损坏 → None；
    - **绝不读 "opencode"（Zen）条目**（规格 §2.3：Zen key 打此端点必 403）；
    - 对真实 auth.json 只读，不写不改。
    """
    if auth_path is not None:
        p = Path(auth_path)
    else:
        base = os.environ.get("USERPROFILE") or str(Path.home())
        p = Path(base) / _OPENCODE_AUTH_REL
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get("opencode-go")
    if not isinstance(entry, dict) or entry.get("type") != "api":
        return None
    key = entry.get("key")
    return key if isinstance(key, str) and key else None


def detect_codex_token(auth_path: Path | str | None = None) -> str | None:
    """自动检测 Codex（ChatGPT 订阅）OAuth access_token：`~\\.codex\\auth.json` 的
    `tokens.access_token`（Codex CLI 登录产物）。

    - 仅当 `auth_mode == "chatgpt"` 且 tokens.access_token 存在且为非空字符串时返回；
    - auth_mode≠chatgpt / 文件缺失 / JSON 损坏 / 无 tokens → None；
    - 与 OpenAI API key 完全不互通（规格：Codex 用 ChatGPT OAuth token；M11a 起
      API 侧已从产品移除，本函数只认 Codex CLI 产物）；
    - 对真实 auth.json 只读，不写不改，且绝不打印/回显 token 值。
    - path 参数化：测试注入伪造文件，禁止读真实凭据。
    """
    if auth_path is not None:
        p = Path(auth_path)
    else:
        base = os.environ.get("USERPROFILE") or str(Path.home())
        p = Path(base) / _CODEX_AUTH_REL
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("auth_mode") != "chatgpt":
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    tok = tokens.get("access_token")
    return tok if isinstance(tok, str) and tok else None


def codex_auth_candidates() -> list[Path]:
    """find_codex_auth 默认搜索序（M10b 自动读取）。

    ① LOCAL_DIR/auth.json —— dev=项目 local\\；frozen=exe 同级 local\\（部署投放位）
    ② LOCAL_DIR.parent/auth.json —— dev=项目根（用户手动投放位）；frozen=exe 同级
    ③ ~\\.codex\\auth.json —— Codex CLI 登录产物
    """
    home = os.environ.get("USERPROFILE") or str(Path.home())
    return [LOCAL_DIR / "auth.json",
            LOCAL_DIR.parent / "auth.json",
            Path(home) / _CODEX_AUTH_REL]


def find_codex_auth(paths: list[Path | str] | None = None
                    ) -> tuple[str, Path] | None:
    """按候选序找 Codex access_token：命中即返回 (token, source_path)。

    - 每个候选都过 detect_codex_token 校验链（auth_mode=chatgpt、access_token 非空）；
      文件缺失/JSON 损坏/不合格 → 静默跳下一个；全缺 → None；
    - source_path 仅供面板「检测来源」显示（相对路径 + 尾 4 位），**token 绝不进
      日志/UI**；候选文件一律只读，不写不改；
    - paths 参数化：测试注入伪造候选，禁止读真实凭据。
    """
    cands = [Path(p) for p in paths] if paths is not None else codex_auth_candidates()
    for p in cands:
        tok = detect_codex_token(p)
        if tok:
            return tok, p
    return None


def cookie_value(cookie_str: str, name: str) -> str | None:
    """从 Cookie 整串中取指定字段（用于派生 x-xsrf-token 等）。"""
    for part in cookie_str.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


if __name__ == "__main__":
    c = load_bailian_cookie()
    print(f"cookie chars={len(c)}")
    print("xsrf (login_aliyunid_csrf) =", cookie_value(c, "login_aliyunid_csrf"))
    print("ticket present =", bool(cookie_value(c, "login_aliyunid_ticket")))
