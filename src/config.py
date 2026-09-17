"""本地配置：token-widget/local/config.json 读写（PLAN.md §4 config.py）。

不存在则生成默认值并落盘；poll_seconds 下限 60s（PLAN §1 合规约束：低频只读）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# frozen（PyInstaller onefile）时 __file__ 指向临时解包目录，local/ 必须落在 exe 同级
if getattr(sys, "frozen", False):
    LOCAL_DIR = Path(sys.executable).resolve().parent / "local"
else:
    LOCAL_DIR = Path(__file__).resolve().parent.parent / "local"
CONFIG_PATH = LOCAL_DIR / "config.json"

POLL_MIN_SECONDS = 60

DEFAULTS: dict = {
    "poll_seconds": 300,            # 轮询周期（下限 60）
    "low_yellow_pct": 0.15,         # 剩余 <15% 黄
    "low_red_pct": 0.05,            # 剩余 <5% 红
    "always_on_top": True,
    "autostart": False,
    "enabled_providers": ["bailian"],
    # M6：OpenCode Go 配置节（auto_detect=是否允许从 opencode auth.json 自动检测 Go key）
    # M11a（2026-09-15 用户裁决）：OpenAI API 侧移除，config.openai 节随 source 一并删除
    "opencode_go": {"auto_detect": True},
    # M8：网络代理（HTTP/CONNECT，仅境外源；proxy_url 存原始用户输入，经
    # netconfig.normalize_proxy_url 规范化后使用；百炼永不走此通道）。
    # M10：targets 可含 "codex"（chatgpt.com 亦需海外出口）。
    "network": {"proxy_enabled": False, "proxy_url": "",
                "proxy_targets": ["opencode_go", "codex"]},
    # M15：更新（GitHub Releases）。repo="owner/name"（空=未配置，UI 提示、零网络）；
    # enabled=定时检查开关（**下载/替换仅用户明确动作**）；last_check=上次检查 epoch 秒。
    "update": {"enabled": True, "repo": "", "last_check": 0},
}


def _merge_sections(cfg: dict) -> dict:
    """dict 型配置节与 DEFAULTS 逐项合并（老 config 无这些键/只有部分键也向后兼容）。"""
    for key, dv in DEFAULTS.items():
        if isinstance(dv, dict):
            sec = dict(dv)
            sv = cfg.get(key)
            if isinstance(sv, dict):
                sec.update(sv)
            cfg[key] = sec
    return cfg


def _clamp(cfg: dict) -> dict:
    try:
        cfg["poll_seconds"] = max(POLL_MIN_SECONDS, int(cfg.get("poll_seconds", 300)))
    except (TypeError, ValueError):
        cfg["poll_seconds"] = DEFAULTS["poll_seconds"]
    return cfg


def load_config() -> dict:
    """读取配置；文件不存在/损坏则生成默认值并保存。已存键与默认值合并（含 dict 节）。"""
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                return _clamp(_merge_sections({**DEFAULTS, **saved}))
        except (ValueError, OSError):
            pass
    cfg = _clamp(_merge_sections(dict(DEFAULTS)))
    save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(_clamp(cfg), ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
