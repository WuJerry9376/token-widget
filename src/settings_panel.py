"""M3 设置面板 + 百炼凭据续期面板；M6 起含密钥绑定面板
（无边框便签卡片，与浮窗同质感；改即写 config/state）。

约束：
- key/Cookie 内容任何时刻不回显（保存后立即清空输入框）、不进日志/tooltip；
  Go 自动检测仅显示尾 4 位；错误提示只含错误码与固定文案，不含凭据值；
- 开机自启只操作 HKCU\\...\\Run 下的 "token-widget" 值名（src/autostart.py）；
- M6：供应商复选框均可勾选；无凭据的源勾选时自动弹出其绑定面板；
  旁注动态化（有 key=已绑定 / 无=未绑定，点击均可进绑定面板）；
- M8：新增「网络代理」分组（HTTP/CONNECT，作用域境外源，**百炼不出现**）；
  地址宽进严规范化回显；代理 URL 可含认证段 → 测试连通结果等展示文本一律脱敏；
- M10：第 3 家 Codex 复选框 + ProviderKeyPanel 变体（检测/粘贴 access_token，
  保存即验证）；代理作用域加 Codex 勾选；面板文案标注「非官方接口，可能随时失效」
  （M12②：仅供应商复选框标签去「（实验性）」，绑定说明保留）；
- M12①：「启用代理」未勾选时代理地址/端口/作用域/测试连通整组禁用（单一同步函数
  _sync_probe_btn；Entry disabledbackground 融纸、勾选/按钮灰字，恢复勾选即时回常态）；
- M11a（2026-09-15 用户裁决）：OpenAI API 侧整行移除——供应商 3 家、代理作用域
  仅 OpenCode Go / Codex 两项；ProviderKeyPanel 不再受理 openai。
- M13：状态行右下角加版本签名「v<APP_VERSION> · by Jerry Wu」（f_note 字档 / FAINT，
  side=right 随面板宽度右对齐）；版本号取自 src/version.py 单一事实源，
  随 build/version_info.txt 同步由 fix-2 流程负责。
"""
from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Any

from . import auth, autostart, config as config_mod, netconfig, updater
from .version import APP_VERSION
from . import version as _version        # 属性引用（非 from import）：单一事实源可被测试钉验
from .ui import (CRED_ERRORS, BADGE_BG, BADGE_EDGE, FAINT, INK, OK, ORANGE,
                 PAPER, PAPER_EDGE, SOFT, SOFT_TXT, RED, TRACK, TRACK_EDGE,
                 WIN_LABELS, fmt_value, work_area)

ENTRY_BG = "#FFFCF0"
YELLOW_FG = "#8A651F"        # 阈值输入框文字色（区别于状态红绿，避免误读为报错）
RED_FG = "#8E3B30"


def _tk_colors() -> dict[str, Any]:
    """Label / Checkbutton / Button 通用配色。"""
    return dict(bg=PAPER, fg=INK, activebackground=PAPER, activeforeground=INK,
                disabledforeground=FAINT, highlightthickness=0, bd=0)


def _frame_kw() -> dict[str, Any]:
    """Frame 不支持 fg 系列选项，单独给容器用。"""
    return dict(bg=PAPER, highlightthickness=0, bd=0)


class _Card(tk.Toplevel):
    """便签卡片基类：纸色 + 2px 描边 + 标题条拖拽 + ✕ 关闭；工作区居中。

    M3c⑨ 面板质感裁决：与主便签同源但**刻意保持直角**——
    - 同源：同一套 PAPER/PAPER_EDGE/INK/FAINT 色板、2px 纸缘描边、
      标题下缝线改为与便签头部一致的 dashed 虚线（原来实线，视觉更"表格"）；
    - 直角理由：面板承载密集表单控件，圆角需 transparentcolor 色键 + 子控件
      无法被裁进圆角（tk 子窗口不支持任意 clip），会直接露馅穿帮；且纸纹点阵
      垫在输入框/复选框下伤可读性（本次审查②已证明 9px 灰字压纹理易误读）。
      浮窗是"贴桌上的便签"，面板是"从便签上撕下的操作单"——直角是功能分区，
      不是遗漏。
    """

    def __init__(self, app, title: str, geo_tag: str = "CARD") -> None:
        super().__init__(app.root, bg=PAPER_EDGE)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        inner = tk.Frame(self, bg=PAPER)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        self.head = tk.Frame(inner, bg=PAPER)
        self.head.pack(fill="x", padx=14, pady=(10, 0))
        t = tk.Label(self.head, text=title, font=app.f_title, **_tk_colors())
        t.pack(side="left")
        close = tk.Label(self.head, text="✕ 关闭", font=app.f_small,
                         cursor="hand2", **{**_tk_colors(), "fg": SOFT})
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.close_card())
        # 缝线（M3c⑨）：与便签头部虚线同色同律
        sep = tk.Canvas(inner, height=2, bg=PAPER, highlightthickness=0, bd=0)
        sep.pack(fill="x", padx=14, pady=(7, 0))
        sep.create_line(0, 1, 4000, 1, fill=PAPER_EDGE, dash=(2, 3))

        self.body = tk.Frame(inner, bg=PAPER)
        self.body.pack(fill="both", expand=True, padx=14, pady=(8, 12))

        # 标题条拖拽（含其内部 label）
        self._drag_off: tuple[int, int] | None = None
        for wid in (self.head, t, close):
            wid.bind("<ButtonPress-1>", self._ds, add="+")
            wid.bind("<B1-Motion>", self._dm, add="+")
        self.bind("<ButtonRelease-1>", self._de)

        self.geo_tag = geo_tag
        # 不在此居中：子类内容 pack 完成后调用 finish()
        self.withdraw()

    def finish(self) -> None:
        """子类构造完内容后调用：量尺寸 → 居中 → 显示。"""
        self.update_idletasks()
        self._center()
        self.deiconify()

    # ---- 拖拽 / 摆放 ----

    def _ds(self, e):
        self._drag_off = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _dm(self, e):
        if self._drag_off:
            self.geometry(f"+{e.x_root - self._drag_off[0]}+{e.y_root - self._drag_off[1]}")

    def _de(self, e):
        self._drag_off = None

    def _center(self) -> None:
        l, t, r, b = work_area()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = l + max(0, (r - l - w) // 2)
        y = t + max(0, (b - t - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        if getattr(self.app, "_print_geo", False):
            print(f"GEOMETRY {w}x{h}+{x}+{y}  [{self.geo_tag}]", flush=True)
        self.lift()

    # ---- 工具 ----

    def alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def close_card(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass

    def row(self, text: str) -> tk.Frame:
        """左标签行容器：控件由调用方以返回的 frame 为 parent 创建并 pack
        （tkinter 的 pack 作用于 widget 自身 master，不能事后塞进别的 frame）。
        width=17：M3c④ 文案加长后不换行、列对齐（沿用宽度，M11a 后无更长行标签）。"""
        f = tk.Frame(self.body, **_frame_kw())
        f.pack(fill="x", pady=3)
        tk.Label(f, text=text, width=17, anchor="w", font=self.app.f_small,
                 **_tk_colors()).pack(side="left")
        return f


def _section(app, key: str) -> dict:
    """config 节读取（DEFAULTS 兜底合并，老 config 缺节也安全）。"""
    d = dict(config_mod.DEFAULTS.get(key) or {})
    v = app.cfg.get(key)
    if isinstance(v, dict):
        d.update(v)
    return d


def _provider_bound(app, name: str) -> bool:
    """供应商是否已有可用凭据（旁注与"勾选即弹"共用判据；全程只探测不回显值）。"""
    if name == "bailian":
        return Path(auth.BAILIAN_COOKIE_FILE).exists()
    if name == "opencode_go":
        if auth.has_secret("opencode_go_key"):
            return True
        auto = bool(_section(app, "opencode_go").get("auto_detect", True))
        return bool(auto and auth.detect_go_key())
    if name == "codex":                            # M10b：手动 secret 或三候选自动检测
        return bool(auth.has_secret("codex_access_token") or auth.find_codex_auth())
    return False


def _split_proxy_echo(stored) -> tuple[str, str]:
    """(地址框, 端口框) 回显：能规范化 → 标准形态拆分；否则原样进地址框（宽进）。"""
    norm = netconfig.normalize_proxy_url(stored)
    raw = str(stored or "").strip()
    if not norm:
        return raw, ""
    rest = norm.split("://", 1)[1]
    head, sep, tail = rest.rpartition(":")
    return (head, tail) if sep and tail.isdigit() else (rest, "")


class SettingsPanel(_Card):
    """设置页：供应商启停 / 网络代理(M8) / 周期 / 阈值 / 置顶 / 自启。改即保存。"""

    def __init__(self, app) -> None:
        super().__init__(app, "设置", geo_tag="SETTINGS")
        cfg = app.cfg
        enabled = list(cfg.get("enabled_providers") or [])

        # ---- 供应商（M6 三家可勾选；M11a 去 OpenAI 后剩 3 家；旁注=动态绑定状态） ----
        tk.Label(self.body, text="供应商", font=app.f_small_b,
                 **{**_tk_colors(), "fg": SOFT_TXT}).pack(anchor="w", pady=(0, 2))
        self._pvars: dict[str, tk.BooleanVar] = {}
        self._notes: dict[str, tk.Label] = {}
        specs = [("bailian", "百炼 Token Plan"),
                 ("opencode_go", "OpenCode Go"),
                 ("codex", "Codex")]   # M10：ChatGPT Plan 窗口限额；M12② 标签去「（实验性）」，
                                       # 绑定面板内「非官方接口」提示保留
        for name, label in specs:
            var = tk.BooleanVar(value=name in enabled)
            self._pvars[name] = var
            rowf = tk.Frame(self.body, **_frame_kw())
            rowf.pack(fill="x", pady=1)
            tk.Checkbutton(rowf, text=label, variable=var, font=app.f_small,
                           selectcolor=BADGE_BG, cursor="hand2",
                           command=lambda n=name: self._on_provider_toggle(n),
                           **_tk_colors()).pack(side="left", padx=(0, 8))
            note = tk.Label(rowf, text="", font=app.f_note, cursor="hand2",
                            **_tk_colors())
            note.pack(side="left")
            note.bind("<Button-1>", lambda e, n=name: self._open_bind_panel(n))
            self._notes[name] = note
        self._refresh_notes()

        # ---- 网络代理（M8：仅境外源；百炼永不走代理、直连行为不变） ----
        tk.Label(self.body, text="网络代理", font=app.f_small_b,
                 **{**_tk_colors(), "fg": SOFT_TXT}).pack(anchor="w", pady=(10, 2))
        net = _section(app, "network")
        self.var_px_on = tk.BooleanVar(value=bool(net["proxy_enabled"]))
        tk.Checkbutton(self.body, text="启用代理（境外源）", variable=self.var_px_on,
                       font=app.f_small, selectcolor=BADGE_BG, cursor="hand2",
                       command=self._save_net, **_tk_colors()).pack(anchor="w")
        rf = self.row("代理地址")
        rf.pack_configure(pady=1)      # M8 视觉轮③：与供应商组同律（2px 级收紧，仅本组行）
        addr0, port0 = _split_proxy_echo(net.get("proxy_url"))
        self.var_px_addr = tk.StringVar(value=addr0)
        self.var_px_port = tk.StringVar(value=port0)
        ae = tk.Entry(rf, width=20, font=app.f_small, textvariable=self.var_px_addr,
                      bg=ENTRY_BG, fg=INK, insertbackground=INK, relief="flat",
                      highlightthickness=1, highlightbackground=PAPER_EDGE)
        ae.pack(side="left")
        ae.bind("<Return>", self._save_net)
        ae.bind("<FocusOut>", self._save_net)
        self.ent_px_addr = ae                             # M12① 禁用态同步需要引用
        tk.Label(rf, text="  端口", font=app.f_small, **_tk_colors()).pack(side="left")
        # 用 Entry 而非 Spinbox：Spinbox 绑定空变量会在渲染时回填 from_（实测 "1"），
        # 污染"地址+端口"组合判断；端口数字合法性交给 normalize_proxy_url 严出。
        pe = tk.Entry(rf, width=7, font=app.f_small, textvariable=self.var_px_port,
                      bg=ENTRY_BG, fg=INK, insertbackground=INK, relief="flat",
                      highlightthickness=1, highlightbackground=PAPER_EDGE)
        pe.pack(side="left")
        pe.bind("<Return>", self._save_net)
        pe.bind("<FocusOut>", self._save_net)
        self.ent_px_port = pe                             # M12①
        tk.Label(self.body,
                 text="    HTTP 代理（Clash/V2Ray 混合端口如 127.0.0.1:7890 一般同为 HTTP；不支持 socks）",
                 font=app.f_note, **{**_tk_colors(), "fg": FAINT}).pack(anchor="w")
        rf = self.row("作用范围")
        rf.pack_configure(pady=1)      # M8 视觉轮③
        tg = net.get("proxy_targets")
        tg = tg if isinstance(tg, list) else []
        self.var_px_go = tk.BooleanVar(value="opencode_go" in tg)
        self.var_px_cx = tk.BooleanVar(value="codex" in tg)      # M10
        self.chk_px_go = tk.Checkbutton(rf, text="OpenCode Go", variable=self.var_px_go,
                                        font=app.f_small, selectcolor=BADGE_BG,
                                        cursor="hand2", command=self._save_net,
                                        **_tk_colors())
        self.chk_px_go.pack(side="left", padx=(0, 10))
        self.chk_px_cx = tk.Checkbutton(rf, text="Codex", variable=self.var_px_cx,
                                        font=app.f_small, selectcolor=BADGE_BG,
                                        cursor="hand2", command=self._save_net,
                                        **_tk_colors())
        self.chk_px_cx.pack(side="left")
        rf = self.row("连通测试")
        rf.pack_configure(pady=1)      # M8 视觉轮③
        # M8 视觉轮①：按钮两态——
        #   常态（启用代理已勾）：底色加深一档 TRACK(227,211,169) + 1px TRACK_EDGE
        #     (207,185,138) 描边：沿用凭据面板「取消」浅描边语言并加深一档，
        #     与面板底 PAPER(251,243,223) ΔRGB=(24,32,54) 一眼可辨；
        #   禁用态（未启用代理）：灰字 FAINT + 无描边 + 底色融回纸面（弱化不可点）。
        #   未启用代理时“测试连通”无对象，态语义与凭据面板的保存/取消层级一致。
        self.btn_probe = tk.Button(rf, text="测试连通", font=app.f_small, cursor="arrow",
                                   bg=TRACK, fg=SOFT_TXT,
                                   activebackground=TRACK_EDGE, activeforeground=INK,
                                   disabledforeground=FAINT,
                                   relief="flat", bd=0, padx=12, pady=2,
                                   highlightthickness=1, highlightbackground=TRACK_EDGE,
                                   command=self._probe_net)
        self.btn_probe.pack(side="left")
        self.lbl_net = tk.Label(rf, text="  不依赖凭据：拿到任意 HTTP 响应即通道正常",
                                font=app.f_note, **{**_tk_colors(), "fg": FAINT})
        self.lbl_net.pack(side="left")
        self._sync_probe_btn()

        # ---- 更新（M15：GitHub Releases；检查可定时/手动，下载/替换仅用户明确动作） ----
        tk.Label(self.body, text="更新", font=app.f_small_b,
                 **{**_tk_colors(), "fg": SOFT_TXT}).pack(anchor="w", pady=(10, 2))
        up = _section(app, "update")
        self.var_up_auto = tk.BooleanVar(value=bool(up.get("enabled", True)))
        tk.Checkbutton(self.body, text="自动更新（打开本页自动检查一次，6 小时内至多一次）",
                       variable=self.var_up_auto, font=app.f_small,
                       selectcolor=BADGE_BG, cursor="hand2", command=self._save_update_cfg,
                       **_tk_colors()).pack(anchor="w")
        rf = self.row("当前版本")
        tk.Label(rf, text=f"v{APP_VERSION}", font=app.f_small,
                 **{**_tk_colors(), "fg": FAINT}).pack(side="left")
        self.lbl_up_repo = tk.Label(rf, text="", font=app.f_note,
                                    **{**_tk_colors(), "fg": FAINT})
        self.lbl_up_repo.pack(side="left")
        rf = self.row("检查更新")
        rf.pack_configure(pady=1)
        self.btn_up_check = tk.Button(rf, text="检查更新", font=app.f_small,
                                      cursor="hand2", bg=BADGE_BG, fg=INK,
                                      activebackground=BADGE_EDGE, relief="flat", bd=0,
                                      padx=12, pady=2, highlightthickness=1,
                                      highlightbackground=BADGE_EDGE,
                                      command=lambda: self._up_refresh(True))
        self.btn_up_check.pack(side="left")
        self.lbl_up = tk.Label(self.body, text="", font=app.f_small, wraplength=440,
                               justify="left", **{**_tk_colors(), "fg": SOFT_TXT})
        self.lbl_up.pack(anchor="w", pady=(2, 0))
        self._up_btnf = tk.Frame(self.body, **_frame_kw())   # 下载/确认按钮行（按需 pack）
        self.btn_up_dl = tk.Button(self._up_btnf, text="立即下载并更新",
                                   font=app.f_small_b, cursor="hand2", bg=INK, fg=PAPER,
                                   activebackground="#57503E", relief="flat", bd=0,
                                   padx=14, pady=3, command=self._up_ask_confirm)
        self.btn_up_go = tk.Button(self._up_btnf, text="确认更新",
                                   font=app.f_small_b, cursor="hand2", bg=INK, fg=PAPER,
                                   activebackground="#57503E", relief="flat", bd=0,
                                   padx=14, pady=3, command=self._up_apply)
        self.btn_up_no = tk.Button(self._up_btnf, text="取消", font=app.f_small,
                                   cursor="hand2", bg=BADGE_BG, fg=SOFT_TXT,
                                   activebackground=BADGE_EDGE, relief="flat", bd=0,
                                   padx=14, pady=3, highlightthickness=1,
                                   highlightbackground=BADGE_EDGE,
                                   command=self._up_confirm_cancel)
        self._up_info = None            # 本轮发现的 UpdateInfo（下载动作的唯一来源）
        self._up_busy = False
        self._up_q = queue.Queue()
        self._up_sync_repo_label()
        self.after(150, self._up_poll)
        if self.var_up_auto.get():      # 定时路径：进页即查一次（updater 内 6h 频控）
            self.after(400, lambda: self._up_refresh(False))

        # ---- 轮询周期 ----
        self.var_poll = tk.StringVar(value=str(int(cfg.get("poll_seconds", 300))))
        rf = self.row("轮询周期（秒）")
        sp = tk.Spinbox(rf, from_=60, to=3600, increment=30, width=6,
                        textvariable=self.var_poll, font=app.f_small,
                        bg=ENTRY_BG, fg=INK, insertbackground=INK,
                        buttonbackground=BADGE_BG, relief="flat",
                        highlightthickness=1, highlightbackground=PAPER_EDGE)
        sp.pack(side="left")
        sp.bind("<Return>", self._save_poll)
        sp.bind("<FocusOut>", self._save_poll)
        sp.bind("<<Increment>>", lambda e: self.after(50, self._save_poll_quiet))
        sp.bind("<<Decrement>>", lambda e: self.after(50, self._save_poll_quiet))
        tk.Label(rf, text="  60~3600", font=app.f_note,
                 **{**_tk_colors(), "fg": SOFT_TXT}).pack(side="left")

        # ---- 阈值 ----
        self.var_yellow = tk.StringVar(value=f"{float(cfg.get('low_yellow_pct', 0.15)) * 100:g}")
        self.var_red = tk.StringVar(value=f"{float(cfg.get('low_red_pct', 0.05)) * 100:g}")
        rf = self.row("低余量阈值（%）")
        y_sp = tk.Spinbox(rf, from_=1, to=99, increment=1, width=4,
                          textvariable=self.var_yellow, font=app.f_small,
                          bg=ENTRY_BG, fg=YELLOW_FG, insertbackground=INK,
                          buttonbackground=BADGE_BG, relief="flat",
                          highlightthickness=1, highlightbackground=PAPER_EDGE)
        y_sp.pack(side="left")
        y_sp.bind("<Return>", self._save_thr)
        y_sp.bind("<FocusOut>", self._save_thr)
        tk.Label(rf, text="  黄 ／", font=app.f_small,
                 **_tk_colors()).pack(side="left")
        r_sp = tk.Spinbox(rf, from_=1, to=99, increment=1, width=4,
                          textvariable=self.var_red, font=app.f_small,
                          bg=ENTRY_BG, fg=RED_FG, insertbackground=INK,
                          buttonbackground=BADGE_BG, relief="flat",
                          highlightthickness=1, highlightbackground=PAPER_EDGE)
        r_sp.pack(side="left")
        r_sp.bind("<Return>", self._save_thr)
        r_sp.bind("<FocusOut>", self._save_thr)
        tk.Label(rf, text="  红（剩余低于此值着色）", font=app.f_note,
                 **{**_tk_colors(), "fg": SOFT_TXT}).pack(side="left")

        # ---- 总在最前（与浮窗菜单双向同步） ----
        self.var_top = tk.BooleanVar(value=app.topmost)
        tk.Checkbutton(self.body, text="总在最前", variable=self.var_top,
                       font=app.f_small, selectcolor=BADGE_BG, cursor="hand2",
                       command=lambda: app.set_topmost(bool(self.var_top.get())),
                       **_tk_colors()).pack(anchor="w", pady=(8, 2))

        # ---- 开机自启（只写 HKCU Run 的 "token-widget" 值名） ----
        self.var_auto = tk.BooleanVar(value=autostart.is_enabled())
        tk.Checkbutton(self.body, text="开机自启", variable=self.var_auto,
                       font=app.f_small, selectcolor=BADGE_BG, cursor="hand2",
                       command=self._apply_autostart,
                       **_tk_colors()).pack(anchor="w")
        cmd = autostart.command_line()
        tk.Label(self.body, text=f"    {cmd[:66]}{'…' if len(cmd) > 66 else ''}",
                 font=app.f_tiny, **{**_tk_colors(), "fg": FAINT}).pack(anchor="w")

        # ---- 状态行（M13：同行右端为静态版本签名） ----
        # 落位：foot 行 fill=x，左 status 维持原样（改即保存的行为提示、SOFT_TXT），
        # 右 lbl_ver `v… · by Jerry Wu` 同用 f_note 字档但降一档 FAINT——比状态行更轻，
        # 不与 _say 的即时反馈抢戏；side="right" 贴 body 右缘，随面板宽度自动右对齐。
        # 两侧同字档同线高 → 面板高度 0 变化（实测见 tests/capture_m13.py 输出）。
        foot = tk.Frame(self.body, **_frame_kw())
        foot.pack(fill="x", pady=(10, 0))
        self.status = tk.Label(foot, text="改动即时生效并保存", font=app.f_note,
                               **{**_tk_colors(), "fg": SOFT_TXT})
        self.status.pack(side="left")
        self.lbl_ver = tk.Label(foot, text=f"v{_version.APP_VERSION} · by Jerry Wu",
                                font=app.f_note, **{**_tk_colors(), "fg": FAINT})
        self.lbl_ver.pack(side="right")
        self.finish()

    # ================= 回调 =================

    def _say(self, msg: str, col: str = SOFT_TXT) -> None:
        self.status.configure(text=f"{time.strftime('%H:%M:%S')}  {msg}", fg=col)

    def _apply_providers(self) -> None:
        names = [n for n, v in self._pvars.items() if v.get()]
        self.app.set_enabled_providers(names)
        self._say(f"供应商已更新：{'、'.join(names) if names else '（全部停用）'}", OK)

    # ---- M6：绑定状态旁注 / 无凭据勾选弹面板 ----

    def _on_provider_toggle(self, name: str) -> None:
        on = bool(self._pvars[name].get())
        self._apply_providers()
        self._refresh_notes()
        if on and not _provider_bound(self.app, name):
            self._open_bind_panel(name)     # 无凭据的源勾选 → 自动弹其绑定面板

    def _open_bind_panel(self, name: str) -> None:
        if name == "bailian":
            self.app.open_credentials()
        else:
            self.app.open_key_panel(name)

    def _refresh_notes(self) -> None:
        for name, lbl in self._notes.items():
            bound = _provider_bound(self.app, name)
            lbl.configure(text="已绑定 · 点击配置" if bound else "未绑定 · 点击配置",
                          fg=OK if bound else ORANGE)

    # ---- M8：网络代理（config.network 节，改即存；仅境外两家） ----

    def _px_composed(self) -> tuple[str, str | None]:
        """(原始输入, 规范化 URL|None)：addr 自身可规范化则端口框忽略；
        仅当 addr+":"+port 组合可规范化时才采用组合（避免把非法输入拼得更怪）。"""
        addr = self.var_px_addr.get().strip()
        port = self.var_px_port.get().strip()
        norm = netconfig.normalize_proxy_url(addr)
        if norm is None and addr and port:
            cand = netconfig.normalize_proxy_url(f"{addr}:{port}")
            if cand:
                return f"{addr}:{port}", cand
        return addr, norm

    def _sync_probe_btn(self) -> None:
        """M8 视觉轮① + M12①：代理组整组可用性跟随「启用代理」勾选（单一同步函数）。

        启用=全可编辑：Entry normal/ENTRY_BG/INK，作用域勾选 normal，按钮 TRACK 底+描边+手型；
        禁用=整组弱化：Entry disabled（disabledbackground=PAPER 融纸、disabledforeground=FAINT、
        箭头光标），作用域勾选 disabled（文字经 disabledforeground 自动转 FAINT），按钮底色
        融回纸面/灰字/无描边/箭头（经典 tk.Button 无 disabledbackground，直接切 bg）。
        初建（构造尾调用）与每次 _save_net 都走本函数——两套状态永远一处定义。
        禁用期间 Entry/勾选不响应事件（Return/FocusOut/command 均不会触发），
        _save_net 无经禁用控件误触发的路径；唯一入口仍是「启用代理」勾选本身。"""
        on = bool(self.var_px_on.get())
        try:
            if on:
                for e in (self.ent_px_addr, self.ent_px_port):
                    e.configure(state="normal", bg=ENTRY_BG, fg=INK,
                                insertbackground=INK, cursor="xterm")
                for k in (self.chk_px_go, self.chk_px_cx):
                    k.configure(state="normal", cursor="hand2")
                self.btn_probe.configure(state="normal", bg=TRACK,
                                         highlightthickness=1, cursor="hand2")
            else:
                for e in (self.ent_px_addr, self.ent_px_port):
                    e.configure(state="disabled", bg=PAPER,
                                disabledbackground=PAPER,
                                disabledforeground=FAINT, cursor="arrow")
                for k in (self.chk_px_go, self.chk_px_cx):
                    k.configure(state="disabled", cursor="arrow")
                self.btn_probe.configure(state="disabled", bg=PAPER,
                                         highlightthickness=0, cursor="arrow")
        except tk.TclError:
            pass

    def _save_net(self, event=None) -> None:
        raw, norm = self._px_composed()
        targets = []
        if self.var_px_go.get():
            targets.append("opencode_go")
        if self.var_px_cx.get():
            targets.append("codex")              # M10：chatgpt.com 亦需海外出口
        sec = _section(self.app, "network")
        sec["proxy_enabled"] = bool(self.var_px_on.get())
        sec["proxy_url"] = raw                      # 原始用户输入（任务书 C.1），用时再规范化
        sec["proxy_targets"] = targets
        self.app.cfg["network"] = sec
        self.app.save_cfg()
        if raw and norm is None:
            self._say("地址格式未识别（已存原文）：建议 host:port，如 127.0.0.1:7890", ORANGE)
        else:
            self._say(f"网络代理已保存：{'启用 ' + norm if (sec['proxy_enabled'] and norm) else '直连'}", OK)
        if norm:                                    # 规范化标准形态回显
            a, p = _split_proxy_echo(norm)
            self.var_px_addr.set(a)
            self.var_px_port.set(p)
        self.lbl_net.configure(text="  不依赖凭据：拿到任意 HTTP 响应即通道正常", fg=FAINT)
        self._sync_probe_btn()                      # M8 视觉轮①：勾选/地址变更后同步按钮态
        self.app.refresh()                          # 下一轮即按新路由走

    def _probe_net(self) -> None:
        _raw, norm = self._px_composed()
        self.lbl_net.configure(text="  正在测试…" if norm else "  未填代理地址：测试直连",
                               fg=SOFT_TXT)
        self.after(80, lambda: self._probe_run(norm))

    def _probe_run(self, proxy: str | None) -> None:
        """测试连通三态（M8 缺陷修复）：通→绿；region 403→橙"换节点"；连不上→橙原语义。"""
        if not self.alive():
            return
        st, detail, blocked = netconfig.probe_channel(proxy, timeout=netconfig.PROBE_TIMEOUT)
        if st is None:
            hint = "（检查代理地址/软件）" if proxy else "（直连失败）"
            self.lbl_net.configure(text=f"  通道未建立：{detail[:80]}{hint}", fg=ORANGE)
        elif blocked:
            self.lbl_net.configure(
                text="  通道可达，但出口地区被 OpenAI 封锁：换海外节点（HTTP 403）",
                fg=ORANGE)
        else:
            word = "代理" if proxy else "直连"
            self.lbl_net.configure(text=f"  {word}通道正常（收到 HTTP {st}）", fg=OK)

    # ---- M15：更新（后台线程 + queue/after 回投；下载/替换仅用户明确动作） ----

    def _save_update_cfg(self, event=None) -> None:
        sec = _section(self.app, "update")
        sec["enabled"] = bool(self.var_up_auto.get())
        self.app.cfg["update"] = sec
        self.app.save_cfg()
        self._up_sync_repo_label()
        self._say("自动更新已" + ("开启" if sec["enabled"] else "关闭"))

    def _up_sync_repo_label(self) -> None:
        sec = _section(self.app, "update")
        slug = updater.parse_repo(sec.get("repo"))
        self.lbl_up_repo.configure(
            text=f"  源 GitHub Releases · {slug}" if slug else "  源未配置（update.repo）")

    def _up_refresh(self, manual: bool) -> None:
        # 定时路径（manual=False）只对接入 update 节的配置生效：真实 app 经
        # load_config 的 DEFAULTS 合并必有该节；旧测试 fixture 手写 CFG 不含
        # update 节 → 静默跳过（2f04147 定仓后防面板开测即打真实 GitHub）。
        if not manual and not isinstance(self.app.cfg.get("update"), dict):
            return
        sec = _section(self.app, "update")
        if not updater.parse_repo(sec.get("repo")):
            if manual:
                self.lbl_up.configure(
                    text="未配置更新源：请在 local\\config.json 的 update.repo 填入 owner/name",
                    fg=ORANGE)
            return
        if self._up_busy:
            return
        self._up_busy = True
        self.btn_up_check.configure(state="disabled")
        self.lbl_up.configure(text="正在检查更新…", fg=SOFT_TXT)
        self._up_hide_buttons()
        threading.Thread(target=self._up_worker_check, args=(manual,),
                         daemon=True).start()

    def _up_worker_check(self, manual: bool) -> None:
        try:
            res = updater.check(self.app.cfg, force=manual)
            self._up_q.put(("check", res, manual))
        except Exception as e:                        # noqa: BLE001 线程内兜底上抛
            self._up_q.put(("check", updater.CheckResult(
                err=f"检查异常：{type(e).__name__}"), manual))

    def _up_poll(self) -> None:
        if not self.alive():
            return
        try:
            while True:
                item = self._up_q.get_nowait()
                if item[0] == "check":
                    _, res, manual = item
                    self._up_show_check(res, manual)
                elif item[0] == "dl":
                    self._up_show_dl(item[1])
        except queue.Empty:
            pass
        self.after(150, self._up_poll)

    def _up_show_check(self, res, manual: bool) -> None:
        self._up_busy = False
        self.btn_up_check.configure(state="normal")
        if res.skipped:
            self.lbl_up.configure(text="6 小时内已检查过（定时检查被频控；可手动「检查更新」）",
                                  fg=SOFT_TXT)
            return                                    # 频控不视为错误
        if not res.ok:
            self.lbl_up.configure(text=f"检查失败：{res.err[:90]}", fg=ORANGE)
            self._save_last_check()
            return
        self._save_last_check()
        self._up_info = res.info
        cur_new = updater.is_newer(res.info.version, APP_VERSION)
        if not cur_new:
            self.lbl_up.configure(text=f"已是最新 v{APP_VERSION}（检查于 "
                                       f"{time.strftime('%H:%M')}）", fg=OK)
            self._up_hide_buttons()
            return
        notes = (res.info.notes or "").strip().replace("\r", " ").replace("\n", " ")
        head = f"发现新版本 v{res.info.version}"
        if notes:
            head += f" · {notes[:60]}{'…' if len(notes) > 60 else ''}"
        if manual:
            self.lbl_up.configure(text=head + "：可立即下载并更新（将退出当前程序）",
                                  fg=ORANGE)
            if res.info.url:
                self._up_show_download()
            else:
                self.lbl_up.configure(text=head + "：但该 release 无 TokenWidget.exe 资源",
                                      fg=ORANGE)
        else:
            self.lbl_up.configure(text=head + "（定时只读提示，不自动下载）", fg=ORANGE)

    def _save_last_check(self) -> None:
        sec = _section(self.app, "update")
        sec["last_check"] = int(time.time())
        self.app.cfg["update"] = sec
        self.app.save_cfg()

    def _up_hide_buttons(self) -> None:
        self._up_btnf.pack_forget()
        for b in (self.btn_up_dl, self.btn_up_go, self.btn_up_no):
            b.pack_forget()

    def _up_show_download(self) -> None:
        self._up_hide_buttons()
        self.btn_up_dl.pack(side="left")
        self._up_btnf.pack(anchor="w", pady=(4, 0))

    def _up_ask_confirm(self) -> None:
        """简版二次确认（_Card 内联语言，不弹系统对话框）。"""
        if self._up_info is None or not self._up_info.url:
            return
        self.btn_up_dl.pack_forget()
        self.btn_up_go.pack(side="left")
        self.btn_up_no.pack(side="left", padx=(8, 0))
        self.lbl_up.configure(text=f"将关闭并替换当前版本 → v{self._up_info.version}，"
                                   "凭据与设置不受影响。继续？", fg=ORANGE)

    def _up_confirm_cancel(self) -> None:
        if self._up_info is not None and self._up_info.url:
            self._up_show_download()                  # 取消确认 → 回退到「立即下载并更新」可重试
        else:
            self._up_hide_buttons()
        if self._up_info is not None:
            self.lbl_up.configure(text=f"发现新版本 v{self._up_info.version}"
                                       "（已取消本次下载）", fg=SOFT_TXT)

    def _up_apply(self) -> None:
        if self._up_info is None or not self._up_info.url or self._up_busy:
            return
        self._up_busy = True
        self._up_hide_buttons()
        self.lbl_up.configure(text="正在下载更新包…（完成后自动替换并重启）", fg=SOFT_TXT)
        threading.Thread(target=self._up_worker_apply, args=(self._up_info.url,),
                         daemon=True).start()

    def _up_worker_apply(self, url: str) -> None:
        try:
            path, err = updater.download_and_stage(url)
            if err:
                self._up_q.put(("dl", err))
                return
            err = updater.apply_update_and_restart(path)   # 成功=不返回（exit）
            self._up_q.put(("dl", err or "更新脚本已就位但未能退出"))
        except Exception as e:                            # noqa: BLE001
            self._up_q.put(("dl", f"更新异常：{type(e).__name__}"))

    def _up_show_dl(self, err: str) -> None:
        self._up_busy = False
        self.btn_up_check.configure(state="normal")
        if err == "":
            self.lbl_up.configure(text="✓ 更新脚本已接管，正在退出…", fg=OK)
        else:
            self.lbl_up.configure(text=f"更新未完成：{err[:90]}", fg=ORANGE)
            self._up_show_download()

    def _save_poll(self, event=None) -> None:
        try:
            v = int(float(self.var_poll.get()))
        except (TypeError, ValueError):
            v = 0
        if not 60 <= v <= 3600:
            self.var_poll.set(str(int(self.app.cfg.get("poll_seconds", 300))))
            self._say("轮询周期需为 60~3600 的整数秒", RED)
            return
        self.var_poll.set(str(v))
        self.app.set_poll_seconds(v)
        self._say(f"轮询周期 → {v}s", OK)

    def _save_poll_quiet(self) -> None:
        """Spinbox 箭头连点：只在数值合法时静默保存，不回写/打扰。"""
        try:
            v = int(float(self.var_poll.get()))
        except (TypeError, ValueError):
            return
        if 60 <= v <= 3600 and v != int(self.app.cfg.get("poll_seconds", 300)):
            self.app.set_poll_seconds(v)
            self._say(f"轮询周期 → {v}s", OK)

    def _save_thr(self, event=None) -> None:
        try:
            y = float(self.var_yellow.get())
            r = float(self.var_red.get())
        except (TypeError, ValueError):
            self._say("阈值需为数字（百分比，如 15 和 5）", RED)
            return
        if not (0 < r < y <= 99):
            self._say("需满足 0 < 红 < 黄 ≤ 99", RED)
            return
        self.app.set_thresholds(y, r)
        self._say(f"阈值 → 黄 {y:g}% / 红 {r:g}%", OK)

    def _apply_autostart(self) -> None:
        want = bool(self.var_auto.get())
        try:
            if want:
                autostart.enable()
                self._say(f"已开启自启（仅写入 Run\\{autostart.VALUE_NAME}）", OK)
            else:
                autostart.disable()
                self._say("已关闭自启（仅删除 Run\\token-widget 值）", OK)
        except OSError as e:
            self.var_auto.set(not want)
            self._say(f"注册表写入失败：{e}", RED)


# 阈值输入框文字色见文件头 YELLOW_FG / RED_FG


class CredentialPanel(_Card):
    """百炼 Cookie 续期面板：粘贴 → 加密保存（原子写）→ 立即验证刷新 → 反馈。

    - cookie_path 参数化：测试注入临时文件；默认 auth.BAILIAN_COOKIE_FILE（创建时取值）。
    - 保存成功后立即清空输入框；任何文本（含状态行/日志）不含 Cookie 内容。
    """

    def __init__(self, app, cookie_path: Path | str | None = None) -> None:
        super().__init__(app, "更新百炼登录凭据", geo_tag="CREDENTIAL")
        self.cookie_path = Path(cookie_path) if cookie_path else Path(auth.BAILIAN_COOKIE_FILE)
        self._saved_at = 0.0

        steps = ("1. 浏览器打开并登录 bailian.console.aliyun.com，进入 Token Plan 用量页\n"
                 "2. 按 F12 → 网络(Network) → 刷新页面 → 任选一条发往 bailian-cs 的请求\n"
                 "3. 复制 Request Headers 里完整的 Cookie 值，粘贴到下框 → 保存")
        tk.Label(self.body, text=steps, justify="left", font=app.f_small,
                 **_tk_colors()).pack(anchor="w")

        self.txt = tk.Text(self.body, height=6, width=58, wrap="char",
                           font=app.f_small, bg=ENTRY_BG, fg=SOFT_TXT,
                           insertbackground=INK, relief="flat",
                           highlightthickness=1, highlightbackground=PAPER_EDGE,
                           padx=8, pady=6)
        self.txt.pack(fill="x", pady=(8, 4))

        tk.Label(self.body,
                 text="粘贴内容只在本框短暂出现；保存后 DPAPI 加密落盘，界面与日志不再显示。",
                 font=app.f_note, **{**_tk_colors(), "fg": FAINT}).pack(anchor="w")

        btns = tk.Frame(self.body, **_frame_kw())
        btns.pack(anchor="w", pady=(10, 0))
        tk.Button(btns, text="保 存", font=app.f_small_b, cursor="hand2",
                  bg=INK, fg=PAPER, activebackground="#57503E", activeforeground=PAPER,
                  relief="flat", bd=0, padx=16, pady=4,
                  command=self._save).pack(side="left")
        # M3c⑦：取消键加 1px 浅描边（BADGE_EDGE），层级"次要但可点"，
        # 不与实底墨色的「保 存」拉平，也不至悬浮无锚点
        tk.Button(btns, text="取消", font=app.f_small, cursor="hand2",
                  bg=BADGE_BG, fg=SOFT_TXT, activebackground=BADGE_EDGE,
                  activeforeground=INK, relief="flat", bd=0, padx=16, pady=4,
                  highlightthickness=1, highlightbackground=BADGE_EDGE,
                  command=self.close_card).pack(side="left", padx=(8, 0))

        self.status = tk.Label(self.body, text="", font=app.f_small, wraplength=440,
                               justify="left", **{**_tk_colors(), "fg": SOFT_TXT})
        self.status.pack(anchor="w", pady=(8, 0))
        self.finish()

    # ================= 流程 =================

    def _say(self, msg: str, col: str = SOFT_TXT) -> None:
        self.status.configure(text=msg, fg=col)

    def _save(self) -> None:
        raw = "".join(self.txt.get("1.0", "end").split())   # 去空白/换行，Cookie 单串
        if not raw:
            self._say("还没有粘贴内容。", ORANGE)
            return
        if len(raw) < 40 or "=" not in raw:
            self._say("看起来不是完整 Cookie（太短或缺少 =）。请复制整串 Cookie。", RED)
            return
        try:
            auth.save_bailian_cookie(raw, self.cookie_path)
        except (OSError, ValueError) as e:
            self._say(f"保存失败：{e}", RED)                       # 异常文本不含 Cookie
            return
        self.txt.delete("1.0", "end")                              # 立即清屏，不留回显
        self._saved_at = time.time()
        self._say("已加密保存，正在验证…")
        self.app.refresh()
        self.after(1500, self._verify)

    def _verify(self) -> None:
        """等保存之后的第一轮真实结果：ok→成功并关；仍凭据错→留面板；其他→说明。"""
        if not self.alive():
            return
        fresh = float(self.app.meta.get("ts", 0) or 0) > self._saved_at
        u = next((x for x in self.app.usages if x.provider == "bailian"), None)
        if fresh and u is not None:
            if u.ok:
                self._say("✓ 验证成功，凭据已生效。", OK)
                self.after(900, self.close_card)
                return
            code = u.error_code or "ERROR"
            if code in CRED_ERRORS:
                self._say(f"保存成功，但验证仍提示凭据失效（{code}）。"
                          "请确认 Cookie 来自已登录的百炼控制台、且为整串未截断。", RED)
            else:
                self._say(f"保存成功。本轮拉取返回 {code}——非凭据问题，"
                          "浮窗会自动退避重试，可关闭本窗口观察。", ORANGE)
            return
        if time.time() - self._saved_at > 60:
            self._say("验证超时：拉取尚未回来。可关闭窗口，浮窗会自动重试。", ORANGE)
            return
        self.after(2000, self._verify)


class ProviderKeyPanel(_Card):
    """M6/M10 密钥绑定面板（复用保存即验证纪律；M11a 起仅 Go 与 Codex 两家）。

    - Go：自动检测结果行（仅尾 4 位）+ 手动粘贴 + 自动检测开关；
      Codex（实验性）：自动检测结果行（local\\ → 项目根/exe 同级 → ~/.codex 搜索序，仅尾 4 位）
      + 手动粘贴 access_token。
    - 保存 → auth.save_secret（DPAPI 原子写，默认落 local\\<name>.dpapi，测试重定向
      auth.LOCAL_DIR）→ 输入框即刻清空 → 调对应 source 一次（fetch_now）就地显示结果。
    - 任何状态文本/异常信息只含错误码与固定文案，绝不包含 key/token 值。
    """

    TITLES = {"opencode_go": "绑定 OpenCode Go key",
              "codex": "绑定 Codex（ChatGPT）token"}
    CODE_HINTS = {"KEY_INVALID": "密钥无效", "NO_SUBSCRIPTION": "此 key 无 Go 订阅",
                  "not_configured": "未绑定凭据", "RATE_LIMITED": "源限流",
                  "NETWORK": "网络异常", "PARSE_EMPTY": "响应无法解析"}

    def __init__(self, app, provider: str) -> None:
        if provider not in self.TITLES:
            raise ValueError(f"未知 provider：{provider}")
        self.provider = provider
        super().__init__(app, self.TITLES[provider], geo_tag="PROVIDER_KEY")
        if provider == "codex":
            self._build_codex()
        else:
            self._build_go()
        self.status = tk.Label(self.body, text="", font=app.f_small, wraplength=440,
                               justify="left", **{**_tk_colors(), "fg": SOFT_TXT})
        self.status.pack(anchor="w", pady=(8, 0))
        self.finish()

    # ================= 构建 =================

    def _say(self, msg: str, col: str = SOFT_TXT) -> None:
        self.status.configure(text=msg, fg=col)

    def _secret_entry(self, parent) -> tk.Entry:
        """密文回显输入框（show="*"）：key 只在此框短暂出现，保存后立即清空。"""
        e = tk.Entry(parent, width=40, font=self.app.f_small, show="*",
                     bg=ENTRY_BG, fg=SOFT_TXT, insertbackground=INK, relief="flat",
                     highlightthickness=1, highlightbackground=PAPER_EDGE)
        e.pack(side="left")
        return e

    def _save_button(self, btns) -> None:
        tk.Button(btns, text="保存并验证", font=self.app.f_small_b, cursor="hand2",
                  bg=INK, fg=PAPER, activebackground="#57503E", activeforeground=PAPER,
                  relief="flat", bd=0, padx=16, pady=4,
                  command=self._save).pack(side="left")
        tk.Button(btns, text="取消", font=self.app.f_small, cursor="hand2",
                  bg=BADGE_BG, fg=SOFT_TXT, activebackground=BADGE_EDGE,
                  activeforeground=INK, relief="flat", bd=0, padx=16, pady=4,
                  highlightthickness=1, highlightbackground=BADGE_EDGE,
                  command=self.close_card).pack(side="left", padx=(8, 0))

    def _build_go(self) -> None:
        app = self.app
        tk.Label(self.body, text=(
            "Go key 用于拉取 rolling(~5h)/周/月 窗口百分比（官方 usage API）。\n"
            "登录过 opencode 的机器可自动检测（auth.json 的 opencode-go 条目）；\n"
            "⚠️ Zen key 不通用（打此端点必 403），自动检测绝不会采用。"),
            justify="left", font=app.f_small, **_tk_colors()).pack(anchor="w")
        self.lbl_detect = tk.Label(self.body, text="", font=app.f_small, wraplength=440,
                                   justify="left", **{**_tk_colors(), "fg": SOFT_TXT})
        self.lbl_detect.pack(anchor="w", pady=(6, 0))
        go = _section(app, "opencode_go")
        self.var_auto = tk.BooleanVar(value=bool(go["auto_detect"]))
        tk.Checkbutton(self.body, text="使用自动检测（opencode auth.json）",
                       variable=self.var_auto, font=app.f_small, selectcolor=BADGE_BG,
                       cursor="hand2", command=self._save_go_cfg,
                       **_tk_colors()).pack(anchor="w", pady=(4, 0))
        rf = self.row("Go key")
        self.ent_key = self._secret_entry(rf)
        btns = tk.Frame(self.body, **_frame_kw())
        btns.pack(anchor="w", pady=(10, 0))
        self._save_button(btns)
        self._refresh_detect()

    def _build_codex(self) -> None:
        """M10 Codex（实验性）：检测结果行（尾 4 位）+ 手动粘贴 access_token + 保存即验证。"""
        app = self.app
        tk.Label(self.body, text=(
            "用 ChatGPT 订阅的 OAuth access_token 拉取 Codex 5h/周 窗口限额。\n"
            "⚠️ 实验性：非官方接口，可能随时失效；与 OpenAI 平台 key 完全不互通。\n"
            "自动读取（按序）：local\\auth.json → 项目根/exe 同级 auth.json → "
            "~\\.codex\\auth.json\n（Codex CLI 登录产物；均需 auth_mode=chatgpt；"
            "token 永不回显，仅显示尾 4 位）。"),
            justify="left", font=app.f_small, **_tk_colors()).pack(anchor="w")
        self.lbl_detect = tk.Label(self.body, text="", font=app.f_small, wraplength=440,
                                   justify="left", **{**_tk_colors(), "fg": SOFT_TXT})
        self.lbl_detect.pack(anchor="w", pady=(6, 0))
        rf = self.row("access_token")
        self.ent_key = self._secret_entry(rf)
        btns = tk.Frame(self.body, **_frame_kw())
        btns.pack(anchor="w", pady=(10, 0))
        self._save_button(btns)
        self._refresh_detect()

    # ================= config 节（改即存，wire spec §3.2） =================

    def _save_go_cfg(self, event=None) -> None:
        sec = _section(self.app, "opencode_go")
        sec["auto_detect"] = bool(self.var_auto.get())
        self.app.cfg["opencode_go"] = sec
        self.app.save_cfg()
        self._refresh_detect()

    def _detect_disp_path(self, p: Path) -> str:
        """检测来源展示路径：优先相对项目根（local\\…），再相对用户目录（~\\…），否则绝对。"""
        for base, pre in ((auth.LOCAL_DIR.parent, ""), (Path.home(), "~" + os.sep)):
            try:
                return pre + str(p.relative_to(base))
            except ValueError:
                continue
        return str(p)

    def _refresh_detect(self) -> None:
        if not self.alive():
            return
        if self.provider == "codex":
            # M10b：手动 secret > 自动搜索（local\ → 项目根/exe 同级 → ~/.codex）；仅尾4位
            if auth.has_secret("codex_access_token"):
                txt = "已绑定：手动粘贴的 access_token（DPAPI）"
            else:
                found = auth.find_codex_auth()
                if found:
                    k, src = found
                    txt = (f"已自动检测：{self._detect_disp_path(src)}"
                           f"（…{k[-4:]}）")
                else:
                    txt = ("自动检测：三候选均未找到——放置 auth.json 到 local\\ 或项目根，"
                           "或登录 Codex CLI（~\\.codex\\auth.json）；也可在下方粘贴 "
                           "access_token")
            self.lbl_detect.configure(text=txt)
            return
        if not self.var_auto.get():
            txt = "自动检测：已关闭（仅使用手动粘贴的 key）"
        else:
            k = auth.detect_go_key()
            txt = (f"自动检测：已找到 Go key（…{k[-4:]}）" if k
                   else "自动检测：未找到（先登录 opencode，或在下方粘贴 Go key）")
        self.lbl_detect.configure(text=txt)

    # ================= 保存 / 验证 =================

    def _save(self) -> None:
        if self.provider == "codex":
            self._save_codex()
        else:
            self._save_go()

    def _save_go(self) -> None:
        raw = self.ent_key.get().strip()
        if not raw:
            if self.var_auto.get() and auth.detect_go_key():
                self._say("未粘贴新 key，使用自动检测结果验证…")
                self.after(60, self._validate)
            else:
                self._say("还没有粘贴内容。", ORANGE)
            return
        if len(raw) < 8:
            self._say("Go key 看起来太短（不足 8 位），请复制完整 key。", RED)
            return
        try:
            auth.save_secret("opencode_go_key", raw)
        except (OSError, ValueError) as e:
            self._say(f"保存失败：{e}", RED)
            return
        self.ent_key.delete(0, "end")
        self._say("已加密保存，正在验证…")
        self.after(60, self._validate)

    def _save_codex(self) -> None:
        """M10：access_token（JWT）保存即验证；空输入但有自动检测结果时直接验证。"""
        raw = self.ent_key.get().strip()
        if not raw:
            if auth.find_codex_auth():
                self._say("未粘贴新 token，使用自动检测结果验证…")
                self.after(60, self._validate)
            else:
                self._say("还没有粘贴内容。", ORANGE)
            return
        if len(raw) < 16:
            self._say("access_token 看起来太短（不足 16 位），请复制完整 JWT。", RED)
            return
        try:
            auth.save_secret("codex_access_token", raw)
        except (OSError, ValueError) as e:
            self._say(f"保存失败：{e}", RED)               # 异常文本不含 token（auth 保证）
            return
        self.ent_key.delete(0, "end")                      # 即刻清空，不留回显
        self._say("已加密保存，正在验证…")
        self.after(60, self._validate)

    def _validate(self) -> None:
        """保存即验证：调对应 source 一次（fetch_now 绕缓存），结果就地显示、绝不回显 key。"""
        if not self.alive():
            return
        try:
            from .registry import SOURCES
            src = SOURCES.get(self.provider)
            if src is None:
                self._say(f"✗ 验证失败：源未注册（{self.provider}）", RED)
                return
            fn = getattr(src, "fetch_now", None)     # 新源绕缓存；旧源退化 fetch
            from typing import cast
            from .sources.base import Usage
            u = cast(Usage, fn() if callable(fn) else src.fetch())
        except Exception as e:                          # noqa: BLE001
            self._say(f"验证异常：{type(e).__name__}: {str(e)[:120]}", RED)
            return
        if u.ok:
            if u.unit == "usd" and u.used is not None:
                msg = f"✓ 验证成功：近30天已用 {fmt_value(u.used, 'usd')}"
                if u.remaining is not None:
                    msg += f" · 余额 {fmt_value(u.remaining, 'usd')}"
                if u.total is not None:
                    msg += f" · 预算 {fmt_value(u.total, 'usd')}"
            elif u.unit == "percent" and u.pct_used is not None:
                _w0 = u.windows[0] if u.windows else None
                lab = WIN_LABELS.get(_w0.label, _w0.label) if _w0 else "窗口"
                msg = f"✓ 验证成功：{lab} 窗口已用 {u.pct_used:.0%}"
            else:
                msg = "✓ 验证成功"
            self._say(msg, OK)
            self.app.refresh()                          # 浮窗下一轮即显示新数据
        else:
            code = u.error_code or "ERROR"
            hint = self.CODE_HINTS.get(code, "拉取失败")
            self._say(f"✗ 验证失败：{hint}（{code}）", ORANGE)
        self._refresh_notes()

    def _refresh_notes(self) -> None:
        """绑定状态变化同步回设置页旁注（面板开着才刷，避免 TclError）。"""
        s = getattr(self.app, "_settings", None)
        if s is not None:
            try:
                if s.alive():
                    s._refresh_notes()
            except tk.TclError:
                pass

