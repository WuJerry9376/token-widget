# token-widget

A Windows sticky-note widget that keeps your LLM subscription quotas on the desktop — Bailian Token Plan · OpenCode Go · ChatGPT Codex, at a glance, no browser tab required.

![Main note: Bailian credits with plan-expiry note, OpenCode Go three windows, Codex plan bars](docs/screenshots/feature_note.png)

[![release](https://img.shields.io/github/v/release/WuJerry9376/token-widget)](https://github.com/WuJerry9376/token-widget/releases)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[Releases (download `TokenWidget.exe`)](https://github.com/WuJerry9376/token-widget/releases)

> Screenshots use demo data (35,772 credits, "plan 12-31", dialog v1.8.1→v1.9.0 etc.) injected at the render layer — layout and code paths are identical to a live run.

## Features

- **One file, nothing to install.** A single ~10.7 MB `TokenWidget.exe` for Windows 10/11 x64. The product code is Python standard library only — no runtime, no dependencies.
- **Three sources, one note.** Bailian Token Plan (7-day credits + booster pool + plan expiry + reset countdown), OpenCode Go (5h/day/week usage bars), and ChatGPT Codex plan windows (experimental). Each provider renders as one row on a paper-note card.
- **Edge snapping.** Drag it near a screen edge and it slides flush; window position is remembered across runs and monitors.
- **Self-update you actually confirm.** Version checks come from the GitHub Releases API at three quiet trigger points (startup / settings page / daily), a confirmation dialog shows version, date, size and release notes, and the download only starts when you click Update. Nothing is ever replaced silently.
- **Hash-anchored downloads.** Every staged binary is verified against the SHA-256 digest published by the official GitHub API. An optional mirror site may carry the bytes when your direct connection is unreliable — it never supplies version info or hashes.
- **Credentials stay on your machine.** Cookies and API keys are encrypted with Windows DPAPI, bound to your current user account; they never leave the machine except to the provider's own endpoint.
- **Proxy-aware.** HTTP/CONNECT proxies (typical Clash/V2Ray mixed port `127.0.0.1:7890`) can be scoped to OpenCode Go / Codex only. Bailian never goes through the proxy.

## Getting started

1. **Download** `TokenWidget.exe` from the [Releases page](https://github.com/WuJerry9376/token-widget/releases) and drop it in any folder. Windows SmartScreen may warn about an unsigned single-file build: *More info → Run anyway*. Local Defender scans in our testing report zero detections; other antivirus vendors may differ.
2. **Double-click it.** A paper note appears on your desktop and a `local\` folder is created beside the exe (config, data, encrypted credentials — all there, nothing elsewhere).
3. **Three things worth doing on first run:** drag the note near a screen edge (it snaps and remembers); right-click → **设置…** (Settings) to pick providers, polling interval, always-on-top and autostart; bind the accounts you use (next section).

## Binding your accounts

### Bailian Token Plan

- **What you paste:** your console session Cookie (one string). The tool only reads usage data with it.
- **Where to get it:** log in to `bailian.console.aliyun.com` in your browser → F12 → Network → click any request going to `bailian-cs.console.aliyun.com` → copy the full `Cookie` request-header value.
- **Where to paste:** Settings → tick *百炼 Token Plan* → the row's **"更新登录凭据…"** opens the paste dialog. It is saved DPAPI-encrypted and never re-displayed.
- Cookies expire (re-paste when the row turns orange); DPAPI binds them to this Windows user, so each PC pastes its own.

### OpenCode Go

- **What you paste:** an OpenCode **Go** key (a Zen key will not work — the usage endpoint rejects it).
- **Automatic:** if you signed in to opencode on this machine, `~\.local\share\opencode\auth.json` is detected (can be turned off).
- **Where to paste:** Settings → tick *OpenCode Go* → the bind panel opens (also via the row's "点击配置" note). Saved encrypted, verified once on save, never re-displayed.

### ChatGPT Codex (experimental)

- **What it uses:** the ChatGPT OAuth token from your Codex CLI login (`~\.codex\auth.json`, or drop an `auth.json` next to the exe); otherwise paste the access token in the bind panel.
- **Experimental by nature:** a community-known non-official endpoint, disabled by default, labelled in the UI; it may stop working whenever OpenAI changes it. A 401 shows "登录已过期" — re-paste or re-login.
- Not the OpenAI platform API key; the two never mix.

## Proxy (Clash users, read this)

- Overseas sources (OpenCode Go / Codex) are usually blocked in direct connections from mainland China. In Settings → **网络代理**: enable, enter `127.0.0.1` + `7890` (your Clash/V2Ray mixed HTTP port), and tick which providers use it. **Bailian never goes through the proxy.**
- HTTP/CONNECT proxies only (no socks); **测试连通** needs no credentials — any HTTP response back means the channel works.

## Updates

- Checks run at three quiet points (startup / opening Settings / daily after 05:00) with a 6-hour rate limit. A small orange dot on the note means "new version found" — click it, review the dialog (versions, date, size, notes), and only then does anything download. Version info and the SHA-256 anchor always come from the official GitHub API; an optional mirror only carries bytes.
- From v1.9.1 the swap is script-free (the new instance renames itself into place: no console flash, no "Security validation" popup). **One-time transition:** upgrading v1.9.0→v1.9.1 still runs the old script and may show that popup or not auto-restart once — the replacement did succeed, just launch it again; from 1.9.1 onward it is clean.
- Full release notes: [Releases](https://github.com/WuJerry9376/token-widget/releases).

## Moving to another PC

- Copy the **exe only** (optionally `local\config.json` for preferences). Do not copy `local\*.dpapi` files — DPAPI secrets cannot decrypt on another machine; just re-paste credentials there.
- Multi-monitor position and settings are per-machine; autostart is set per machine in Settings.
- Several machines may run the same account concurrently (low-frequency read-only polling); a fresh Aliyun login can invalidate an older cookie — re-paste when asked.

## Privacy & safety

- Credentials are DPAPI-encrypted files beside the exe, readable only by your Windows user on this machine — and by nothing else. Never send `local\bailian_cookie.dpapi` to anyone; it equals your console login.
- The tool makes low-frequency, read-only requests only: each provider's usage endpoint (optionally via your proxy) and the GitHub Releases API. No inference calls, no telemetry, no update server of its own.

## Troubleshooting

| What you see on the note | Meaning | What to do |
|---|---|---|
| Orange "需重新登录凭据（Cookie 过期）" | Bailian cookie expired | Row button → re-paste cookie |
| Orange "出口地区受限 · 切换海外节点后自动恢复" | Provider region-blocks your exit IP | Switch to an overseas node; row's 立即重试 recovers |
| Orange "登录已过期 · 重新获取 access token" | Codex token expired | Re-paste token or re-login Codex CLI |
| Small orange dot, bottom-right | New version found | Click → Settings → confirm dialog |
| Grey row + "旧数据" tag | Last fetch failed; showing last good value | Auto-retrying with backoff — check network/proxy |
| Yellow / red bar | <15% / <5% quota left | Nothing wrong — that is the alert working |

## Screenshots

| | |
|---|---|
| ![Settings: providers, proxy, update and display options](docs/screenshots/feature_settings.png) | ![Update dialog: version diff, release date, size and notes](docs/screenshots/feature_dialog.png) |
| *Settings* | *Update dialog* |
| ![After dragging close to the right edge, the note snaps flush](docs/screenshots/feature_snap.png) | ![OpenCode Go stacked windows: 5h/day/week bars](docs/screenshots/feature_go3bars.png) |
| *Edge snap (right edge)* | *OpenCode Go three window bars* |
| ![Close-up of the Codex row: two bars for the 5-hour and weekly windows](docs/screenshots/feature_dualbar.png) | |
| *Codex dual progress bars* | |

## Disclaimer & known limitations

- **Bailian** has no official quota API. This tool reads the console's undocumented read-only usage endpoint — the same path several open-source monitors take. Cookies expire and must be re-pasted; upstream changes can break collection at any time.
- **Codex** plan windows are read through a community-known, non-official ChatGPT backend endpoint. It is labelled *experimental* in the UI, disabled by default, and may stop working whenever OpenAI changes it.
- Everything this tool does is low-frequency, read-only polling (≥60 s per provider). It never calls inference/chat endpoints, never automates your subscription.
- Not affiliated with, endorsed by, or certified by Alibaba Cloud, OpenCode or OpenAI.

## For developers

Python 3.12 + Tkinter, product code stdlib-only. Run from source: `python main.py`; data check: `python cli.py`; full gate: `pwsh -File tests\run_all_m9b.ps1` (10 suites, 187 checks); build: `pwsh -File build\build.ps1` (~20 s → `dist\TokenWidget.exe`, details in [build/README.md](build/README.md)). Wire specs, the complete operations manual and the dev-only asset tools (incl. `tools/make_gif.py`, kept for offline re-shoots; the README no longer embeds the demo GIF) live in [docs/](docs/).

---

## 中文（精简版）

桌面便笺风额度浮窗：百炼 Token Plan / OpenCode Go / ChatGPT Codex 的余量、进度条与重置倒计时常驻桌面。

### 快速上手

1. [Releases 页](https://github.com/WuJerry9376/token-widget/releases) 下载单文件 `TokenWidget.exe`（SmartScreen 提示时「更多信息→仍要运行」）；
2. 双击运行，exe 旁自动生成 `local\` 数据目录（凭据加密也存那里）；
3. 首次三件事：拖到屏幕边缘试吸附；右键→设置选供应商/轮询/置顶/自启；绑定账户（见下）。

### 绑定账户

- **百炼**：浏览器登录 `bailian.console.aliyun.com` → F12 网络 → 任选一条发往 `bailian-cs` 的请求 → 复制完整 `Cookie` → 设置页勾选后在弹层粘贴。Cookie 会过期，橙字提示时重贴。
- **OpenCode Go**：Go key（Zen key 不通用）；登录过 opencode 的机器可自动检测，或设置页手动粘贴。
- **Codex（实验性）**：读你 Codex CLI 的 ChatGPT 登录 token（`~\.codex\auth.json`），也可手动粘贴；非官方接口、默认不启用，401 时提示重贴。

### 代理

国内直连不动这两家境外源时：设置页「网络代理」勾选启用 → 填 Clash/V2Ray 混合端口（如 `127.0.0.1:7890`）→ 按供应商勾选作用范围。**百炼永不走代理**；仅支持 HTTP 型代理；「测试连通」不依赖凭据。

### 更新

三个低打扰触发点检查 GitHub Releases；橙点=发现新版，点击进确认弹窗，点「立即更新」才下载，包体按官方 API 哈希校验、绝不静默替换。**v1.9.1 起替换重启全程无黑窗无弹窗；唯一一次过渡：v1.9.0→v1.9.1 本次可能再见一次旧脚本弹窗——替换已成功，双击即新版。** 完整版本记录见 Releases 页。

### 换电脑与隐私

只拷 exe（偏好可拷 `local\config.json`）；DPAPI 凭据异机解不开，目标机重新粘贴即可。凭据仅本机本用户可读、绝不上传；所有请求=各供应商只读用量端点+GitHub API，低频轮询、零自动化调用。

### 界面一览

主浮窗（顶部大图）+ 截图区五幅：设置页 / 更新弹窗 / 贴边吸附 / OpenCode Go 三窗条 / Codex 双进度条。**截图数值均为演示数据**（注入渲染层，与真数据同一条路径，排版与实机一致）；真实凭据态下常含橙色告警档，观感不佳，故门面用健康态演示值。

### 诚实声明

百炼走控制台未公开只读接口（Cookie 会过期、上游改版可能失效）；Codex 用量为社区通用非官方端点（UI 已标注"实验性"，默认不启用）。本工具零自动化推理调用、全部为低频只读轮询；与上述厂商无关联。

---

## License

[MIT](LICENSE) · Copyright (c) 2026 Jerry Wu
