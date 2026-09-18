# token-widget

A Windows sticky-note widget that keeps your LLM subscription quotas on the desktop — Bailian Token Plan · OpenCode Go · ChatGPT Codex, at a glance, no browser tab required.

![Demo: three provider rows, update dot, confirm dialog and download progress](docs/screenshots/demo.gif)

[![release](https://img.shields.io/github/v/release/WuJerry9376/token-widget)](https://github.com/WuJerry9376/token-widget/releases)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[Releases (download `TokenWidget.exe`)](https://github.com/WuJerry9376/token-widget/releases)

## Features

- **One file, nothing to install.** A single ~10.7 MB `TokenWidget.exe` for Windows 10/11 x64. The product code is Python standard library only — no runtime, no dependencies.
- **Three sources, one note.** Bailian Token Plan (7-day credits + booster pool + reset countdown), OpenCode Go (5h/weekly/monthly usage windows), and ChatGPT Codex plan windows (experimental). Each provider renders as one row on a paper-note card.
- **Edge snapping.** Drag it near a screen edge and it slides flush; window position is remembered across runs and monitors.
- **Self-update you actually confirm.** Version checks come from the GitHub Releases API at three quiet trigger points (startup / settings page / daily), a confirmation dialog shows version, date, size and release notes, and the download only starts when you click Update. Nothing is ever replaced silently.
- **Hash-anchored downloads.** Every staged binary is verified against the SHA-256 digest published by the official GitHub API. An optional mirror site may carry the bytes when your direct connection is unreliable — it never supplies version info or hashes.
- **Credentials stay on your machine.** Cookies and API keys are encrypted with Windows DPAPI, bound to your current user account; they never leave the machine except to the provider's own endpoint.
- **Proxy-aware.** HTTP/CONNECT proxies (typical Clash/V2Ray mixed port `127.0.0.1:7890`) can be scoped to OpenCode Go / Codex only. Bailian never goes through the proxy.

## Quick start

1. Download `TokenWidget.exe` from the [Releases page](https://github.com/WuJerry9376/token-widget/releases) and put it in any folder.
2. Double-click it. The note appears on your desktop and creates a `local\` folder beside the exe for config and data.
3. Right-click the note → Settings, tick the providers you use and bind their credentials (Bailian cookie / Go key / Codex token — step-by-step guides in the Appendix below).

> Windows SmartScreen may warn about an unsigned single-file build: *More info → Run anyway*. Local Defender scans in our testing report zero detections. Scans by other antivirus vendors may differ.

## Screenshots

| | |
|---|---|
| ![Main note: Bailian credits with plan-expiry note, OpenCode Go three windows, Codex plan bars](docs/screenshots/feature_note.png) | ![Settings: providers, proxy, update and display options](docs/screenshots/feature_settings.png) |
| *Main note* | *Settings* |
| ![Update dialog: version diff, release date, size and notes](docs/screenshots/feature_dialog.png) | ![After dragging close to the right edge, the note snaps flush](docs/screenshots/feature_snap.png) |
| *Update dialog* | *Edge snap (right edge)* |
| ![OpenCode Go stacked windows: 5h/day/week bars](docs/screenshots/feature_go3bars.png) | ![Close-up of the Codex row: two bars for the 5-hour and weekly windows](docs/screenshots/feature_dualbar.png) |
| *OpenCode Go three window bars* | *Codex dual progress bars* |

## Update & security

- **When it checks:** ~5 s after startup, when the Settings page opens, and once daily after 05:00 — merged under a 6-hour rate limit. Finding a new version lights a small orange dot on the note; clicking it jumps to Settings.
- **What it never does:** download or replace the exe on its own. Update happens only after you press *Update now* in the confirmation dialog; the swap runs as a one-shot script after exit, and your `local\` credentials and settings are untouched.
- **Where the bytes come from:** the asset of the latest GitHub Release. Version metadata and the SHA-256 trust anchor always come from the official GitHub API. If you paste a mirror URL, it is only used as a fallback carrier for the binary; mirror results without a matching hash are refused.
- **Where your credentials live:** DPAPI-encrypted files next to the exe (`local\*.dpapi`), decryptable only by your Windows user account on this machine. Copying them to another PC is useless by design.

## Build from source

```
Python 3.12 + Tkinter (product code imports stdlib only)

python main.py                    # run from source
pwsh -File tests\run_all_m9b.ps1  # full gate, currently 169 checks / 10 suites
pwsh -File build\build.ps1        # one-shot PyInstaller build (~20 s → dist\TokenWidget.exe)
python cli.py                     # console view of the same collected data
```

## Disclaimer & known limitations

- **Bailian** has no official quota API. This tool reads the console's undocumented read-only usage endpoint — the same path several open-source monitors take. Cookies expire and must be re-pasted; upstream changes can break collection at any time.
- **Codex** plan windows are read through a community-known, non-official ChatGPT backend endpoint. It is labelled *experimental* in the UI, disabled by default, and may stop working whenever OpenAI changes it.
- Everything this tool does is low-frequency, read-only polling (≥60 s per provider). It never calls inference/chat endpoints, never automates your subscription.
- Not affiliated with, endorsed by, or certified by Alibaba Cloud, OpenCode or OpenAI.

---

## 中文（精简版）

桌面便笺风额度浮窗：百炼 Token Plan / OpenCode Go / ChatGPT Codex 的余量、进度条与重置倒计时常驻桌面。

### 特性

- **单文件免安装**：约 10.7 MB 的 exe，产品代码仅用 Python 标准库；
- **三源聚合一窗**：百炼（7 天 Credits + 加油包）、OpenCode Go（5h/周/月窗口）、Codex（5h/周，实验性）；
- **贴边吸附**：拖近屏幕边缘自动贴齐，位置跨启动记忆；
- **自更新但不擅自更新**：三个低打扰触发点检查 GitHub Releases，发现新版弹确认窗，点「立即更新」才下载；绝不静默替换文件；
- **哈希信任锚**：包体一律按官方 API 下发的 SHA-256 校验；镜像源只是可选的"搬运工"，只碰二进制、不碰元数据；
- **凭据本机加密**：Cookie/key 以 DPAPI 加密存 exe 旁 `local\`，绑定本机本用户，异机无效；
- **代理兼容**：Clash/V2Ray 的 HTTP 混合端口可按供应商勾选启用（百炼永不走代理）。

### 快速上手

1. 到 [Releases 页](https://github.com/WuJerry9376/token-widget/releases) 下载 `TokenWidget.exe`；
2. 双击运行，exe 旁自动生成 `local\` 数据目录；
3. 右键浮窗 → 设置，勾选供应商并按附录指引绑定凭据。

### 界面一览

主浮窗 / 设置页 / 更新弹窗 / 贴边吸附 / OpenCode Go 三窗条 / Codex 双进度条——见上文截图（alt 文案对应）。

> **演示数据说明**：截图与动图中的数值均为演示数据（示例口径 35,772 / 「套餐 10-12 到期」/ 弹窗 v1.9.0 示例版本等），非真实账户数据。真实凭据态下各源常含橙色告警档，观感不佳，故演示数值注入的是渲染层（与真数据同一条渲染路径），界面排版与实机一致。

### 构建与验证

源码运行 `python main.py`；全量门禁 `pwsh -File tests\run_all_m9b.ps1`（10 套件 169 项）；打包 `pwsh -File build\build.ps1`。

### 诚实声明

百炼走控制台未公开只读接口（Cookie 会过期、上游改版可能失效）；Codex 用量为社区通用非官方端点（UI 已标注"实验性"，默认不启用）。本工具零自动化推理调用、全部为低频只读轮询；与上述厂商无关联。

---

## 附录 · 绑定与运维手册（自旧版 README 全文迁入）

### A1 首次绑定细节（最终用户步骤）

1. 取 `dist\TokenWidget.exe`（单文件，~10.6MB）放到任意目录
2. 首次运行自动创建同级 `local\` 并生成默认配置
3. 右键浮窗 → **设置…** → 勾选百炼后若提示"需重新登录凭据" → 点击行内 **"更新登录凭据…"**：
   - 浏览器打开并登录 `bailian.console.aliyun.com` → F12 网络 → 任选一条发往 `bailian-cs.console.aliyun.com` 的请求 → 复制 Request Headers 里完整 `Cookie` 值 → 粘贴保存
   - Cookie 仅以 DPAPI（当前 Windows 用户）加密存于本机 `local\bailian_cookie.dpapi`，不会外传；换电脑/换用户需重新粘贴
4. 可选：设置页打开"开机自启"（仅写 HKCU Run 的 `token-widget` 单值）；"总在最前"开关；轮询周期 60~3600s（默认 300s）
5. 余量颜色：剩余 <15% 黄、<5% 红；接口连续失败时灰显最后成功值并标注陈旧

### A2 显示语义

| 供应商 | 显示 | 数据源 | 备注 |
|---|---|---|---|
| 百炼个人版 | 7 天周期剩余 Credits + 重置倒计时；有 5h 数据时自动副显；加油包单列；分项行尾附「套餐 MM-DD 到期」（subscription.endTime；≤7 天转橙、≤3 天转红，跨年带年份；Go/Codex 无此字段永不显示） | 控制台网关（非官方契约，移植 CodexBar/OmniRoute 实测逻辑，见 `docs\bailian_gateway_spec.md`） | Cookie 过期会提示重贴；完整到期日+剩余天数在 tooltip |
| OpenCode Go | 5h/周/月窗口已用 % + 倒计时 | `zen/go/v1/usage`（Go key，`~/.local/share/opencode/auth.json` 的 `opencode-go` 条目） | 无绝对额度下发 |
| Codex（实验性） | 5h/周窗口已用 % + 重置倒计时；积分/重置券进 tooltip | ChatGPT 订阅 OAuth（见 A3） | 非官方接口，可能随时失效 |

### A3 如何绑定 OpenCode Go（M6 起"占位"已转真实；M11a 起本页不再含 OpenAI）

- 右键浮窗 → 设置… → 勾选 OpenCode Go（未绑定时自动弹出绑定面板；旁注"未绑定 · 点击配置"也可随时打开）。
- OpenCode Go：登录过 opencode 的机器自动检测 `~\.local\share\opencode\auth.json` 的 `opencode-go` 条目（可关），或手动粘贴 Go key；**Zen key 不通用**（该端点必 403），自动检测绝不采用。
- key 一律 DPAPI 加密存 `local\<name>.dpapi`；保存后输入框立即清空不回显；保存即验证一次，失败按错误码提示（密钥无效/无 Go 订阅等）。
- ~~OpenAI Admin key 绑定~~：**M11a（2026-09-15 用户裁决）整行移除**，`src/sources/openai.py` 与其凭据、设置项已删除；线路规格留档 `docs\openai_go_wire_spec.md` 备查。

### A4 Codex / ChatGPT Plan 窗口限额（M10，**实验性**）

- 第 4 家供应商「Codex（实验性）」：显示 ChatGPT 订阅的 Codex **5h / 周 窗口已用 % + 重置倒计时**（plan_type 做徽章；Pro 积分余额、窗口重置券计数进 tooltip）。
- ⚠️ 实验性声明：走 **非官方前端接口**（`chatgpt.com/backend-api/codex/usage`），ToS 灰区、仅只读低频（≥60s），**可能随时失效**；默认不启用，设置页手动勾选。
- token 自动读取（M10b，按序取第一个合格命中，仅 `auth_mode=chatgpt`）：① `local\auth.json`（frozen=exe 同级）→ ② 项目根 / exe 同级 `auth.json` → ③ `~\.codex\auth.json`（Codex CLI 登录产物）；面板显示"已自动检测：<来源路径>（尾 4 位）"。
- 异机/无 CLI 登录：设置页手动粘贴 access_token（DPAPI 加密存储）；token 任何时刻不回显、不进日志，与 OpenAI 平台 key 完全不互通。
- 请求需携带 `originator: codex_cli_rs` 等 CF 指纹头（已内置，见 `docs\codex_chatgpt_wire_spec.md`「CF 边缘指纹层」）。
- 国内需代理：在「网络代理 → 作用范围」勾选 Codex 项（同 Clash 混合端口即可）；401 提示「登录已过期」重贴 token，Cloudflare 拦截按网络档退避。

### A5 网络代理（M8，境外源在国内联网）

- OpenCode Go / Codex 在国内直连常被墙。设置页「网络代理」分组：勾选启用 → 填本地 HTTP 代理（典型 Clash/V2Ray 混合端口 `127.0.0.1:7890`，地址框与端口框分开填或合填 `host:port` 均可）→ 勾选作用范围（仅这两家，**百炼永不走代理**）。
- 仅支持 **HTTP/CONNECT 型代理**（`http://host:port`）；**不支持 socks**。代理 URL 可含 `http://user:pass@host:port` 认证段，但界面/日志/错误提示会脱敏为 `user:***@`。
- 「测试连通」按钮零凭据依赖：向探测端点发起，拿到任意 HTTP 状态码（含 401）即判「通道正常」，连接失败才报「通道未建立（检查代理地址/软件）」。
- 出口地区被上游封锁（Cloudflare 403 region）时会提示「切换海外节点」而非「密钥无效」（`REGION_BLOCKED` 已单独分类；「测试连通」同样橙字提示换节点）。
- 地址非法（无端口/socks/畸形）时按直连处理并给橙色提示；代理改动即存，下一轮采集（含设置面板内"测试/验证"）立即生效。

### A6 更新机制细节（M15-M19，GitHub Releases）

- 设置页「更新」分组：☑自动更新（默认开；**检查触发点=程序启动后 ~5s、打开设置页时、每日 5 点后首帧**，统一 6 小时频控合并）、当前版本、「镜像源（可选）」、「检查更新」手动按钮（无视频控）。
- 发现新版本的出口：主窗右下角 3px 橙点（仅"有未发现新版"时亮、零行高变化）——点击直达设置页并立即检查；无新版或检查失败自动灭。
- 更新源=GitHub Releases 最新 release 的 `TokenWidget.exe`；仓库默认 `WuJerry9376/token-widget`（已内置配置 DEFAULTS，可在 `local\config.json` 的 `update.repo` 覆盖，置空=未配置零网络）。github api 默认直连（proxy_targets 不含 update），直连失败且代理开启时自动经代理重试一次。
- **发现新版=专属弹窗确认（M19）**：手动点「检查更新」（或点橙点进设置页触发）发现新版 → 自动弹出确认窗：当前版本→新版本、发布时间、包大小、发行说明（≤6 行），底部「立即更新」/「取消」。点「立即更新」直接开始下载替换（弹窗即确认，无二次询问），窗内实时显示下载百分比与校验状态；失败给橙字原因+「重试」「关闭」，目录不可写时出「提权更新」（一次 UAC）。弹窗被取消后设置页状态行保留「发现新版 vY」+「查看」可随时重开。**定时/启动路径发现只亮橙点、不弹窗**（防打扰）。
- **镜像备用源（M18）**：设置页「镜像源（可选）」粘贴即用（如 `ghfast.top` 或 `https://ghfast.top/`，也兼容 `https://ghfast.top/https://…` 占位式——两者都规范化为「前缀+原URL」拼接存储）。下载回退链=**直连 → 代理（开启时）→ 镜像**，成功通道在状态行标注。**版本信息（检查/哈希）始终只走 GitHub 官方 API，镜像永不参与元数据**。注意：镜像是第三方服务，可读到你下载的字节，但有官方 API 下发的 SHA-256 哈希把关——`asset.digest` 存在则**必校验**（不符即删报错；镜像腿缺哈希直接拒收，直连/代理腿缺哈希放行并在状态说明）。
- **版本近况（v1.8.3，当前发布版）**：百炼行新增**套餐到期提示**（分项行尾「套餐 MM-DD 到期」，≤7 天转橙、≤3 天转红，跨年带年份，完整日期+剩余天数在 tooltip；Go/Codex 不显示）；刷新图标与内容层序统一（不再被文字/进度条压盖）；OpenCode Go 升级为 5h/日/周 **三主条堆叠**（标签去波浪号与「窗」字）；进度条高亮改绝对阈值（跨行不再互抢）；加油包单列。v1.8.2：设置页 foot 图标换官方 GitHub Invertocat 素材（FAINT/SOFT 两态、DPI 四档自适应、随 exe 打包）。v1.8.1：发现新版改专属弹窗确认。v1.8.0：foot GitHub 图标 + 镜像备用源 + SHA-256 校验。**完整版本历史以 [Releases 页](https://github.com/WuJerry9376/token-widget/releases) 为准。**
- **安全设计：定时路径只读发现、绝不自动下载**——下载与替换只在用户于确认弹窗点「立即更新」后发生；替换经一次性脚本在程序退出后完成（旧 exe 改名→新 exe 就位→自启→清理），`local\` 下凭据与设置零触碰。

### A7 移植到其他电脑

1. **只拷 `TokenWidget.exe` 一个文件**（目标机需 Windows 10/11 x64，免装 Python）。可选再拷 `local\config.json` 带走偏好；**不要拷 `bailian_cookie.dpapi`**——DPAPI 凭据与本机本用户绑定，异机必然解密失败（程序会安全降级为"需重新登录凭据"引导，不会崩）
2. 双击运行，首次启动自动在 exe 旁创建 `local\`；百炼行显示橙色"需重新登录凭据…"
3. 点该行胶囊 → 在**这台目标机的浏览器**登录 `bailian.console.aliyun.com` → F12 网络 → 任选一条发往 `bailian-cs` 的请求 → 复制完整 `Cookie` 粘贴保存（本机 DPAPI 重新加密）
4. 被 SmartScreen/杀软拦时：属性→解除锁定，或加白名单（未签名单文件打包的常见误报；本机 Defender 实测 0 检出；其他杀软厂商结果可能不同）
5. 开机自启按需在设置页开启（写当前用户 HKCU，逐台各自设置）；多屏拖动位置自动记忆
6. 多台机器可同时跑同一账户（只读低频轮询互不冲突）；任一台上重新登录阿里云可能使旧 Cookie 失效，届时该机按提示重贴即可

### A8 开发与构建目录

- 技术栈：Python 3.12 + Tkinter，**运行时零第三方依赖**（stdlib only；仅 dev 取证/素材工具用 PIL）
- 目录：`src/`（sources=采集适配层，ui/scheduler/settings_panel=浮窗，auth=DPAPI 凭据，autostart=注册表单值）· `scripts/probe_api.py`（M0 连通 probe）· `tests/`（渲染/设置/异常注入自测）· `build/`（spec/图标/一键打包，详见 `build\README.md`）
- CLI 采集自测：`python cli.py`
- 计划与验收：`PLAN.md` · `docs\M5_acceptance_checklist.md`

### A9 合规与风险须知

- 百炼个人版无官方余量 API，本工具使用其控制台只读查询接口（与多个开源监控工具同路径），**上游改版可能失效**；查询频率 ≥60s，不做任何自动化推理调用
- 请勿将 `local\bailian_cookie.dpapi` 发给他人——它等价于你的控制台登录态

### License

[MIT](LICENSE) · Copyright (c) 2026 Jerry Wu
