"""token-widget M2 便笺风桌面浮窗（tkinter，stdlib only）。

设计意图（PLAN §7-Q6 便笺风）：
- 奶油纸底 + 圆角（transparentcolor 色键抠角）+ 右下角卷边 + 顶部和纸胶带握把；
  斜向点状细纹模拟纸纤维，顶沿高光/底沿暗线做微立体。
- 单一 Canvas 绘制（tk 子窗口不能透明，避免圆角穿帮），数据变化整体重绘。
- 阈值着色：剩余 <15% 黄、<5% 红（config.low_yellow_pct / low_red_pct）。
- M23 套餐到期：百炼 C 行分项尾部追加「 · 套餐 MM-DD 到期」（plan_end 空=零占位；
  跨年显全日期；≤7 天 ORANGE、≤3 天含过期 RED、平时 SOFT_TXT；stale 旧值行
  日期照常但随灰 FAINT；宽不足截主文保后缀，兜不住则后缀整体不显——同「按周期计」
  降级律；tooltip 恒显完整日期+剩余天数）。仅百炼：其余 source plan_end 恒 None。
- 主行外的多余 windows（百炼 "5h"）自动副显，接口不返回即完全不占位
  （PLAN §7-Q5 推广为「按 windows 条数渲染」）。M24B 起 Go 不再走副显——升级
  多主条块（与 Codex M14 同语法，5h/日/周/月 全量出条，从上到下）。
- M7-a 加油包细条：主条下方第二根细条（BADGE 中性色、无阈值语义），仅当有 ACTIVE 包时出现、
  否则零占位；总量由「total − 推导周期量」得出，明细进 tooltip。
- M7-b 刷新图标：标题行状态文字左侧手绘 ↻（Canvas 弧 + 切线箭头，非系统符号），点击=「立即刷新」
  同一路径；悬停底色加深一档；拉取期间 60°/步旋转（after 循环、主线程、回包或 30s 超时自停）。
  M12④ 起笔画改 4× 超采样 PhotoImage 光栅（Tk 无抗锯齿的替代；几何/热区/旋转时序语义不变）。
  M24A 层序定案：图标族（rotbg+图）恒压在纸纹之上、文字之下——items 后于纹理创建，
  初始渲染与旋转帧/hover 同走 _rot_raise 单一收口，任何时刻所见层序一致。
- M9 屏幕边缘自吸附（行为特性，无开关）：拖拽释放时窗口任一边距所在显示器工作区对应边
  ≤ SNAP_PX（28 逻辑px，随 DPI 缩放）→ 贴齐该边（与工作区边缘 0 间距；顶边贴工作区顶，
  任务栏避让由 work_area 天然处理）；横纵独立判定，可同吸成贴角。目标屏 = 窗口面积占比
  最大的显示器（ctypes EnumDisplayMonitors 在 UI 层扩展，state.py 不动）。释放后 ~90ms×3 帧
  ease-out 滑到贴边位，动画期间新拖拽立即接管；吸附终值即写 state.json。非拖拽的点击释放
  不触发；首启自动摆位与 --print-geometry 语义不变（后者输出吸附后最终位）。
- M11b Codex 行双条：两个进度条——主条=最紧已知窗（B 行文案/倒计时/阈值色全套），
  副细条=另一已知窗（与百炼加油包同槽语法：5.4px 条、ROW_ADDON=14 增量、左 label
  右「已用 x% · 倒计时」图文同向）；条填充=已用向，阈值色各窗独立判定；
  other:N 未知窗行内不显（tooltip 仍全列）；重置券角标「券×N」（note 解析）画在
  A 行徽章位、零高度、无券完全不占位，hover=说明性 tooltip（无点击动作）。
  （M14 起副细条已升等尺寸主条，下方 M14 条目为准。）
- M14 Codex 双主条等尺寸：5h/周各自「文字行（短名·已用% ｜ 倒计时粗体）+ 9px 主条」
  两信息块完全对称；组内文→条 7px（与百炼 B 行同律），组间行距 CODEX_GAP=12px
  （条-条实距 19px；1.7× 组内，Gestalt 亲近性分组清晰）；整组收在 ROW_FULL=100 内
  （原细条方案 114 → 100，第二条借用旧细条+C 行空档，行高零增）。
- M11d 固定槽与去「窗」：主条恒=5h、副细条恒=周（与松紧解耦，缺位递补：无 5h 周升
  主条、无周仅主条）；5h 短名去「窗」→「5h · 已用 x%」；
  大数字口径随主条窗剩余占比（所见即所得），黄/红仍各窗独立判（副条自着色兜紧迫度）。
- M24 用户实测四修：A ↻ 图标族层序恒定居中（纸纹之上、文字之下；纹理后创建 +
  _rot_raise 单一收口，初始渲染与旋转/hover 同路）；B Go 行升多主条（source 侧
  86400→「日」映射与 5h→日→周→月固定序，有几窗画几条；条行短名一律无「窗」字，
  codex 残留「周窗」同步改「周」；大数字=剩余占比·最紧窗口径；行高第 3 窗起
  每窗 +GO_BAR_PITCH=28，与 codex 高度账同族）；C 条内高光线改绝对像素阈
  （填充宽 ≥BAR_HI_MIN_PX=24 逻辑 px 才画，替代 M7b⑤「<15% 轨宽」——双主条
  并排观感一致：小窗两条都无、大窗两条都有）。
- M11c 第 5 轮视觉打磨：①codex 窗短名「周窗」（去「周 窗口」拼接空格；5h 由 M11d 去「窗」），
  副细条尾注整句统一 f_note 浅灰常规（原 f_tiny 下 CJK「后重置」视觉比数字重一档）；②券×N
  字重与 PLUS 同档（SOFT 灰褐，角标是配角）；③细条方向语义定案：主条一律**已用向**；
  细条一律**图文同向、右文案自带方向锚字**——codex 副细条右「已用 x% · …」（已用向），
  加油包细条右「剩 X / Y」（剩余向，des-2 定案）——两根细条方向相反不再靠猜，锚字为准。
- M6 单位语义：unit=="usd" 大数字=剩余/余额（$ 两位小数），副行「近30天已用 / 预算|余额」；
  unit=="percent" 大数字=剩余占比（分母 100），rolling 显示文案「5h」。
- M9b usd 无余额态：admin key 采得到已用但无余额视图（remaining=None 且 used 有真实值）→
  大数字=近30天已用（$0.00 只能来自真实 used=0，None 绝不渲染成假值）、单位小字改「近30天已用」、
  副行不再重复已用，改分母指引「未设预算 · 绑定普通 key 可看余额」；percent/credits 型不动。
- 失败降级：有最后成功值 → 灰显 +「旧数据」标记；LOGIN_EXPIRED/NO_CREDENTIAL/
  KEY_INVALID/NO_SUBSCRIPTION → 橙色凭据档（bailian 走 Cookie 面板、OpenAI/Go 走密钥面板）；
  RATE_LIMITED/NETWORK 等走灰 stale 档；绝不渲染空值假象。凭据（Cookie/key）永不进入 UI。
- 数据契约只消费 src.sources.base.Usage/Window，不感知供应商协议。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import queue
import re
import threading
import time
import tkinter as tk
from collections.abc import Callable
from datetime import datetime, timezone
from tkinter import font as tkfont

from . import state as state_mod
from . import updater
from .sources.base import Usage, Window
from .version import APP_VERSION

# ---------- 便笺视觉常量（逻辑 px / 颜色；坐标 ×DPI 缩放，字号用负像素） ----------
KEY = "#fe01fe"          # 透明色键：圆角之外透出桌面
PAPER = "#FBF3DF"        # 奶油纸底
PAPER_TX = "#EEDFB8"     # 纸纹（比纸底深一档）
PAPER_EDGE = "#D9C79E"   # 纸边描线
PAPER_HI = "#FFFCEF"     # 顶沿高光
TAPE = "#EFE4BF"         # 和纸胶带
TAPE_EDGE = "#DCCB9B"
TAPE_LINE = "#E3D2A4"
FOLD = "#EBDBAD"         # 卷边背面
INK = "#413928"          # 墨色正文
SOFT = "#8B7F65"         # 次要文字（徽章/状态）
SOFT_TXT = "#6E655A"     # B/C 行小字（M2 审查：提亮一档保证 100% 缩放锐利）
FAINT = "#B3A582"        # 弱化/时间戳
STALE = "#BCAF92"        # 旧数据图形灰
OK = "#3BC371"           # 正常进度绿（M12③ 用户点名亮档；原 #5D8A5E）
YELLOW = "#FEC211"       # 剩余 <15%（M12③；条内无文字，亮黄无对比度问题——文案都在纸底上）
RED = "#EF0000"          # 剩余 <5%（M12③；原 #B34B3C）
ORANGE = "#D9782E"       # 需重贴凭据
TRACK = "#E3D3A9"        # 进度条底槽（M2 审查：加深，轨道感明确）
TRACK_EDGE = "#CFB98A"
BADGE_BG = "#F3E9CD"
BADGE_EDGE = "#DAC8A0"
ADDON_FILL = "#C2A878"     # M7b③：加油包细条填充（略深卡其；与主条空轨 #E3D3A9 拉开 ΔRGB≈(33,43,49)）
BAR_HI = "#FFFBEB"
BAR_HI_MIN_PX = 24         # M24C：内高光线绝对像素阈（填充宽 ≥ 此逻辑 px 才画）
MENU_BG = "#FBF6E7"
MENU_HL = "#EFE1BE"
TIP_BG = "#3B3527"
TIP_FG = "#F6EED8"
HEAD_INK = INK           # M7-b：刷新图标笔画色（与标题墨色同源，笔画不引新色）

W_IN = 330               # 逻辑宽（300~340 要求内）
M_IN = 18                # 左右留白
R_IN = 16                # 圆角半径
FOLD_IN = 22             # 卷边三角直角边
HEAD_H = 52              # 头部占位高
ROW_FULL = 100           # 标准行高（7d + 数值 + addon/更新时间）
ROW_5H = 16              # 5h 副行增量
ROW_ADDON = 14           # M7-a 加油包细条增量（条 5.4px ≈ 主条 9px 的 60%）
ROW_CRED = 16            # 凭据警示行增量
ROW_ERR = 58             # 纯错误行高
CODEX_TEXT_Y = 53        # M14 codex 块1 文字行基线位（沿用旧 B 行 53/60 语法）
CODEX_TXT_BAR = 7        # 组内：文字行中心 → 条顶（与百炼 B 行→条同律）
CODEX_GAP = 12           # M14 组间距：条1底 → 块2文字行中心（条-条实距 = 12+7 = 19px）

NAMES = {"bailian": "百炼", "opencode_go": "OpenCode Go",
         "codex": "Codex"}
SPECS = {"lite": "Lite", "standard": "Standard", "pro": "Pro", "max": "Max"}
# M6（wire spec §3.4）：KEY_INVALID/NO_SUBSCRIPTION 归橙色凭据档；RATE_LIMITED/NETWORK 走灰 stale。
# fix-5 定案：REGION_BLOCKED 升橙档——语义是环境态（出口地区封锁）而非凭据，但面板/CLI 文案
# 已含「切换海外节点」指引，主窗橙档更醒目；scheduler 退避行为不变（分类在 sources 层，此处仅配色）。
CRED_ERRORS = {"LOGIN_EXPIRED", "NO_CREDENTIAL", "KEY_INVALID", "NO_SUBSCRIPTION",
               "REGION_BLOCKED"}

# ---------- M9 屏幕边缘自吸附（逻辑 px；物理判定处 ×S 随 DPI 缩放） ----------
SNAP_PX = 28           # 吸附触发距离：释放位与工作区边距 ≤ 此值 → 贴齐该边（0 间距）
SNAP_FRAMES = 3        # 滑动帧数（ease-out 二次，总时长 ≈ SNAP_FRAMES*SNAP_STEP_MS ≈ 90ms）
SNAP_STEP_MS = 30      # 帧间隔 ms
# 窗口 label 的显示文案（Go API 变体 rolling → 显示语义 "5h"，spec §2.2 风险⑥；
# M24C 起去波浪号，与 Codex 短名统一）。
# M24B 起 Go source 直接下发显示 label（5h/日/周/月），此表保留旧字段名兜底
# （历史 fixture / 缓存数据仍经此归一）。
WIN_LABELS = {"rolling": "5h", "daily": "日", "weekly": "周", "monthly": "月"}


def win_label(label: str) -> str:
    """原始 label → 显示 label（未知值透传）。"""
    return WIN_LABELS.get(label, label)


def spec_display(u: Usage) -> str:
    """spec 徽章文案：百炼档位走 SPECS 映射；Codex（M10）把 plan_type 大写化。"""
    if not u.spec:
        return ""
    if u.provider == "codex":
        return str(u.spec).upper().replace("_", " ")
    return SPECS.get(u.spec, str(u.spec))


def _tip_credits(u: Usage) -> str | None:
    """实验性 codex：addon_remaining 复用位承载积分余额（USD）→ tooltip 单列一行。"""
    if u.provider == "codex" and u.addon_remaining is not None:
        return f"积分余额 {fmt_value(u.addon_remaining, 'usd')}（实验性源）"
    return None


# ---------- M11b Codex 行双条（主条=最紧已知窗 + 副细条；纯函数可单测） ----------

CODEX_KNOWN_LABELS = ("5h", "周")       # sources/codex.WINDOW_LABELS 的两个知名值


def codex_bars(u: Usage) -> tuple[Window | None, Window | None]:
    """codex 行取条：(主条窗, 副细条窗)。M11d① **固定槽位**——5h 恒上（主条）、周恒下（细条）。

    不再按"最紧窗"选位（source 的 windows 排序仅供其自身口径，行内布局与松紧解耦，
    位置成为稳定预期：用户永远在上槽看 5h、下槽看周）。缺 5h 时周升主条（单边场景），
    缺周则仅主条；other:N 行内不显（tooltip 仍全列）。
    全为未知窗（异常套餐）→ (None, None)：调用方回落通用渲染，不丢数据。"""
    if u.provider != "codex":
        return None, None
    w5 = next((w for w in u.windows if w.label == "5h"), None)
    wk = next((w for w in u.windows if w.label == "周"), None)
    main = w5 if w5 is not None else wk          # 缺 5h → 周升主条
    sec = wk if w5 is not None else None         # 周作副条仅当 5h 占了主条
    if main is None:
        return None, None
    return main, sec


# ---------- M24B Go 行多主条（与 Codex M14 同语法；纯函数可单测） ----------

GO_BAR_PITCH = CODEX_TXT_BAR + 9 + CODEX_GAP    # 28：块行距（文字→条7 + 条9 + 组间12）


def go_bars(u: Usage) -> list[Window]:
    """Go 行取条：windows 全量按固定序 5h→日→周→月（other/未知尾置）出多主条。

    provider 非 Go 或无 windows → []（调用方回落通用渲染，数据不丢）。
    source 已在采集层排好序，这里二次排序只是对旧数据/手写 fixture 的归一保险。"""
    if u.provider != "opencode_go" or not u.windows:
        return []
    order = {lab: k for k, lab in enumerate(("5h", "日", "周", "月"))}
    return sorted(u.windows, key=lambda w: order.get(win_label(w.label), len(order)))


def go_tightest_pct(bars: list[Window]) -> float | None:
    """大数字口径（M24B）：最紧窗的已用 pct（=各窗 pct 最大者）；全未知 → None。"""
    pcts = [w.pct_used for w in bars if w.pct_used is not None]
    return max(pcts) if pcts else None


def codex_ticket_count(u: Usage) -> int | None:
    """重置券角标数：note「窗口重置券：可用 N」→ N；无 note/无数字/非 codex → None（不占位）。

    宽松解析（取首个「可用 <数字>」）；解析失败宁可不显，绝不错显。"""
    if u.provider != "codex" or not u.note:
        return None
    m = re.search(r"可用\s*(\d+)", u.note)
    return int(m.group(1)) if m else None


def codex_win_caption(label: str) -> str:
    """M11c①/M11d②/M24B 条行窗短名：一律**无「窗」字**——「周窗」→「周」，
    5h/日 原样（M24B 把 codex 最后残留的「周窗」也去了；Go 多主条同用本函数）。

    仅多主条支路（codex/Go）使用；通用行（百炼）的「{label} 窗口 · 已用」拼接不动。"""
    lab = win_label(label)
    return lab[:-1] if lab.endswith("窗") and len(lab) > 1 else lab


# ---------- 纯格式化函数（渲染层之外可单测） ----------

def _local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def fmt_value(v: float | None, unit: str = "credits") -> str:
    """千分位；usd 两位小数；None → 「—」。"""
    if v is None:
        return "—"
    return f"${v:,.2f}" if unit == "usd" else f"{v:,.0f}"


def fmt_countdown(dt: datetime | None) -> str:
    """"8h02m 后重置"；≥1 天 "1d05h 后重置"；<1h "47m 后重置"；过期 →「即将重置」。"""
    a = _local(dt)
    if a is None:
        return "重置时间未知"
    secs = int((a - datetime.now().astimezone()).total_seconds())
    if secs <= 0:
        return "即将重置"
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d >= 1:
        return f"{d}d{h:02d}h 后重置"
    if h >= 1:
        return f"{h}h{m:02d}m 后重置"
    return f"{m}m 后重置"


def fmt_clock(dt: datetime | None) -> str:
    a = _local(dt)
    return "—" if a is None else a.strftime("%H:%M:%S")


def addon_split(u: Usage) -> tuple[int, int] | None:
    """周期/加油包剩余的唯一取数源（floor 先取整，大数字/底行/细条/tooltip 四处复用）。

    M7b 必修①：此前细条走 fmt_value(四舍五入) 而 breakdown 走 floor，出现
    1,509 vs 1,508 的分歧。返回 (wk_floor, ad_floor)；不可算（字段缺/负差）→ None。"""
    if u.remaining is None or u.addon_remaining is None:
        return None
    if not (u.remaining >= u.addon_remaining >= 0):
        return None
    return math.floor(u.remaining - u.addon_remaining), math.floor(u.addon_remaining)


def usd_used_mode(u: Usage) -> bool:
    """M9b：usd 且余额未知、但已用是真实值 → 大数字改显「近30天已用」。

    真实场景：Admin key 绑成功、org/costs 200，但无预算无 grants →
    Usage(unit=usd, used=0, remaining=None, total=None)。此前大数字显「—」
    易被读成故障；显真实 used 让「采集正常但余额未知」一眼可读。
    红线：None 绝不走本分支渲染成 $0.00 假值——$0.00 只能来自真实 used=0。"""
    return u.unit == "usd" and u.remaining is None and u.used is not None


def breakdown_display(u: Usage) -> tuple[str, str | None]:
    """M2 审查①：数值自洽 —— 分项各自 floor，大数字 = Σ分项（"周期+加油包=剩余"肉眼成立）。

    返回 (大数字文本, 分项文本或 None)。
    """
    if u.unit == "usd":                      # M6：$ 语义 大数字=剩余/余额；副行=已用+分母来源
        if usd_used_mode(u):                 # M9b：无余额视图 → 大数字=真实已用，副行改分母指引
            big = fmt_value(u.used, u.unit)  # used 为真实值（0 也是真话，非占位假值）
            left = (f"预算 {fmt_value(u.total, u.unit)}" if u.total is not None
                    else "未设预算 · 绑定普通 key 可看余额")
            return big, left
        big = fmt_value(u.remaining, u.unit)
        if u.used is not None:
            left = (f"近30天已用 {fmt_value(u.used, u.unit)} / 预算 {fmt_value(u.total, u.unit)}"
                    if u.total is not None
                    else f"近30天已用 {fmt_value(u.used, u.unit)} / 余额 {fmt_value(u.remaining, u.unit)}")
        else:
            left = None
        return big, left
    if u.remaining is None:
        big = f"{(1 - u.pct_used) * 100:.0f}%" if u.pct_used is not None else "—"
        return big, None
    split = addon_split(u)
    if split is not None:                    # 含加油包：大数字 = 周期项 + 加油包项（floor 同源）
        wk, ad = split
        big = f"{wk + ad:,}"
        left = f"剩余 {wk:,}（周期） ＋ 加油包 {ad:,}"
        if u.total is not None:
            left += f" / 总 {math.floor(u.total):,}"
        return big, left
    big = f"{math.floor(u.remaining):,}"
    left = (f"剩余 {big} / 总 {math.floor(u.total):,}" if u.total is not None
            else f"剩余 {big}")
    return big, left


# ---------- M23：套餐到期提示（C 行分项尾部后缀；仅百炼——其余 source plan_end 恒 None） ----------

PLAN_WARN_DAYS = 7        # 距到期 ≤7 自然日 → 整段日期文字转橙
PLAN_URGENT_DAYS = 3      # ≤3 自然日（含已过期）→ 转红


def plan_end_display(u: Usage, now: datetime | None = None) -> tuple[str, str] | None:
    """返回 (后缀文本, 文字色) 或 None（plan_end=None → 零占位，行布局不变）。

    文本 = " · 套餐 09-28 到期"（与今天同年，MM-DD 无歧义省年份）；跨年显全
    " · 套餐 2027-01-05 到期"。色档按**本地自然日**差（负=已过期按最紧迫）：
    ≤PLAN_URGENT_DAYS → RED、≤PLAN_WARN_DAYS → ORANGE、其余 SOFT_TXT（与该
    C 行同档）。stale 降灰由渲染层覆写（旧值随灰，紧急档也不例外，日期照常显示）。"""
    pe = _local(u.plan_end)
    if pe is None:
        return None
    ref = _local(now) or datetime.now().astimezone()
    days = (pe.date() - ref.date()).days
    d_txt = f"{pe:%m-%d}" if pe.year == ref.year else f"{pe:%Y-%m-%d}"
    col = RED if days <= PLAN_URGENT_DAYS else (ORANGE if days <= PLAN_WARN_DAYS
                                                else SOFT_TXT)
    return f" · 套餐 {d_txt} 到期", col


def plan_end_split(left: str, tail: str, measure, avail: float,
                   ellipsis: str = "…") -> tuple[str, str | None]:
    """C 行宽度守卫（纯函数）：主文+后缀放得下→原样；放不下→**截主文保后缀**
    （到期是用户价值增量，截断该截断的）；连截断位都不够→后缀不显（返回
    (原文, None)，与「（按周期计）」守卫同律降级）。measure=callable(str)->px。"""
    if not tail or measure(left) + measure(tail) <= avail:
        return left, tail if tail else None
    budget = avail - measure(tail)
    base = left
    while base and measure(base + ellipsis) > budget:
        base = base[:-1]
    if base:
        return base + ellipsis, tail
    return left, None


def addon_bar_state(u: Usage) -> tuple[bool, float | None, int]:
    """M7-a：加油包细条可见性与推导总量。返回 (显示, addon_total 或 None, 剩余floor)。

    数据只有 Usage.addon_remaining（sources 层已把多包 Σ 合并）；总量按
    「addon_total = total − period_total」推导：sources 保证 used = weekly×pct
    （bailian.py 剩余公式）→ weekly = used/pct。pct 过小/字段缺失时不推导
    （返回 None，文本退化为「剩 X」，进度条空走轨）。
    M7b①：剩余显示值一律取 addon_split 的 floor —— 与大数字/底行分项同源，
    禁止在此处再走四舍五入（曾致细条 1,509 vs 底行 1,508）。
    显示条件：addon_remaining>0，或推导出总量 ≥1（ACTIVE 包用罄仍显示，
    即「有 ACTIVE 包」）。sources 不可读时 addon_remaining=None → 永不显示。
    M10：codex 复用 addon_remaining 承载「积分余额」（非加油包池）→ 不画加油包细条，
    积分改在 tooltip 单列（_tip_credits）。
    """
    if u.provider == "codex":
        return False, None, 0
    if u.addon_remaining is None:
        return False, None, 0
    split = addon_split(u)
    ad_floor = split[1] if split is not None else math.floor(u.addon_remaining)
    at: float | None = None
    if (u.total is not None and u.used is not None
            and u.pct_used is not None and u.pct_used >= 0.02):
        weekly = u.used / u.pct_used
        if u.total > weekly + 1.0:
            at = u.total - weekly
    show = u.addon_remaining > 0 or bool(at)
    return show, at, ad_floor


def work_area() -> tuple[int, int, int, int]:
    """Windows 主屏工作区（物理 px）left, top, right, bottom；失败退 1920×1080。"""
    try:
        r = wt.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
        if r.right > r.left and r.bottom > r.top:
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return 0, 0, 1920, 1080


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def work_areas() -> list[tuple[int, int, int, int]]:
    """全部显示器工作区（物理 px）列表；M9 多屏吸附取数用。

    主屏版 work_area()/state.py 均不动：这里用 EnumDisplayMonitors 在 UI 层
    自行扩展；回调失败/异常退 [work_area()]（单主屏，行为等同旧版）。
    """
    areas: list[tuple[int, int, int, int]] = []
    try:
        proto = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC,
                                   ctypes.POINTER(wt.RECT), wt.LONG)

        def _cb(hmon, hdc, lprc, data):
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(mi)
            if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                rw = mi.rcWork
                if rw.right > rw.left and rw.bottom > rw.top:
                    areas.append((rw.left, rw.top, rw.right, rw.bottom))
            return True

        keep = proto(_cb)     # 调用期间保持原型存活（防 GC）
        ctypes.windll.user32.EnumDisplayMonitors(0, 0, keep, 0)
    except Exception:
        pass
    return areas or [work_area()]


def snap_target(pos: tuple[int, int], size: tuple[int, int],
                areas: list[tuple[int, int, int, int]],
                threshold: float) -> tuple[int, int] | None:
    """M9 纯判定：拖拽释放位 → 吸附终值；None = 不吸（原位）。

    - 目标工作区 = 窗口重叠面积最大的那块屏（多屏；断开/完全出屏时面积同为 0，
      取列首屏做软着陆，终值必然拉回该屏边缘）。
    - 横纵独立判定，可同吸附成贴角；贴齐后与工作区边缘保持 0 间距。
    - 边距 ≤ threshold 含负值（窗口越过屏边 → 拉回贴齐，同样算吸附）。
    - 双边同时达标（工作区比窗口还小等极端情形）取 |边距| 更小的一边。
    - 已贴齐（终值 == 原位）返回 None：不白启动画。
    """
    x, y = int(pos[0]), int(pos[1])
    w, h = int(size[0]), int(size[1])
    best = None
    best_a = -1
    for (l, t, r, b) in areas:
        ix = max(0, min(x + w, r) - max(x, l))
        iy = max(0, min(y + h, b) - max(y, t))
        if ix * iy > best_a:
            best_a, best = ix * iy, (l, t, r, b)
    if best is None:
        return None
    l, t, r, b = best
    dl, dt = x - l, y - t                  # 距左/上：正=屏内
    dr, db = r - (x + w), b - (y + h)      # 距右/下：正=屏内

    def pick(d1: float, v1: int, d2: float, v2: int) -> int | None:
        o1, o2 = d1 <= threshold, d2 <= threshold
        if o1 and o2:
            return v1 if abs(d1) <= abs(d2) else v2
        return v1 if o1 else (v2 if o2 else None)

    nx = pick(dl, l, dr, r - w)
    ny = pick(dt, t, db, b - h)
    fx = x if nx is None else nx
    fy = y if ny is None else ny
    return None if (fx, fy) == (x, y) else (fx, fy)


# ---------- M12④ ↻ 手绘图形的解析式覆盖判定与超采样生成（NoteApp._rot_images 用） ----------

def _hex_rgb(spec: str) -> tuple[int, int, int]:
    return (int(spec[1:3], 16), int(spec[3:5], 16), int(spec[5:7], 16))


def _ring_cov(dx: float, dy: float, rr: float, hw: float, a0: float) -> bool:
    """子点是否落在圆环扇段笔画内（画布坐标 y 向下；角度系与 create_arc 同：
    0=东、逆时针增、canvas 点 (cos a, −sin a)），扫过 [a0, a0+300°]。"""
    if abs(math.hypot(dx, dy) - rr) > hw:
        return False
    th = math.degrees(math.atan2(-dy, dx)) % 360.0
    return (th - a0) % 360.0 <= 300.0


def _in_tri(x: float, y: float, v1: tuple[float, float], v2: tuple[float, float],
            v3: tuple[float, float]) -> bool:
    """点 in 三角形（叉积同侧法，含边界）。"""
    def cr(ax, ay, bx, by):
        return ax * by - ay * bx
    d1 = cr(v2[0] - v1[0], v2[1] - v1[1], x - v1[0], y - v1[1])
    d2 = cr(v3[0] - v2[0], v3[1] - v2[1], x - v2[0], y - v2[1])
    d3 = cr(v1[0] - v3[0], v1[1] - v3[1], x - v3[0], y - v3[1])
    return (d1 <= 0 and d2 <= 0 and d3 <= 0) or (d1 >= 0 and d2 >= 0 and d3 >= 0)


def _gen_rot_icons(S: float, master=None) -> dict[int, tk.PhotoImage]:
    """6 档旋转（0..300 步 60）4× 超采样 PhotoImage；几何参数=原 create_arc 手绘。

    rr=6.6·S 弧半径、lw=max(1, round(1.6·S)) 线宽、箭头切向 4.6·S/径向 0.6 系数——
    与旧矢量版逐一同参，仅抗锯齿方式不同。返回 {rot: PhotoImage}。
    """
    rr, s = 6.6 * S, 4.6 * S
    lw = max(1, round(S * 1.6))
    hw = lw / 2.0
    half = int(math.ceil(math.hypot(rr, s) + hw + 0.5))     # 紧 bbox：弧带/箭尖最远点外推 0.5px
    W = 2 * half + 1
    ctr = half
    p_r, p_g, p_b = _hex_rgb(PAPER)
    i_r, i_g, i_b = _hex_rgb(HEAD_INK)
    ss, n_sub = NoteApp._SS, NoteApp._SS * NoteApp._SS
    sub = [(k + 0.5) / ss for k in range(ss)]               # 子点偏移（格中心）
    out: dict[int, tk.PhotoImage] = {}
    for rot in range(0, 360, 60):
        a0 = (70 + rot) % 360
        a = math.radians(a0)
        ca, sa = math.cos(a), math.sin(a)
        p0 = (ctr + rr * ca, ctr - rr * sa)                 # 弧口端点
        v1 = (p0[0] + sa * s, p0[1] + ca * s)               # 切线方向·朝缺口（原式）
        v2 = (p0[0] + ca * s * 0.6, p0[1] - sa * s * 0.6)   # 径向两侧（原式）
        v3 = (p0[0] - ca * s * 0.6, p0[1] + sa * s * 0.6)
        img = tk.PhotoImage(width=W, height=W, master=master)
        rows = []
        for py in range(W):
            line = []
            for px in range(W):
                hit = 0
                for sy in sub:
                    yy = py + sy
                    dy = yy - ctr
                    for sx in sub:
                        xx = px + sx
                        dx = xx - ctr
                        if _ring_cov(dx, dy, rr, hw, a0) or _in_tri(xx, yy, v1, v2, v3):
                            hit += 1
                f = hit / n_sub
                if f == 0.0:
                    line.append(f"#{p_r:02x}{p_g:02x}{p_b:02x}")
                elif f == 1.0:
                    line.append(f"#{i_r:02x}{i_g:02x}{i_b:02x}")
                else:
                    line.append("#%02x%02x%02x" % (
                        int(p_r + (i_r - p_r) * f + 0.5),
                        int(p_g + (i_g - p_g) * f + 0.5),
                        int(p_b + (i_b - p_b) * f + 0.5)))
            rows.append("{" + " ".join(line) + "}")
        # Tk put：行=嵌套 list（{c c …}），一次整幅写入——空格分隔的扁平串会被当作
        # "每行一色"并整框平铺首色（实测踩坑），必须带花括号分行。
        img.put(" ".join(rows), to=(0, 0, W, W))
        out[rot] = img
    return out


class NoteApp:
    """便笺浮窗控制器：渲染 / 拖拽 / 右键菜单 / tooltip / 调度事件消费 / 位置记忆。"""

    def __init__(self, root: tk.Tk, cfg: dict, scheduler, state: dict | None = None,
                 verbose: bool = False, print_geometry: bool = False) -> None:
        self.root = root
        self.cfg = cfg
        self.sched = scheduler
        self.init_state = state or {}
        self.verbose = verbose
        self._print_geo = print_geometry
        self._quitting = False

        self.low_yellow = float(cfg.get("low_yellow_pct", 0.15))
        self.low_red = float(cfg.get("low_red_pct", 0.05))

        # ---- 窗口：无边框 + 透明色键抠圆角 + 置顶 ----
        root.overrideredirect(True)
        root.withdraw()
        root.title("token-widget")
        try:
            root.attributes("-transparentcolor", KEY)
            self._keyed = True
        except tk.TclError:
            self._keyed = False
        saved_top = self.init_state.get("always_on_top")
        self.topmost = (bool(saved_top) if saved_top is not None
                        else bool(cfg.get("always_on_top", True)))
        root.attributes("-topmost", self.topmost)
        root.configure(bg=KEY)

        self.canvas = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        # DPI：main.py 已在 Tk() 前设置 awareness；此处取比例（96dpi → 1.0）
        self.S = max(0.5, float(root.tk.call("tk", "scaling")) * 72.0 / 96.0)
        self._make_fonts()

        # ---- 数据状态 ----
        self.usages: list[Usage] = []
        self.meta: dict = {}
        self.last_good: dict[str, Usage] = {}
        self.fetching = False
        self.hits: list[tuple[float, float, float, float, dict]] = []

        self._tip: tk.Toplevel | None = None
        self._tip_lbl: tk.Label | None = None
        self._drag_off: tuple[int, int] | None = None
        self._pos = (0, 24)   # 内部记账的窗口左上角（避免映射前 winfo 读到 0,0）
        self._press_xy: tuple[int, int] | None = None   # 判别点击 vs 拖拽
        self.clicks: list[tuple[float, float, float, float, Callable[[], None]]] = []
        self._settings = None            # 设置面板（单例）
        self._cred_panel = None          # 百炼凭据粘贴面板（单例）
        self._key_panels: dict = {}      # M6：各源密钥绑定面板（各自单例；M11a 起 Go/Codex）

        # ---- M7-b 刷新图标：↻ 步进旋转状态（after 循环，主线程，无新线程） ----
        self._rot = 0                    # 当前步转角（0..300，60° 一档）
        self._spin_job: object | None = None
        self._spin_deadline = 0.0        # monotonic；超时自停（防调度回包丢失后永转）
        self._refresh_geo: tuple[float, float, float] | None = None   # (cx, cy, 热区半径)
        self._hover_ic = False

        # ---- M9 边缘吸附：滑动动画状态（after 步进，主线程；新拖拽立即接管） ----
        self._snap_job: object | None = None
        self._snap_anim: tuple[int, int, int, int, int] | None = None   # (sx,sy,tx,ty,帧号)
        self._snap_target: tuple[int, int] | None = None   # 吸附终值（动画/落盘对账用）

        # ---- M16 自动更新触发：判定挂既有 5s/15s tick（不加常驻轮询），网络走
        #      瞬时 daemon 线程（同 M15 面板形态，结果经 _drain 回投主线程） ----
        self._upd_q: queue.Queue = queue.Queue()
        self._upd_busy = False             # 单飞：一次只允许一个在途检查线程
        self._upd_startup_done = False     # 进程内启动触发是否已消费
        self._upd_new: updater.UpdateInfo | None = None   # 发现未处理新版（UpdateInfo）→ 亮橙点
        self._upd_force_open = False       # 橙点点击 → 开设置并 force 检查一次

        self._make_menu()
        self._bind()
        self._render()
        self._place_initial()
        root.deiconify()

        root.after(150, self._drain)
        root.after(5000, self._tick)
        root.protocol("WM_DELETE_WINDOW", self.quit)

    # ================= 字体 / 尺寸 =================

    def _make_fonts(self) -> None:
        fams = set(tkfont.families(self.root))

        def pick(*cands: str) -> str:
            for c in cands:
                if c in fams:
                    return c
            return "TkDefaultFont"

        def F(family: str, size_in: float, bold: bool = False) -> tkfont.Font:
            return tkfont.Font(root=self.root, family=family,
                               size=-max(9, round(size_in * self.S)),
                               weight="bold" if bold else "normal")

        cjk = pick("Microsoft YaHei UI", "Microsoft YaHei", "SimHei")
        num = pick("Georgia", "Cambria", "Times New Roman")
        self.f_title = F(cjk, 14, True)
        self.f_name = F(cjk, 12.5, True)
        self.f_num = F(num, 21, True)
        self.f_small = F(cjk, 11)
        self.f_small_b = F(cjk, 11, True)
        self.f_tiny = F(cjk, 9.5)
        # 面板注记小字：M3c 审查②——9px 灰 CJK 中部横画易连读成「删除线」，注记提一档
        self.f_note = F(cjk, 10.5)
        self.f_badge = F(cjk, 9, True)
        self.f_tip = F(cjk, 10)

    def _p(self, v: float) -> float:
        return v * self.S

    # ---- M12④ ↻ 图标：4× 超采样纯 stdlib 光栅化（Tk 无抗锯齿的替代） ----
    #
    # 方案：几何与原手绘一致（300° 圆环扇段 + 切线箭头三角，a0=70+rot），但对每个
    # 物理像素取 4×4 子点解析判覆盖 → 笔画 premultiply 到纸底 PAPER 后 PhotoImage.put。
    # Tk 8.6 PhotoImage 无 per-pixel alpha（实测 truecolor/#RRGGBBAA 均不支持）→
    # 不能用"背景填色键再抠透明"（透明色键会透桌面）。M24A 定案：图标**后于纸纹点阵
    # 创建并经 _rot_raise 恒序收口**（压在纹理之上、文字之下）——旧 under-texture 方案
    # 让虚线栅格穿过图标，在初始渲染与旋转/hover 重绘之间漂移层序（用户实测可见）。
    # 图底 PAPER 与纸面同色、点阵间距 11px 稀疏，bbox 内遮蔽 ≤ 个位数 1px 点，无接缝、
    # 不透桌面；bbox 紧裁到墨迹外推 0.5px（半宽=ceil(√(rr²+s²)+线宽/2+.5)），
    # 不越顶边 20px 条带判据（icy=P(34)，半高≤15@200% → 上缘≥24px 物理）。
    # 旋转动画：启动后首轮渲染一次性生成 6 档（0/60/…/300°）PhotoImage（6×21²×16
    # 子点≈42k 次判定，毫秒级，实测见 verbose），_repaint_rot 只做 itemconfigure 换图
    # + _rot_raise（单一收口）。hover rotbg / 点击热区 / 旋转时序语义零改动。

    _SS = 4                       # 每像素 4×4 子点
    _ROT_IMGS: dict[tuple, dict[int, tk.PhotoImage]] = {}   # (master,S档) → {角度:图}

    def _rot_images(self) -> dict[int, tk.PhotoImage]:
        key = (id(self.root), round(self.S, 3))
        imgs = NoteApp._ROT_IMGS.get(key)
        if imgs is None:
            t0 = time.perf_counter()
            imgs = _gen_rot_icons(self.S)
            NoteApp._ROT_IMGS[key] = imgs
            if self.verbose:
                # M12h：不用 '↻'——console 变体 GBK 码页不可编码（fix-2 v1.6.3 定档）
                print(f"[ui] 刷新图标超采样光栅化×6：{(time.perf_counter() - t0) * 1000:.1f}ms "
                      f"(S={self.S:.3f})", flush=True)
        return imgs

    # ---- 纸形几何（渲染与「蒙版裁切」共用同一套真圆弧定义） ----

    def _rounded_rect(self, x0: float, y0: float, x1: float, y1: float,
                      rad: float, fill: str) -> None:
        """真圆角矩形 = 两条正交带 + 四个 1/4 圆盘（pie，无描边）。像素级可预测。"""
        c = self.canvas
        d = 2 * rad
        c.create_rectangle(x0 + rad, y0, x1 - rad, y1, fill=fill, outline="")
        c.create_rectangle(x0, y0 + rad, x1, y1 - rad, fill=fill, outline="")
        c.create_arc(x0, y0, x0 + d, y0 + d, style="pie", start=90, extent=90,
                     fill=fill, outline="")
        c.create_arc(x1 - d, y0, x1, y0 + d, style="pie", start=0, extent=90,
                     fill=fill, outline="")
        c.create_arc(x1 - d, y1 - d, x1, y1, style="pie", start=270, extent=90,
                     fill=fill, outline="")
        c.create_arc(x0, y1 - d, x0 + d, y1, style="pie", start=180, extent=90,
                     fill=fill, outline="")

    def _paper_clip(self, w: float, h: float, r: float) -> None:
        """内容（纸纹点阵/缝线/高光线）画完后，把圆角弧「外侧」补涂回色键。

        M3c 审查必修①：旧实现 smooth 样条圆角与纹理矩形边界不一致，角弧外
        会残留漂浮虚线段与白色高光线短横。此蒙版与 _rounded_rect 共用同一组
        圆弧（圆心 (r,r)/(w-r,r)/(r,h-r)/(w-r,h-r)、半径 r），48 段折线逼近
        （矢高 <0.001px），保证纸形外透明区绝对干净。"""
        c, seg = self.canvas, 48

        def arc(cx: float, cy: float, a0: float, a1: float) -> list[float]:
            pts: list[float] = []
            for i in range(seg + 1):
                a = math.radians(a0 + (a1 - a0) * i / seg)
                pts.extend([cx + r * math.cos(a), cy - r * math.sin(a)])
            return pts

        c.create_polygon([0, 0, r, 0, *arc(r, r, 90, 180), 0, r],
                         fill=KEY, outline="")
        c.create_polygon([w, 0, w - r, 0, *arc(w - r, r, 90, 0), w, r],
                         fill=KEY, outline="")
        c.create_polygon([0, h, r, h, *arc(r, h - r, 270, 180), 0, h - r],
                         fill=KEY, outline="")
        c.create_polygon([w, h, w - r, h, *arc(w - r, h - r, 270, 360), w, h - r],
                         fill=KEY, outline="")

    def _win_w(self) -> int:
        return int(round(W_IN * self.S))

    # ================= 摆放 / 位置记忆 =================

    def _place_initial(self) -> None:
        w = self._win_w()
        h = int(self.canvas.winfo_reqheight())
        l, t, r, b = work_area()
        x, y = self.init_state.get("x"), self.init_state.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            x = max(l, min(int(x), max(l, r - w)))   # 换显示器/分辨率时钳回工作区
            y = max(t, min(int(y), max(t, b - h)))
        else:
            x, y = r - w - 24, t + 24                # 默认右上
        self._pos = (int(x), int(y))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _sync_size(self) -> None:
        """内容高度变化后同步窗口尺寸，左上角保持不动（位置用内部记账值）。"""
        if self._quitting or not self.root.winfo_exists():
            return
        w = self._win_w()
        h = int(round(self.canvas.winfo_reqheight()))
        if self._drag_off is None and (self.root.winfo_height() != h
                                       or self.root.winfo_width() != w):
            self.root.geometry(f"{w}x{h}+{self._pos[0]}+{self._pos[1]}")
            self._print_geometry_line(w, h)
        else:
            self._print_geometry_line(self.root.winfo_width(),
                                      self.root.winfo_height())

    def _print_geometry_line(self, w: int, h: int) -> None:
        """--print-geometry：每次尺寸变化打一行（末行=当前几何，供截图/测试定位）。"""
        if self._print_geo and self.root.winfo_ismapped():
            print(f"GEOMETRY {w}x{h}+{self._pos[0]}+{self._pos[1]}", flush=True)

    # ================= 交互 =================

    def _bind(self) -> None:
        c = self.canvas
        c.bind("<ButtonPress-1>", self._drag_start)
        c.bind("<B1-Motion>", self._drag_move)
        c.bind("<ButtonRelease-1>", self._drag_end)
        c.bind("<Button-3>", self._on_right)
        c.bind("<Motion>", self._on_move)
        c.bind("<Leave>", lambda e: self._tip_hide())
        self.root.bind("<Escape>", lambda e: self._tip_hide())

    def _drag_start(self, e: tk.Event) -> None:
        self._tip_hide()
        self._cancel_snap()                # M9：动画未走完即新拖拽 → 立即终止接管
        self._snap_target = None
        self._press_xy = (int(e.x_root), int(e.y_root))
        self._drag_off = (int(e.x_root) - self.root.winfo_x(),
                          int(e.y_root) - self.root.winfo_y())

    def _drag_move(self, e: tk.Event) -> None:
        if self._drag_off:
            x = int(e.x_root) - self._drag_off[0]
            y = int(e.y_root) - self._drag_off[1]
            self._pos = (x, y)
            self.root.geometry(f"+{x}+{y}")

    def _win_size(self) -> tuple[int, int]:
        """窗口物理尺寸（与 _place_initial 钳制、_sync_size 同一口径）。"""
        return self._win_w(), int(self.canvas.winfo_reqheight())

    def _drag_end(self, e: tk.Event) -> None:
        self._drag_off = None
        moved = False
        if self._press_xy is not None:
            moved = (abs(int(e.x_root) - self._press_xy[0]) > 4
                     or abs(int(e.y_root) - self._press_xy[1]) > 4)
        self._press_xy = None
        # M9：仅"真拖拽"（>4px 位移，与点击同一判别）结束时判吸附；点击不吸
        target = (snap_target(self._pos, self._win_size(), work_areas(),
                              self._p(SNAP_PX)) if moved else None)
        if target is not None:
            # 终值即刻落盘（动画只是视觉滑行；中途退出/被杀也恢复贴边位）
            self._snap_target = target
            state_mod.save_state(x=target[0], y=target[1])
            self._start_snap(target)
        else:
            state_mod.save_state(x=self._pos[0], y=self._pos[1])
            self._print_geometry_line(self._win_w(), self.root.winfo_height())
        if not moved:                      # 原地松开 = 点击：命中行内按钮则触发
            for (x0, y0, x1, y1, cmd) in self.clicks:
                if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                    if cmd is not None:
                        cmd()
                    break

    # ---- M9 吸附动画（3 帧 ease-out ≈90ms；帧数/间隔见模块常量） ----

    def _start_snap(self, target: tuple[int, int]) -> None:
        self._cancel_snap()
        sx, sy = self._pos
        self._snap_anim = (int(sx), int(sy), int(target[0]), int(target[1]), 0)
        self._snap_step()                  # 第 1 帧同拍走起（不额外等 30ms）

    def _cancel_snap(self) -> None:
        if self._snap_job is not None:
            try:
                self.root.after_cancel(self._snap_job)   # type: ignore[arg-type]
            except (tk.TclError, ValueError):
                pass
            self._snap_job = None
        self._snap_anim = None

    def _snap_step(self) -> None:
        self._snap_job = None
        if self._quitting or self._snap_anim is None:
            return
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        sx, sy, tx, ty, i = self._snap_anim
        i += 1
        if i >= SNAP_FRAMES:               # 到站：终值与落盘一致，动画状态清零
            x, y = tx, ty
            self._snap_anim = None
            self._snap_target = None
        else:
            f = 1.0 - (1.0 - i / SNAP_FRAMES) ** 2      # ease-out：先快后慢
            x = int(round(sx + (tx - sx) * f))
            y = int(round(sy + (ty - sy) * f))
            self._snap_anim = (sx, sy, tx, ty, i)       # 帧号回写（否则永远卡第 1 帧）
        self._pos = (x, y)
        try:
            self.root.geometry(f"+{x}+{y}")
        except tk.TclError:
            return
        if self._snap_anim is not None:
            try:
                self._snap_job = self.root.after(SNAP_STEP_MS, self._snap_step)
            except tk.TclError:
                self._snap_job = None
        else:
            # --print-geometry：吸附后最终位（释放即时路径不经过这里）
            self._print_geometry_line(self._win_w(), self.root.winfo_height())

    def _on_right(self, e: tk.Event) -> None:
        self._tip_hide()
        try:
            self.root.focus_force()   # overrideredirect 窗口无系统焦点，帮菜单一把
        except tk.TclError:
            pass
        self.menu.post(int(e.x_root), int(e.y_root))

    # ---- 悬停 tooltip ----

    def _on_move(self, e: tk.Event) -> None:
        hit = None
        for (x0, y0, x1, y1, info) in self.hits:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                hit = info
                break
        on_btn = any(z[0] <= e.x <= z[2] and z[1] <= e.y <= z[3]
                     for z in self.clicks)
        self.canvas.configure(cursor="hand2" if on_btn else "")
        # M7-b hover：图标底色微变（PAPER_TX=纸面加深一档），只 toggle item 不重绘
        ic = self._refresh_geo
        over = (ic is not None and abs(e.x - ic[0]) <= ic[2]
                and abs(e.y - ic[1]) <= ic[2])
        if over != self._hover_ic:
            self._hover_ic = over
            try:
                self.canvas.itemconfigure("rotbg",
                                          state="normal" if over else "hidden")
            except tk.TclError:
                pass
        if hit is None:
            self._tip_hide()
        else:
            self._tip_show(hit, e)

    def _tip_show(self, info: dict, e: tk.Event) -> None:
        text = self._tip_text(info)
        if self._tip is None or not self._tip.winfo_exists():
            self._tip = tk.Toplevel(self.root)
            self._tip.overrideredirect(True)
            self._tip.attributes("-topmost", True)
            self._tip_lbl = tk.Label(self._tip, bg=TIP_BG, fg=TIP_FG, font=self.f_tip,
                                     justify="left", padx=10, pady=8)
            self._tip_lbl.pack()
        if self._tip_lbl is not None:
            self._tip_lbl.configure(text=text, bg=TIP_BG, fg=TIP_FG)
        self._tip.update_idletasks()
        tw, th = self._tip.winfo_reqwidth(), self._tip.winfo_reqheight()
        l, t, r, b = work_area()
        px, py = int(e.x_root) + 14, int(e.y_root) + 12
        if px + tw > r:
            px = int(e.x_root) - 14 - tw
        if py + th > b:
            py = max(t, int(e.y_root) - 12 - th)
        self._tip.geometry(f"+{px}+{py}")
        self._tip.deiconify()
        self._tip.lift()

    def _tip_hide(self) -> None:
        if self._tip is not None and self._tip.winfo_exists():
            self._tip.withdraw()

    def _tip_text(self, info: dict) -> str:
        if "tip" in info:                      # M7-b：图标等固定文案热区
            return info["tip"]
        u: Usage = info["u"]
        err: Usage | None = info.get("err")
        unit_cn = {"credits": "Credits", "usd": "USD", "percent": "%"}.get(u.unit, u.unit)
        lines = [f"{NAMES.get(u.provider, u.provider)}（{u.provider}）"
                 + (f" · 档位 {spec_display(u)}" if u.spec else "")]
        for wn in u.windows:
            lab = WIN_LABELS.get(wn.label, wn.label)
            seg = [f"{lab} 窗口：已用 {wn.pct_used:.1%}" if wn.pct_used is not None
                   else f"{lab} 窗口：暂无百分比"]
            if wn.resets_at is not None:
                seg.append(f"{_local(wn.resets_at):%m-%d %H:%M} 重置")
            lines.append(" · ".join(seg))
        big, _left = breakdown_display(u)
        if u.remaining is not None and u.total is not None:
            lines.append(f"合计：剩 {big} / "
                         f"{fmt_value(u.total, u.unit)} {unit_cn}")
        if u.pct_used is not None and u.addon_remaining is not None \
                and u.provider != "codex":
            # M3c 数据口径裁决：唯一文案增项（进度条旁小字 + 此行 tooltip）
            lines.append("百分比按 7 天周期计（合计数字含加油包）")
        if u.used is not None:
            lines.append(f"已消耗：{fmt_value(u.used, u.unit)} {unit_cn}")
        if u.provider == "codex":               # M10：addon 复用位=积分余额（USD）
            _cred = _tip_credits(u)
            if _cred:
                lines.append(_cred)
        elif u.addon_remaining is not None:
            _show, ad_t, ad_f = addon_bar_state(u)
            if ad_t:
                lines.append(f"加油包：剩 {ad_f:,} / 总 {math.floor(ad_t):,}"
                             f"（条长=剩余占比；多个 ACTIVE 包已合并，明细见控制台）")
            else:
                lines.append(f"加油包剩余：{ad_f:,}")
        if u.plan_end is not None and (pe_t := _local(u.plan_end)) is not None:
            # M23：完整到期日+剩余天数（C 行只显 MM-DD 短式，此处全式）
            _days = (pe_t.date() - datetime.now().astimezone().date()).days
            lines.append(f"套餐到期：{pe_t:%Y-%m-%d %H:%M}（"
                         + ("已到期" if _days < 0 else f"剩 {_days} 天") + "）")
        if u.note:                              # M10b：单行补充（如窗口重置券），无则不显
            lines.append(u.note)
        lines.append(f"拉取于 {fmt_clock(u.fetched_at)} · 下轮 "
                     f"{self.meta.get('next_delay', 0):.0f}s 后")
        if err is not None and not err.ok:
            msg = (err.error_msg or "")[:90]
            lines.append(f"当前状态：{err.error_code}" + (f" · {msg}" if msg else ""))
            lines.append("（上方为最后一次成功数据；失败期间自动退避重试）")
        return "\n".join(lines)

    # ================= 右键菜单 / 面板 / 退出 =================

    def _make_menu(self) -> None:
        m = tk.Menu(self.root, tearoff=0, bg=MENU_BG, fg=INK,
                    activebackground=MENU_HL, activeforeground=INK,
                    relief="flat", bd=1, font=self.f_small)
        m.add_command(label="立即刷新", command=self.refresh)
        self.var_top = tk.BooleanVar(value=self.topmost)
        m.add_checkbutton(label="总在最前", variable=self.var_top, command=self._toggle_top)
        m.add_separator()
        m.add_command(label="设置…", command=self.open_settings)
        m.add_command(label="退出（保存位置）", command=self.quit)
        self.menu = m

    def open_settings(self) -> None:
        """设置面板单例：已开则置顶。"""
        if self._settings is not None and self._settings.alive():
            self._settings.lift()
            return
        from .settings_panel import SettingsPanel
        self._settings = SettingsPanel(self)

    def open_credentials(self) -> None:
        """百炼 Cookie 粘贴面板单例。"""
        if self._cred_panel is not None and self._cred_panel.alive():
            self._cred_panel.lift()
            return
        from .settings_panel import CredentialPanel
        self._cred_panel = CredentialPanel(self)

    def open_key_panel(self, provider: str) -> None:
        """M6/M10：OpenAI / OpenCode Go / Codex 密钥绑定面板（按 provider 各自单例）。"""
        p = self._key_panels.get(provider)
        if p is not None and p.alive():
            p.lift()
            return
        from .settings_panel import ProviderKeyPanel
        self._key_panels[provider] = ProviderKeyPanel(self, provider)

    def refresh(self) -> None:
        self.fetching = True
        self._start_spin()                    # M7-b：点击/菜单/面板触发同走此路，图标即转
        self.sched.kick()
        self._render()
        if self.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] 手动刷新已触发（尝试绕过源缓存）", flush=True)

    def _toggle_top(self) -> None:
        self.set_topmost(bool(self.var_top.get()))

    # ---- 设置面板写回调（改即保存；面板直接调这些方法） ----

    def set_topmost(self, v: bool) -> None:
        self.topmost = bool(v)
        self.root.attributes("-topmost", self.topmost)
        try:
            self.var_top.set(self.topmost)
        except tk.TclError:
            pass
        try:
            if self._settings is not None and self._settings.alive():
                self._settings.var_top.set(self.topmost)
        except tk.TclError:
            pass
        state_mod.save_state(always_on_top=self.topmost)

    def save_cfg(self) -> None:
        from . import config as config_mod
        config_mod.save_config(self.cfg)      # CONFIG_PATH 模块级，测试可重定向

    def set_poll_seconds(self, v: int) -> None:
        v = max(60, min(3600, int(v)))
        self.cfg["poll_seconds"] = v
        self.sched.poll = float(v)
        self.save_cfg()

    def set_thresholds(self, yellow_pct: float, red_pct: float) -> None:
        y = min(99.0, max(1.0, float(yellow_pct)))
        r = min(99.0, max(1.0, float(red_pct)))
        self.low_yellow, self.low_red = y / 100.0, r / 100.0
        self.cfg["low_yellow_pct"] = y / 100.0
        self.cfg["low_red_pct"] = r / 100.0
        self.save_cfg()
        self._render()

    def set_enabled_providers(self, names: list[str]) -> None:
        self.cfg["enabled_providers"] = list(names)
        self.save_cfg()
        from .registry import active_sources
        self.sched.set_sources(active_sources(self.cfg))
        self.usages = []
        self.refresh()                        # 启停变化立即拉一轮

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._cancel_snap()                # M9：动画在途退出 → 落盘以吸附终值为准
        qx, qy = self._snap_target if self._snap_target is not None else self._pos
        state_mod.save_state(x=qx, y=qy, always_on_top=self.topmost)
        self.sched.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ================= 调度事件消费（queue → 主线程 after） =================

    def _drain(self) -> None:
        if self._quitting:
            return
        try:
            while True:
                kind, payload, meta = self.sched.events.get_nowait()
                if kind == "tick":
                    if not self.fetching:
                        self.fetching = True
                        self._start_spin()    # 自动轮询同样起转
                        self._render()
                else:
                    self.fetching = False
                    self._stop_spin()         # M7-b：回包即停转 + 图标归零
                    self._rot = 0
                    self.usages = payload
                    self.meta = meta
                    for u in payload:
                        if u.ok:
                            self.last_good[u.provider] = u
                    if self.verbose:
                        self._log_cycle(payload, meta)
                    self._render()
        except queue.Empty:
            pass
        except Exception as e:                    # 渲染异常不能让事件循环停摆（信息不含凭据）
            print(f"[ui] 渲染异常（已跳过本轮）：{type(e).__name__}: {str(e)[:160]}",
                  flush=True)
        self._upd_drain()                       # M16：同循环顺带消费自动更新结果（无新轮询）
        self.root.after(250, self._drain)

    def _log_cycle(self, usages: list[Usage], meta: dict) -> None:
        parts = []
        for u in usages:
            if u.ok:
                bits = f"剩 {fmt_value(u.remaining, u.unit)}"
                if u.pct_used is not None:
                    bits += f" 已用 {u.pct_used:.1%}"
                parts.append(f"{u.provider}=OK({bits})")
            else:
                parts.append(f"{u.provider}={u.error_code}")
        print(f"[{time.strftime('%H:%M:%S')}] 轮询完成: " + " | ".join(parts)
              + f" | 下轮 {meta.get('next_delay', 0):.0f}s", flush=True)

    def _tick(self) -> None:
        if self._quitting:
            return
        try:
            if self.usages and self._drag_off is None:
                self._render()          # 刷新倒计时文案（分钟粒度足够）
        except Exception as e:
            print(f"[ui] 定时重绘异常（已跳过）：{type(e).__name__}: {str(e)[:160]}",
                  flush=True)
        try:
            self._upd_tick()            # M16：自动更新触发点（首 tick≈5s=启动位；5 点后=每日位）
        except Exception as e:
            print(f"[ui] 更新触发异常（已跳过）：{type(e).__name__}", flush=True)
        self.root.after(15000, self._tick)

    # ================= M16 自动更新触发 + 发现新版橙点 =================

    def _upd_tick(self) -> None:
        """15s tick 复用：判定并发起自动检查（enabled/slug/6h/日期戳全在 updater）。

        仅起瞬时 daemon 线程做网络（主线程绝不打网，防 20s 冻结 UI）；结果由
        _drain 回投。startup 触发每进程一次；daily 由 last_auto_date 防重。"""
        if self._upd_busy or self._quitting:
            return
        if not isinstance(self.cfg.get("update"), dict):
            return                                # M16：cfg 未接入 update 节（旧手写配置/测试
            #                                       fixture）→ 触发点整体静默；真实 app 经
            #                                       load_config 合并必有该节，功能不受影响
        trig = updater.next_trigger(self.cfg, self._upd_startup_done)
        if not trig:
            return
        if trig == "startup":
            self._upd_startup_done = True
        self._upd_busy = True
        threading.Thread(target=self._upd_work, args=(trig,), daemon=True).start()

    def _upd_work(self, trig: str) -> None:
        try:
            res = updater.check(self.cfg, force=False)
        except Exception as e:                        # noqa: BLE001 线程兜底
            res = updater.CheckResult(err=f"检查异常：{type(e).__name__}")
        self._upd_q.put((trig, res))

    def _upd_drain(self) -> None:
        """_drain(250ms) 顺带消费更新结果：落戳/灭点/亮点（全在主线程）。"""
        changed = False
        try:
            while True:
                trig, res = self._upd_q.get_nowait()
                self._upd_busy = False
                if res.skipped:
                    # 被 6h 频控：daily 仍记日期戳（结果本就新鲜，防此后每 15s 空转起线程）
                    if trig == "daily":
                        updater.stamp_auto_trigger(self.cfg, trig, attempted=False)
                        self.save_cfg()
                    continue
                updater.stamp_auto_trigger(self.cfg, trig)
                self.save_cfg()
                if res.ok:
                    if updater.is_newer(res.info.version, APP_VERSION):
                        self._upd_new = res.info      # 有未发现新版 → 橙点亮
                    else:
                        self._upd_new = None          # 已是最新 → 灭
                else:
                    self._upd_new = None              # 网络失败不亮误导点
                changed = True
        except queue.Empty:
            pass
        if changed and not self._quitting:
            self._render()                            # 点亮/灭点即时生效（不渲染会等下轮）

    def _upd_open(self) -> None:
        """橙点出口：打开设置页并置 force 标记（面板 build 时无视频控刷一次状态）。"""
        self._upd_force_open = True
        self.open_settings()

    # ================= 绘制原语 =================

    def _pill(self, x0: float, y0: float, x1: float, y1: float,
              fill: str, outline: str = "", width: int = 0) -> None:
        """胶囊形：两端半圆 + 中段矩形。

        M3c⑥：填充层 chord 不带描边（chord 自带闭合直边描边会在胶囊端帽
        内缘留下 1px 竖笔）。
        M7b④：描边层再升级为「单条闭合采样折线」（右帽 12 段半圆弧 → 底边 →
        左帽 12 段 → 顶边闭合）——两条独立 create_arc(style=arc) 的路径端点
        帽会在弧与直线交界(x±r 处)画出 2~3px 竖直进桩（12× 实拍确认，即审查
        所称"右帽 1px 竖笔"），闭点多边形无端点帽、交界为连续拐角，一并根治
        细条右端同样的">"状桩。"""
        c = self.canvas
        h = y1 - y0
        r = h / 2
        if x1 - x0 <= h:
            c.create_oval(x0, y0, x0 + h, y1, fill=fill, outline=outline, width=width)
            return
        c.create_arc(x0, y0, x0 + h, y1, start=90, extent=180, style="chord",
                     fill=fill, outline="")
        c.create_arc(x1 - h, y0, x1, y1, start=-90, extent=180, style="chord",
                     fill=fill, outline="")
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline="")
        if outline and width:
            seg = 12

            def arc_pts(cx: float, cy: float, a0: float, a1: float) -> list[float]:
                pts: list[float] = []
                for i in range(seg):
                    a = math.radians(a0 + (a1 - a0) * i / seg)
                    pts.extend([cx + r * math.cos(a), cy - r * math.sin(a)])
                return pts

            # 起点=右帽顶点 (x1-r, y0)，顺右帽→底边→左帽→（闭合边=顶边）
            pts = arc_pts(x1 - r, y0 + r, 90, -90) + arc_pts(x0 + r, y0 + r, 270, 90)
            c.create_polygon(pts, smooth=False, fill="", outline=outline,
                             width=width)

    def _badge(self, x: float, cy: float, text: str, fg: str, bg: str,
               edge: str, dashed: bool = False) -> float:
        """小徽章，返回下一段起点 x。"""
        f = self.f_badge
        w = f.measure(text) + self._p(14)
        h = self._p(17)
        y0, y1 = cy - h / 2, cy + h / 2
        if dashed:
            self.canvas.create_rectangle(x, y0, x + w, y1, fill="", outline=fg,
                                         width=1, dash=(3, 2))
        else:
            self._pill(x, y0, x + w, y1, fill=bg, outline=edge, width=1)
        self.canvas.create_text(x + w / 2, cy, text=text, font=f, fill=fg)
        return x + w + self._p(6)

    def _bar(self, x: float, y: float, w: float, h: float,
             pct_used: float | None, color: str,
             track: str = TRACK, edge: str = TRACK_EDGE) -> None:
        """进度条（填充=已用比例；加油包细条传入的是「剩余占比」，与自身文案同向）。

        M7-a：track/edge 可覆写。M7b⑤→M24C：内高光线改**绝对像素阈**——填充宽
        ≥BAR_HI_MIN_PX(24 逻辑px，随 DPI 缩放) 才画。旧「<15% 轨宽」在双主条并排时
        产生观感不一致（330 宽下 ≈44px 才画，8% 周条与 41% 5h 条一边有无）；
        绝对阈下同一屏两根条按同一把尺子判定，小窗两条都无、大窗两条都有。"""
        c = self.canvas
        self._pill(x, y, x + w, y + h, fill=track, outline=edge, width=1)
        if pct_used is None or pct_used <= 0:
            return
        pw = max(h, w * min(1.0, pct_used))
        self._pill(x, y, x + pw, y + h, fill=color)
        if pw < self._p(BAR_HI_MIN_PX):
            return
        c.create_line(x + h / 2, y + h * 0.28, x + pw - h / 2, y + h * 0.28,
                      fill=BAR_HI, width=max(1, int(self.S)))

    def _click_pill(self, x_right: float, cy: float, text: str,
                    cmd: Callable[[], None], fg: str) -> float:
        """右对齐可点击胶囊按钮（原地松开触发，见 _drag_end 点击分流）。返回左缘 x。"""
        f = self.f_small_b
        w = f.measure(text) + self._p(16)
        h = self._p(19)
        x0 = x_right - w
        self._pill(x0, cy - h / 2, x0 + w, cy + h / 2,
                   fill=BADGE_BG, outline=BADGE_EDGE, width=1)
        self.canvas.create_text(x0 + w / 2, cy, text=text, font=f, fill=fg)
        self.clicks.append((x0, cy - h / 2, x0 + w, cy + h / 2, cmd))
        return x0

    # ================= 行模型 =================

    def _row_infos(self) -> list[dict]:
        """把「本轮 Usage + 最后成功值」折叠成行视图：{u=展示值, err=错误, stale, cred, kind}。"""
        infos = []
        for u in self.usages:
            if u.ok:
                infos.append({"kind": "full", "u": u, "err": None,
                              "stale": False, "cred": False})
                continue
            good = self.last_good.get(u.provider)
            cred = (u.error_code or "") in CRED_ERRORS
            if good is not None:
                infos.append({"kind": "full", "u": good, "err": u,
                              "stale": True, "cred": cred})
            else:
                infos.append({"kind": "err", "u": u, "err": u,
                              "stale": False, "cred": cred})
        return infos

    @staticmethod
    def _extra_windows(u: Usage) -> int:
        """主行之外的窗口条数（百炼 5h；Go 周/月）——0 即完全不占位（PLAN §7-Q5 推广）。"""
        return max(0, len(u.windows) - 1)

    def _row_h(self, info: dict) -> float:
        if info["kind"] == "err":
            return ROW_ERR
        u = info["u"]
        if u.provider == "codex":
            main, sec = codex_bars(u)
            if main is not None:                   # M14 双主条：两信息块收进 ROW_FULL 内
                h = ROW_FULL
                if info["cred"] or info["stale"]:
                    h += ROW_CRED
                return h
            # 全未知窗（other:N 独苗等异常套餐）→ 落通用路径，数据不丢
        if u.provider == "opencode_go" and u.windows:
            # M24B Go 多主条：两窗以内 ROW_FULL 全收（同 codex 高度账），
            # 第 3 窗起每多一窗 +GO_BAR_PITCH（28px，与块行距同值）
            n = len(go_bars(u))
            h = ROW_FULL + GO_BAR_PITCH * max(0, n - 2)
            if info["cred"] or info["stale"]:
                h += ROW_CRED
            return h
        h = ROW_FULL + ROW_5H * self._extra_windows(u)
        if addon_bar_state(u)[0]:                  # M7-a：无包零占位（与 5h 同策略）
            h += ROW_ADDON
        if info["cred"] or info["stale"]:
            h += ROW_CRED
        return h

    # ================= 整窗渲染 =================

    def _render(self) -> None:
        if self._drag_off is not None or self._quitting:
            return
        c, S, P = self.canvas, self.S, self._p
        c.delete("all")
        self.hits = []
        self.clicks = []
        w, m = W_IN * S, P(M_IN)

        infos = self._row_infos()
        h_log = HEAD_H + 8 + sum(self._row_h(i) + 8 for i in infos)
        if not infos:
            h_log += 34
        h = max(P(120), h_log * S)
        c.configure(width=int(round(w)), height=int(round(h)))

        r, fr = P(R_IN), P(FOLD_IN)
        lw = max(1, round(S))
        # ---- 纸面：真圆弧组合形。先画描边环（外轮廓），再画内层纸色填充 ----
        # （M3c①：弃用 smooth 样条——样条角弧与纹理/高光线的矩形边界不一致，
        #   透明区会残留漂浮点段；组合形 + 尾部 _paper_clip 保证蒙版外绝对干净。）
        self._rounded_rect(0, 0, w, h, r, PAPER_EDGE)
        self._rounded_rect(lw, lw, w - lw, h - lw, max(2.0, r - lw), PAPER)

        # ---- 纸纤维斜纹（点状颗粒） ----
        step, skew = P(11), P(3)
        i = -h
        while i < w:
            c.create_line(i, 0, i + skew, h, fill=PAPER_TX, width=1, dash=(1, 6))
            i += step

        # ---- M24A ↻ 图标族（rotbg+图）**后于纸纹创建**：恒压在纸纹之上、文字之下。
        #      M12④ 的 under-texture 让虚线栅格穿过图标，在「初始渲染↔旋转/hover」
        #      之间产生层序漂移（用户实测：静置被压下面、转一圈回到上面）→ 定案
        #      恒序：icon items 一律在纹理后建，并经 _rot_raise 单一收口（与
        #      _repaint_rot 同路）。图底 PAPER 与纸面同色、点阵间距 11px 极稀疏，
        #      bbox 内最多遮蔽个位数 1px 点，无接缝观感。几何记账不变。 ----
        stat = self._head_status()
        icx = w - m - self.f_tiny.measure(stat) - self._p(6) - self._p(7.5)
        icy = P(34)
        ird = self._p(9.5)
        self._refresh_geo = (icx, icy, ird)
        c.create_oval(icx - ird, icy - ird, icx + ird, icy + ird,
                      fill=PAPER_TX, outline="", state="hidden", tags="rotbg")
        if self._hover_ic:
            c.itemconfigure("rotbg", state="normal")
        self._rot_icon(icx, icy)
        self._rot_raise()

        # ---- 顶沿高光 / 底沿暗线 ----
        c.create_line(r, P(1.6), w - r, P(1.6), fill=PAPER_HI, width=lw)
        c.create_line(r, h - P(2.0), w - fr - r, h - P(2.0), fill=PAPER_TX,
                      width=max(1, round(S * 1.5)))

        # ---- 胶带握把（顶部居中） ----
        tw, th = P(92), P(18)
        tx0, ty0 = (w - tw) / 2, P(2)
        self._pill(tx0, ty0, tx0 + tw, ty0 + th, fill=TAPE, outline=TAPE_EDGE, width=1)
        c.create_line(tx0 + th * 0.6, ty0 + th * 0.42, tx0 + tw - th * 0.6,
                      ty0 + th * 0.42, fill=TAPE_LINE, dash=(4, 3))
        c.create_line(tx0 + th * 0.6, ty0 + th * 0.68, tx0 + tw - th * 0.6,
                      ty0 + th * 0.68, fill=TAPE_LINE, dash=(4, 3))

        # ---- 头部 ----
        c.create_text(m, P(34), anchor="w", text="Token 余量",
                      font=self.f_title, fill=INK)
        c.create_line(m, P(45), w - m, P(45), fill=PAPER_EDGE, dash=(2, 3))
        c.create_text(w - m, P(34), anchor="e", font=self.f_tiny,
                      fill=ORANGE if self.fetching else SOFT, text=stat)
        # ↻ 图像与 rotbg 已在纸纹层之后创建（M24A 恒序）；此处仅挂热区（坐标同旧）
        self.clicks.append((icx - ird, icy - ird, icx + ird, icy + ird, self.refresh))
        self.hits.append((icx - ird, icy - ird, icx + ird, icy + ird,
                          {"tip": "立即刷新（绕过缓存）"}))

        # ---- 供应商行 ----
        y = float(HEAD_H)
        for idx, info in enumerate(infos):
            if idx:
                c.create_line(m, P(y - 4), w - m, P(y - 4),
                              fill=PAPER_EDGE, dash=(1, 3))
            y = self._draw_row(y, info, m, w)
            y += 8
        if not infos:
            c.create_text(m, P(y + 10), anchor="w", fill=SOFT, font=self.f_small,
                          text="没有已启用的供应商（见 config.enabled_providers）")

        # ---- M16 发现新版橙点（≤15 行改动，逐行注释）----
        # 仅"有未发现新版"时绘制；位于 foot 底部右缘、卷边三角左上（不触 M3c 顶边纯净判据）；
        # 直径 3px（半径 1.5px×S），零行高增（不改 h 记账）；10px 见方点击热区。
        if self._upd_new is not None:                      # 无发现 → 整段跳过（零占位）
            ux, uy = w - fr - P(9), h - P(11)              # 卷边内侧、底沿暗线上方
            ur = max(1.0, P(1.5))                          # 3px 直径（DPI 缩放后下限 2px）
            c.create_oval(ux - ur, uy - ur, ux + ur, uy + ur,
                          fill=ORANGE, outline="", tags=("updot",))  # 纯色点无描边
            ud = self._p(8)                                # 点击/悬停容差（半宽 8px）
            self.clicks.append((ux - ud, uy - ud, ux + ud, uy + ud,
                                self._upd_open))           # 点击→设置页+force 检查
            self.hits.append((ux - ud, uy - ud, ux + ud, uy + ud,
                              {"tip": f"发现新版本 v{self._upd_new.version}，点击查看"}))

        # ---- 纸形蒙版裁切：圆角弧外的纹理/缝线/高光线全部补涂色键（M3c①） ----
        self._paper_clip(w, h, r)

        # ---- 右下卷边：色键沿对角裁掉纸角 → 翻折三角（直边，与切口共线） ----
        if self._keyed:
            c.create_polygon(w, h - fr, w, h, w - fr, h, fill=KEY, outline="")
            c.create_polygon(w - fr, h, w, h - fr, w - fr, h - fr, smooth=False,
                             fill=FOLD, outline=PAPER_EDGE, width=lw)

        self.root.after_idle(self._sync_size)

    def _head_status(self) -> str:
        if self.fetching:
            return "更新中…"
        if not self.usages:
            return "读取中…"
        latest = max((u.fetched_at for u in self.usages if u.ok), default=None)
        if latest is None:
            return "尚无成功数据"
        return f"{fmt_clock(latest)} 更新"

    # ---- M7-b 刷新图标（手绘 ↻ = 300° 弧 + 切线箭头，不用系统字体符号） ----

    SPIN_STEP_MS = 120       # 60°/步 → 一圈 720ms，纸面小图标不过度闪烁
    SPIN_TIMEOUT_S = 30.0    # 兜底：调度回包丢失时自停，不永转

    def _rot_icon(self, cx: float, cy: float) -> None:
        """M12④：↻ = 4× 超采样光栅化图（替代 create_arc+polygon 手绘，消锯齿）。

        anchor=center 与旧笔画同圆心同半径，热区/rotbg 记账不变；tags 保留
        "rot"（删除语义兼容）+ "rotimg"（旋转帧 itemconfigure 换图定位用）。"""
        self.canvas.create_image(cx, cy, image=self._rot_images()[self._rot],
                                 tags=("rot", "rotimg"))

    def _rot_raise(self) -> None:
        """M24A 层序收口（唯一出口）：图标族恒序——纸纹之上、rotbg 在图之下。
        初始渲染与每个旋转帧/hover 重绘同路调用，任何时刻所见层序一致。"""
        try:
            self.canvas.tag_raise("rotbg")
            self.canvas.tag_raise("rot")
        except tk.TclError:
            pass

    def _repaint_rot(self) -> None:
        """旋转帧：只换 image 引用（不删体重绘），并走 _rot_raise 同一层序收口。"""
        geo = self._refresh_geo
        if geo is None or self._quitting or not self.root.winfo_exists():
            return
        try:
            self.canvas.itemconfigure("rotimg",
                                      image=self._rot_images()[self._rot])
        except tk.TclError:
            pass
        self._rot_raise()

    def _start_spin(self) -> None:
        if self._spin_job is not None or self._quitting:
            return
        self._spin_deadline = time.monotonic() + self.SPIN_TIMEOUT_S
        self._spin_step()

    def _stop_spin(self) -> None:
        if self._spin_job is not None:
            try:
                self.root.after_cancel(self._spin_job)   # type: ignore[arg-type]
            except (tk.TclError, ValueError):
                pass
        self._spin_job = None

    def _spin_step(self) -> None:
        self._spin_job = None
        if self._quitting or not self.fetching:
            self._rot = 0
            return
        if time.monotonic() > self._spin_deadline:      # 超时：停在当前角，回包即归零
            return
        self._rot = (self._rot - 60) % 360    # M8b 用户"倒放"：反向步进（画布角度系→屏幕顺时针）
        self._repaint_rot()
        try:
            self._spin_job = self.root.after(self.SPIN_STEP_MS, self._spin_step)
        except tk.TclError:
            self._spin_job = None

    # ---- 单行渲染 ----

    def _draw_row(self, y: float, info: dict, m: float, w: float) -> float:
        """画一个供应商行，返回行底 y（逻辑单位）。"""
        if info["kind"] == "err":
            return self._draw_err_row(y, info, m, w)
        return self._draw_full_row(y, info, m, w)

    def _cred_ui(self, u: Usage) -> tuple[str, str, Callable[[], None]]:
        """凭据档（CRED_ERRORS）行的 (警示文案, 按钮文案, 动作)：百炼=Cookie，OpenAI/Go=key。"""
        if u.provider == "bailian":
            return ("需重新登录凭据（Cookie 过期）", "更新登录凭据…", self.open_credentials)
        code = u.error_code or ""
        if code == "REGION_BLOCKED":
            # fix-5 定案：橙档但环境态——文案指路换节点，按钮给「立即重试」（换好节点即恢复）
            return ("出口地区受限 · 切换海外节点后自动恢复", "立即重试", self.refresh)
        if code == "NO_SUBSCRIPTION":
            txt = "此 key 无 OpenCode Go 订阅 · 换 key 或重新登录"
        elif code == "KEY_INVALID":
            # M10：codex 的 KEY_INVALID=OAuth token 过期（续期流语义=百炼 Cookie 档）
            txt = ("登录已过期 · 重新获取 access token" if u.provider == "codex"
                   else "密钥无效 · 需重新绑定")
        else:
            txt = "需重新绑定凭据"
        return (txt, "配置密钥…", lambda: self.open_key_panel(u.provider))

    def _draw_full_row(self, y: float, info: dict, m: float, w: float) -> float:
        c, P = self.canvas, self._p
        u: Usage = info["u"]
        err: Usage | None = info["err"]
        stale, cred = info["stale"], info["cred"]

        # 颜色：正常墨色；旧数据/凭据异常整体降灰
        c_name = INK if not stale else SOFT
        c_num = INK if not stale else STALE
        c_soft = SOFT_TXT if not stale else FAINT
        right = w - m

        # 行首警示行：凭据异常 → 橙色提示 + 行内绑定按钮（M6：百炼=Cookie 面板，OpenAI/Go=密钥面板）；
        # 其他 stale → 灰字原因
        if cred:
            # 错误码在 err（本轮失败 Usage）上；stale 行 info["u"] 是最后成功值
            warn_txt, btn_txt, btn_cmd = self._cred_ui(err or u)
            c.create_text(m, P(y + 10), anchor="w", font=self.f_small, fill=ORANGE,
                          text=warn_txt)
            self._click_pill(right, P(y + 5), btn_txt, btn_cmd, ORANGE)
            y += ROW_CRED
        elif stale and err is not None:
            c.create_text(m, P(y + 10), anchor="w", font=self.f_small, fill=FAINT,
                          text=f"拉取失败 · {err.error_code} · 自动重试中（退避）")
            y += ROW_CRED

        top = y
        # A 行：名称 + 档位徽章 (+旧数据徽章) + 右端大数字
        c.create_text(m, P(y + 16), anchor="w", font=self.f_name, fill=c_name,
                      text=NAMES.get(u.provider, u.provider))
        x = m + self.f_name.measure(NAMES.get(u.provider, u.provider)) + P(8)
        if u.spec:
            x = self._badge(x, P(y + 12), spec_display(u),
                            SOFT, BADGE_BG, BADGE_EDGE)
        if stale:
            x = self._badge(x, P(y + 12), "旧数据", FAINT, "", FAINT, dashed=True)
        # M11b 重置券角标「券×N」：note 解析，画在 A 行徽章位（零高度增量）；
        # 无券/解析失败 → 完全不占位。hover=说明 tooltip（独立热区，先于行区注册），
        # 无点击动作（计数不是操作）。
        n_tk = codex_ticket_count(u)
        if n_tk is not None:
            bx0 = x
            # M11c②：与 PLUS 同档（SOFT 灰褐）——角标是配角，不与主角争墨色
            x = self._badge(x, P(y + 12), f"券×{n_tk}",
                            FAINT if stale else SOFT, BADGE_BG, BADGE_EDGE)
            self.hits.append((bx0, P(y + 12) - P(9.5), x - P(6), P(y + 12) + P(9.5),
                              {"tip": f"窗口重置券 ×{n_tk}：额度耗尽时可提前重置窗口"
                                       "（实验性接口计数）"}))

        big, left = breakdown_display(u)      # 大数字与 C 行分项同源，保证 Σ 自洽
        # M11d① 分流计算上提：codex 固定槽（5h 主条）+ 大数字口径覆写
        cx_main, cx_sec = codex_bars(u)
        # M24B Go 多主条：大数字=剩余占比·最紧窗口径（各窗 pct 最大者的余量）
        gb = go_bars(u)
        if gb:
            gp = go_tightest_pct(gb)
            big = f"{(1 - gp) * 100:.0f}%" if gp is not None else "—"
        if cx_main is not None:
            # M11d 口径定案：大数字随主条窗剩余占比（所见即所得，与主条同窗同数）；
            # 周窗紧迫度不丢——副细条自着色黄/红 + 自带倒计时（各窗独立判阈值不变）。
            big = (f"{(1 - cx_main.pct_used) * 100:.0f}%"
                   if cx_main.pct_used is not None else "—")
        c.create_text(right, P(y + 20), anchor="e", font=self.f_num, fill=c_num,
                      text=big)
        # M9b：usd 大数字已改显真实已用时，单位小字跟着改语义（否则「$0.00/美元剩」自相矛盾）
        unit_cn = "近30天已用" if usd_used_mode(u) else \
            {"credits": "Credits 剩", "usd": "美元剩", "percent": "剩余占比"}\
            .get(u.unit, f"{u.unit} 剩")
        c.create_text(right, P(y + 35), anchor="e", font=self.f_tiny, fill=c_soft,
                      text=unit_cn)

        # M11b/codex 双条专用支路（cx_main 非空即 codex 已知窗；见上 M11d 口径覆写）
        if cx_main is not None:
            return self._draw_codex_bars(top, info, u, cx_main, cx_sec,
                                         m, right, stale)
        # M24B Go 多主条支路：与 codex M14 同语法（有几窗画几条，5h→日→周→月上到下）
        if gb:
            return self._draw_win_bars(top, info, u, gb, m, right, stale)

        # B 行：主窗口标签 + 倒计时；进度条（Go 的 rolling 经 WIN_LABELS 显示为 "5h"）
        main_w = u.windows[0] if u.windows else None
        label = WIN_LABELS.get(main_w.label, main_w.label) if main_w else "主窗口"
        pct_used = u.pct_used
        reset_dt = u.resets_at or (main_w.resets_at if main_w else None)
        if main_w is None:      # 无窗口概念（OpenAI 预算/余额）→ 直接额度文案
            left_txt = f"额度 · 已用 {pct_used:.1%}" if pct_used is not None \
                else "暂无百分比数据"
        else:
            left_txt = f"{label} 窗口 · 已用 {pct_used:.1%}" if pct_used is not None \
                else f"{label} 窗口 · 暂无百分比数据"
        # M3c 数据口径注记：含加油包时百分比分母是周期额度而非合计，防误读
        # （例：已用 62.1% = 24,853/40,000，而 60,000 为含加油包合计）。
        if pct_used is not None and u.addon_remaining is not None and u.total is not None:
            tail = "（按周期计）"
            room = right - m - self.f_small_b.measure(fmt_countdown(reset_dt)) \
                - self._p(10) - self.f_tiny.measure(left_txt)
            if room >= self.f_tiny.measure(tail):
                left_txt += tail
        c.create_text(m, P(y + 53), anchor="w", font=self.f_tiny, fill=c_soft,
                      text=left_txt)
        c.create_text(right, P(y + 53), anchor="e", font=self.f_small_b,
                      fill=c_name, text=fmt_countdown(reset_dt))
        self._bar(m, P(y + 60), right - m, P(9), pct_used,
                  STALE if stale else self._bar_color(pct_used))

        # M7-a 加油包细条：主条下方第二根（60% 高、中性卡其、无阈值语义）；
        # 无 ACTIVE 包时完全不占位。M7b②：填充=剩余占比，与右端「剩 X / 总 Y」
        # 文字同向（主条文字读「已用%」、条长=已用——两条各锚自身文案，图文不再相反）。
        # M7b①：显示值走 addon_split 同一 floor 源。到期日 sources 未透出 → 暂缺。
        show_ad, ad_total, ad_floor = addon_bar_state(u)
        if show_ad:
            by = P(y + 72)
            bh = P(5.4)
            lab = "加油包"
            if ad_total:
                # M11c③ 方向锚：「剩 X / Y」——细条图文同向（条长=剩余占比），
                # 与 codex 副细条「已用 x%」构成「右文案锚字为准」的统一读法
                rtxt = f"剩 {ad_floor:,} / {math.floor(ad_total):,}"
                rem_frac = max(0.0, min(1.0, (u.addon_remaining or 0.0) / ad_total))
            else:
                rtxt = f"剩 {ad_floor:,}"
                rem_frac = None
            lw_lim = right - m - self.f_tiny.measure(rtxt) - P(10) \
                - self.f_tiny.measure(lab) - P(6)
            self._bar(m + self.f_tiny.measure(lab) + P(6), by, max(P(30), lw_lim),
                      bh, rem_frac,
                      STALE if stale else ADDON_FILL,
                      track=TRACK, edge=TRACK_EDGE)
            c.create_text(m, by + bh / 2, anchor="w", font=self.f_tiny,
                          fill=SOFT if not stale else FAINT, text=lab)
            c.create_text(right, by + bh / 2, anchor="e", font=self.f_tiny,
                          fill=c_soft, text=rtxt)

        # C 行：数值拆分（更新时间只在标题行出现，此处不再重复）
        if left:
            yy = P(y + 82 + (ROW_ADDON if show_ad else 0))
            l_txt, t_txt, t_col = left, None, c_soft  # M23：套餐到期后缀（plan_end=None 零占位）
            pe = plan_end_display(u)
            if pe is not None:
                t_txt, t_col = pe
                if stale:
                    t_col = c_soft                    # 旧值灰显时到期文字随灰（紧急档也不例外）
                l_txt, keep = plan_end_split(left, t_txt, self.f_tiny.measure,
                                             right - m - P(4))
                if keep is None:
                    t_txt = None                      # 截了主文仍放不下 → 后缀不显（同律降级）
                else:
                    t_txt = keep
            c.create_text(m, yy, anchor="w", font=self.f_tiny, fill=c_soft,
                          text=l_txt)
            if t_txt:
                c.create_text(m + self.f_tiny.measure(l_txt), yy, anchor="w",
                              font=self.f_tiny, fill=t_col, text=t_txt)

        bottom = top + ROW_FULL + (ROW_ADDON if show_ad else 0)
        # D 行（可选）：主行之外的窗口逐条副显（百炼 5h / Go 周·月）；不返回即完全不占位
        for wn in u.windows[1:]:
            lab = WIN_LABELS.get(wn.label, wn.label)
            txt = f"{lab} 窗口 · 已用 " + (f"{wn.pct_used:.1%}" if wn.pct_used is not None
                                           else "—")
            c.create_text(m, P(bottom + 6), anchor="w", font=self.f_tiny,
                          fill=c_soft, text=txt)
            c.create_text(right, P(bottom + 6), anchor="e", font=self.f_tiny,
                          fill=c_soft,
                          text=f"{fmt_countdown(wn.resets_at)}（{lab}）")
            bottom += ROW_5H

        self.hits.append((m - P(6), P(top), right + P(6), P(bottom),
                          {"u": u, "err": err, "stale": stale}))
        return bottom

    def _draw_codex_bars(self, top: float, info: dict, u: Usage,
                         main: Window, sec: Window | None,
                         m: float, right: float, stale: bool) -> float:
        """M14 codex 行主体：两根等尺寸主条信息块（文字行+9px 条），M11d① 固定槽不变。

        5h/周两窗完全对称：各自「{短名} · 已用 x%（左，f_tiny）＋ 倒计时（右，粗档）」
        文字行下随一根与百炼主条同高同圆角同空轨语言的 9px 条；组内 文字→条 7px，
        组间 12px（条-条 19px）。阈值色按**各自窗** pct 独立判（_bar_color），
        填充=已用向，图文自洽无需锚字（M11c③ 纪律在双主条下自然成立）。
        整组（双窗）底缘 y+97 < ROW_FULL=100：第二条借用旧细条+C 行空档，行高不增。
        M24B 起几何循环收编进 _draw_win_bars（Go 多主条共用同族语法），本函数只剩
        固定槽取数转调。"""
        return self._draw_win_bars(top, info, u,
                                   [main] + ([sec] if sec is not None else []),
                                   m, right, stale)

    def _draw_win_bars(self, top: float, info: dict, u: Usage,
                       bars: list[Window], m: float, right: float,
                       stale: bool) -> float:
        """M14/M24B 多主条行：N 个等尺寸「文字行+9px 条」信息块自上而下排布。

        块行距 GO_BAR_PITCH=28（文字→条 7 + 条 9 + 组间 12）；两窗底缘 97 收进
        ROW_FULL=100（行高零增），第 3 窗起每多一窗行高 +28（与 _row_h 同账）。
        codex（固定槽 5h/周，≤2 块）与 Go（5h/日/周/月全量出条）共用本路径。"""
        P = self._p
        c_name = INK if not stale else SOFT
        c_soft = SOFT_TXT if not stale else FAINT
        for k, w in enumerate(bars):
            self._codex_bar_block(m, right, top + CODEX_TEXT_Y + k * GO_BAR_PITCH,
                                  w, stale, c_name, c_soft)
        bottom = top + ROW_FULL + GO_BAR_PITCH * max(0, len(bars) - 2)
        self.hits.append((m - P(6), P(top), right + P(6), P(bottom),
                          {"u": u, "err": info["err"], "stale": stale}))
        return bottom

    def _codex_bar_block(self, m: float, right: float, ty: float, win: Window,
                         stale: bool, c_name: str, c_soft: str) -> None:
        """M14 单信息块（M24B Go 共用）：文字行中心在 ty，条占 ty+7 .. ty+7+9
        （几何语法=百炼 B 行）。label 短名一律无「窗」字（codex_win_caption M24B）。"""
        c, P = self.canvas, self._p
        pct = win.pct_used
        txt = (f"{codex_win_caption(win.label)} · 已用 {pct:.1%}" if pct is not None
               else f"{codex_win_caption(win.label)} · 暂无百分比")
        c.create_text(m, P(ty), anchor="w", font=self.f_tiny, fill=c_soft, text=txt)
        c.create_text(right, P(ty), anchor="e", font=self.f_small_b,
                      fill=c_name, text=fmt_countdown(win.resets_at))
        self._bar(m, P(ty + CODEX_TXT_BAR), right - m, P(9), pct,
                  STALE if stale else self._bar_color(pct))

    def _draw_err_row(self, y: float, info: dict, m: float, w: float) -> float:
        """从未成功过的失败行：明确状态文案，不渲染空值假象。"""
        c, P = self.canvas, self._p
        u: Usage = info["u"]
        code = u.error_code or "ERROR"
        right = w - m
        if code == "not_configured":
            status, col = "未配置凭据 · 待启用", SOFT
        elif info["cred"]:
            status, col = "需重新登录凭据", ORANGE
        else:
            status, col = f"拉取失败 · {code} · 自动重试中", SOFT
        c.create_text(m, P(y + 16), anchor="w", font=self.f_name, fill=SOFT,
                      text=NAMES.get(u.provider, u.provider))
        if info["cred"]:
            _warn, btn_txt, btn_cmd = self._cred_ui(u)   # 百炼=Cookie 面板；OpenAI/Go=密钥面板
            bx = self._click_pill(right, P(y + 11), btn_txt, btn_cmd, ORANGE)
            # REGION_BLOCKED 是环境态（fix-5 橙档），不能标成「凭据已失效」误导换 key
            tag = "地区受限" if code == "REGION_BLOCKED" else "凭据已失效"
            c.create_text(bx - P(10), P(y + 15), anchor="e", font=self.f_small_b,
                          fill=col, text=tag)
        else:
            c.create_text(right, P(y + 15), anchor="e", font=self.f_small_b, fill=col,
                          text=status)
        msg = (u.error_msg or "")[:70]
        if msg:
            c.create_text(m, P(y + 36), anchor="w", font=self.f_tiny, fill=FAINT,
                          text=msg)
        c.create_text(m, P(y + 50), anchor="w", font=self.f_tiny, fill=FAINT,
                      text="暂无可显示的历史数据")
        self.hits.append((m - P(6), P(y), right + P(6), P(y + ROW_ERR),
                          {"u": u, "err": u, "stale": False}))
        return y + ROW_ERR

    # ---- 阈值配色 ----

    def _bar_color(self, pct_used: float | None) -> str:
        if pct_used is None:
            return FAINT
        pr = 1.0 - pct_used
        if pr < self.low_red:
            return RED
        if pr < self.low_yellow:
            return YELLOW
        return OK
