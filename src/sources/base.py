"""M1 采集层基础模型：统一 Usage 数据类 + ProviderSource 抽象基类。

规格来源：PLAN.md §4（sources/base.py）+ 任务书。stdlib-only。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Window:
    """单个计量窗口（如百炼 7d / 5h；OpenCode Go rolling / weekly / monthly）。"""

    label: str                        # "7d" | "5h" | "rolling" | "weekly" | "monthly" | ...
    pct_used: float | None = None     # 0..1（防御性归一后）
    resets_at: datetime | None = None


@dataclass
class Usage:
    """一次采集的统一结果。上层（UI/CLI）只消费本模型，不感知供应商协议。

    字段语义：
    - total/remaining/used：绝对额度（unit 同单位）；无绝对额概念时可为 None
    - pct_used：主窗口已用百分比（0..1），百炼=per1WeekPercentage
    - addon_remaining：附加包（百炼用量包）剩余合计，单独展示用
    - note：可选单行补充文案（tooltip 有则显，无则不显；无 PII、无凭据值）
    - stale_from_ok：上层缓存降级标记（失败后保留最后成功值灰显），采集层不写
    """

    provider: str
    ok: bool
    spec: str | None = None           # 档位（lite/standard/pro/max 等）
    unit: str = "credits"             # "credits" | "usd" | "percent"
    used: float | None = None
    total: float | None = None
    remaining: float | None = None
    pct_used: float | None = None     # 0..1
    resets_at: datetime | None = None
    windows: list[Window] = field(default_factory=list)
    addon_remaining: float | None = None
    note: str | None = None           # 单行补充信息（M10b：如窗口重置券计数）；UI tooltip 有则显
    error_code: str | None = None
    error_msg: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stale_from_ok: bool = False


class ProviderSource(ABC):
    """供应商采集适配器抽象。fetch() 必须自行容错，返回 Usage 而非抛异常。"""

    name: str = ""
    enabled_by_default: bool = True

    @abstractmethod
    def fetch(self) -> Usage:
        """执行一次采集（实现内应做进程内缓存/节流，供上层调度）。"""
        raise NotImplementedError
