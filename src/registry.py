"""供应商适配器注册表（PLAN.md §4 registry.py）。"""
from __future__ import annotations

from .sources.base import ProviderSource
from .sources.bailian import BailianSource
from .sources.codex import CodexSource
from .sources.opencode_go import OpenCodeGoSource

SOURCES: dict[str, ProviderSource] = {
    s.name: s for s in (BailianSource(), OpenCodeGoSource(),
                        CodexSource())        # M10：codex 实验性（enabled_by_default=False）
                                            # M11a（2026-09-15）：OpenAI API 侧按用户裁决移除
}


def active_sources(cfg: dict) -> list[ProviderSource]:
    """按配置 enabled_providers 过滤；未知键静默跳过。"""
    enabled = cfg.get("enabled_providers")
    if not isinstance(enabled, list):
        enabled = [n for n, s in SOURCES.items() if s.enabled_by_default]
    return [SOURCES[name] for name in enabled if name in SOURCES]
