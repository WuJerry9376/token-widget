"""百炼 helper 子进程客户端（车道 C；协议 docs/bailian_helper_protocol.md，契约冻结）。

职责：spawn/复用常驻 `--bailian-helper` 子进程、行分隔 JSON 请求-响应（单调 id 配对）、
异步事件行（含 "event"）派发 on_event、每请求 45s 看门狗（超时 kill+重 spawn 一次，
二次失败 → HELPER_ERROR 并静默 15min）、helper stderr 追加进 local/helper.log（1MB 截断）、
atexit 兜底关闭（widget 退出不留隐藏 helper）。stdlib-only。

登录在途标记（login_inflight）：`login_interactive` 允许长看门狗（660s，协议 §6 L3
人工等待至多 10min），请求在途期间置位；poll 侧据此不向 helper 串行队列写命令、
直接回 LOGIN_EXPIRED 语义（见 sources/bailian.py），避免 45s 看门狗误杀人工登录弹窗。

红线（plan §3.4 / 协议 §1）：
- spawn 严禁 SW_HIDE / -WindowStyle Hidden / 隐藏类 creationflags——Windows 下由
  python 进程默认 STARTUPINFO 继承即可，窗口隐藏由 helper 侧 create_window(hidden=True) 做；
- 本模块不解析、不读写任何 cookie/账密明文；stderr 仅原样转储（helper 侧保证无明文）。
"""
from __future__ import annotations

import atexit
import itertools
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from ..config import LOCAL_DIR

WATCHDOG_SECONDS = 45.0      # 协议 §7：每请求看门狗（常规命令默认）
LOGIN_TIMEOUT_SECONDS = 660.0  # login_interactive 专用：协议 §6 L3 人工等待 10min + 余量
UNAVAILABLE_SECONDS = 900.0  # 二次失败后静默 15min（任务书）
LOG_MAX_BYTES = 1_000_000    # helper.log 约 1MB 截断

DEFAULT_PROFILE_DIR = LOCAL_DIR / "webview_profile"   # 协议 §1 生产默认
DEFAULT_LOG_PATH = LOCAL_DIR / "helper.log"

# dev 模式下 main.py 位于项目根（src/sources/ 上溯两级）
DEV_MAIN = Path(__file__).resolve().parent.parent.parent / "main.py"


def build_command(profile_dir, *, frozen=None, executable=None) -> list[str]:
    """冻结命令（协议 §1，任务书冻结形态）：
    - 打包：[exe, "--bailian-helper", "--profile-dir", <dir>]（不解释解释器替换）
    - dev ：[python(w), <ROOT>/main.py, "--bailian-helper", "--profile-dir", <dir>]
      plan §3.4：dev 用 pythonw.exe——存在同名同目录 pythonw 时替换 python.exe，
      避免每次 respawn 闪一个控制台窗口；仅换解释器，默认 STARTUPINFO 红线不变。
    """
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = str(executable or sys.executable)
    tail = ["--bailian-helper", "--profile-dir", str(profile_dir)]
    if frozen:
        return [exe] + tail
    if Path(exe).name.lower() == "python.exe":
        w = Path(exe).with_name("pythonw.exe")
        if w.is_file():
            exe = str(w)
    return [exe, str(DEV_MAIN)] + tail


class _TransportError(Exception):
    """stdio 断/看门狗超时/写失败 → 触发 kill+respawn 一次。"""


class BailianHelperClient:
    """常驻 helper 的 stdio 客户端。request() 串行化（widget 仅单轮询线程）。

    测试注入：popen（假 Popen 工厂）、log_path/profile_dir（tmp 路径）、timeout
    （缩短看门狗）、time_fn（快进 15min 静默窗）。
    """

    def __init__(self, profile_dir=None, log_path=None, *, popen=None,
                 timeout: float = WATCHDOG_SECONDS,
                 unavailable_s: float = UNAVAILABLE_SECONDS,
                 time_fn=time.monotonic) -> None:
        self.profile_dir = Path(profile_dir or DEFAULT_PROFILE_DIR)
        self.log_path = Path(log_path or DEFAULT_LOG_PATH)
        self.timeout = float(timeout)
        self.unavailable_s = float(unavailable_s)
        self._popen = popen or subprocess.Popen
        self._time = time_fn
        self.on_event: Callable[[dict], None] | None = None   # source 侧注入
        self._next_id = itertools.count(1)
        self._lock = threading.Lock()
        self._proc = None
        self._logf = None
        self._responses: queue.Queue = queue.Queue()
        self._unavailable_until = 0.0
        self._down_reason = "helper unavailable"
        self._mono = time.monotonic        # 看门狗时钟（测试注入假时钟模拟慢回包）
        self.login_inflight = False        # login_interactive 在途（含 login_required 事件）
        atexit.register(self.shutdown)

    # ---- 对外接口 ----

    def available(self) -> bool:
        """False = 静默窗内（auto 模式应直接走 legacy，不发起 spawn）。"""
        return self._time() >= self._unavailable_until

    def request(self, cmd: dict, timeout: float | None = None) -> dict:
        """发送一条命令（不含 id，本方法补发），等 id 配对响应。

        永不抛异常；失败回 `{"ok":false,"state":"error","error":"HELPER_ERROR",
        "detail":"..."}`（协议 §3 错误枚举）。看门狗超时 → kill+respawn 重试一次。
        `timeout=None` 用默认 45s；`login_interactive` 等长流程由调用方传入
        LOGIN_TIMEOUT_SECONDS（660s），避免人工登录中途被误杀。
        """
        with self._lock:
            if not self.available():
                return self._helper_error("helper 静默窗内（15min 降级）")
            is_login = cmd.get("cmd") == "login_interactive"
            last = "unknown"
            for _attempt in (1, 2):
                try:
                    self._ensure_spawn()
                except OSError as e:
                    # spawn 失败（FileNotFoundError 等）重试无意义 → 直接进静默窗
                    self._mark_unavailable(f"spawn fail: {type(e).__name__}: {str(e)[:120]}")
                    return self._helper_error(self._down_reason)
                try:
                    return self._roundtrip(dict(cmd), timeout)
                except _TransportError as e:
                    last = str(e)
                    if is_login:
                        self.login_inflight = False    # 超时/断线 → kill+respawn 前清旗标
                    self._restart()
            self._mark_unavailable(last)
            return self._helper_error(self._down_reason)

    def shutdown(self) -> None:
        """best-effort：{"cmd":"shutdown"} + 关 stdin（协议 §2 无 id）。atexit 已挂。"""
        self.login_inflight = False                      # 关进程 → 登录在途一并作废
        if not self._lock.acquire(timeout=2.0):
            self._kill_proc()
            return
        try:
            proc = self._proc
            stdin = proc.stdin if proc is not None else None
            if proc is not None and stdin is not None and proc.poll() is None:
                try:
                    stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                    stdin.flush()
                except OSError:
                    pass
                try:
                    stdin.close()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=3)
                except Exception:
                    self._kill_proc()
            self._cleanup()
        finally:
            self._lock.release()

    # ---- 内部：进程管理 ----

    def _ensure_spawn(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._cleanup()
        self._spawn()

    def _spawn(self) -> None:
        logf = self._open_log()
        try:
            # 红线：不传 creationflags / STARTUPINFO 隐藏参数，默认继承即可
            proc = self._popen(build_command(self.profile_dir),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=logf, text=True, encoding="utf-8", bufsize=1)
        except BaseException:
            logf.close()
            raise
        self._proc, self._logf = proc, logf
        threading.Thread(target=self._read_loop, args=(proc,),
                         daemon=True, name="bailian-helper-reader").start()

    def _restart(self) -> None:
        self._kill_proc()
        self._cleanup()

    def _kill_proc(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass

    def _cleanup(self) -> None:
        proc, self._proc = self._proc, None
        logf, self._logf = self._logf, None
        if proc is not None:
            for name in ("stdin", "stdout", "stderr"):
                pipe = getattr(proc, name, None)   # stderr=fileobj 时为 None
                try:
                    if pipe:
                        pipe.close()
                except (OSError, ValueError):
                    pass
        if logf is not None:
            try:
                logf.close()
            except OSError:
                pass
        self._drain()

    def _drain(self) -> None:
        try:
            while True:
                self._responses.get_nowait()
        except queue.Empty:
            pass

    def _open_log(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.log_path.stat().st_size >= LOG_MAX_BYTES:   # ~1MB 截断重开
                self.log_path.unlink(missing_ok=True)
        except OSError:
            pass
        return open(self.log_path, "a", encoding="utf-8", errors="replace")

    # ---- 内部：读线程与请求往返 ----

    def _read_loop(self, proc) -> None:
        """stdout 逐行：事件行即时派发（不阻塞 request），响应行入队配对。"""
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if "event" in obj:
                    name = obj.get("event")
                    if name == "login_required":
                        self.login_inflight = True       # L3 在途（防御：响应行通常已置位）
                    elif name in ("login_done", "login_failed"):
                        self.login_inflight = False      # 兜底清旗标
                    cb = self.on_event
                    if cb is not None:
                        try:
                            cb(obj)
                        except Exception:
                            pass                        # 事件回调不得杀读线程
                else:
                    self._responses.put(obj)
        except (OSError, ValueError):
            pass
        finally:
            # EOF 哨兵带进程身份：旧代 reader 的哨兵不能误杀新代请求
            self._responses.put({"_eof": True, "_proc": id(proc)})

    def _roundtrip(self, cmd: dict, timeout: float | None = None) -> dict:
        cid = next(self._next_id)
        cmd["id"] = cid
        is_login = cmd.get("cmd") == "login_interactive"
        stdin = self._proc.stdin if self._proc is not None else None
        if stdin is None:
            raise _TransportError("write: no stdin")
        if is_login:
            self.login_inflight = True                   # 写前哨：poll 侧据此闭嘴（协议 §6 L3）
        try:
            stdin.write(json.dumps(cmd, ensure_ascii=False) + "\n")
            stdin.flush()
        except (OSError, ValueError) as e:
            raise _TransportError(f"write: {type(e).__name__}") from e
        eff = self.timeout if timeout is None else float(timeout)
        deadline = self._mono() + eff
        while True:
            remaining = deadline - self._mono()
            if remaining <= 0:
                raise _TransportError("watchdog timeout")
            try:
                obj = self._responses.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if obj.get("_eof"):
                if obj.get("_proc") == id(self._proc):
                    raise _TransportError("helper stdout closed")
                continue                                 # 旧代哨兵 → 忽略
            if obj.get("id") == cid:
                if is_login:
                    self.login_inflight = False          # 配对响应到达 → 清旗标
                return obj
            # 非本请求 id → 丢弃（协议无多路复用，理论不发生）

    # ---- 内部：失败语义 ----

    def _mark_unavailable(self, reason: str) -> None:
        self._down_reason = str(reason)[:200]
        self._unavailable_until = self._time() + self.unavailable_s

    @staticmethod
    def _helper_error(detail) -> dict:
        return {"ok": False, "state": "error", "error": "HELPER_ERROR",
                "detail": str(detail)[:200]}
