# 运维手册（token-widget）

本文自 README 附录（A1-A9）整体迁入：**面向开发者与运维的全量细节**。
README 只保留使用者视角的指引，此处保真备查。版本行为速览以
[Releases](https://github.com/WuJerry9376/token-widget/releases) 为准。

## 目录

- [A1 首次绑定细节（最终用户步骤）](#a1-首次绑定细节最终用户步骤)
- [A2 显示语义](#a2-显示语义)
- [A3 如何绑定 OpenCode Go](#a3-如何绑定-opencode-go)
- [A4 Codex / ChatGPT Plan 窗口限额（实验性）](#a4-codex--chatgpt-plan-窗口限额实验性)
- [A5 网络代理（M8）](#a5-网络代理m8)
- [A6 更新机制细节（M15-M28）](#a6-更新机制细节m15-m28)
- [A7 移植到其他电脑](#a7-移植到其他电脑)
- [A8 开发与构建目录](#a8-开发与构建目录)
- [A9 合规与风险须知](#a9-合规与风险须知)

## A1 首次绑定细节（最终用户步骤）

1. 取 `dist\TokenWidget.exe`（单文件，~10.6MB）放到任意目录
2. 首次运行自动创建同级 `local\` 并生成默认配置
3. 右键浮窗 → **设置…** → 勾选百炼后若提示"需重新登录凭据" → 点击行内 **"更新登录凭据…"**：
   - 浏览器打开并登录 `bailian.console.aliyun.com` → F12 网络 → 任选一条发往 `bailian-cs.console.aliyun.com` 的请求 → 复制 Request Headers 里完整 `Cookie` 值 → 粘贴保存
   - Cookie 仅以 DPAPI（当前 Windows 用户）加密存于本机 `local\bailian_cookie.dpapi`，不会外传；换电脑/换用户需重新粘贴
4. 可选：设置页打开"开机自启"（仅写 HKCU Run 的 `token-widget` 单值）；"总在最前"开关；轮询周期 60~3600s（默认 300s）
5. 余量颜色：剩余 <15% 黄、<5% 红；接口连续失败时灰显最后成功值并标注陈旧

## A2 显示语义

| 供应商 | 显示 | 数据源 | 备注 |
|---|---|---|---|
| 百炼个人版 | 7 天周期剩余 Credits + 重置倒计时；有 5h 数据时自动副显；加油包单列；分项行尾附「套餐 MM-DD 到期」（subscription.endTime；≤7 天转橙、≤3 天转红，跨年带年份；Go/Codex 无此字段永不显示） | 控制台网关（非官方契约，移植 CodexBar/OmniRoute 实测逻辑，见 `bailian_gateway_spec.md`） | Cookie 过期会提示重贴；完整到期日+剩余天数在 tooltip |
| OpenCode Go | 5h/周/月已用 % + 倒计时（M25：UI 文案去「窗口」字样） | `zen/go/v1/usage`（Go key，`~/.local/share/opencode/auth.json` 的 `opencode-go` 条目） | 无绝对额度下发 |
| Codex（实验性） | 5h/周已用 % + 重置倒计时；积分/重置券进 tooltip | ChatGPT 订阅 OAuth（见 A3） | 非官方接口，可能随时失效 |

## A3 如何绑定 OpenCode Go

- 右键浮窗 → 设置… → 勾选 OpenCode Go（未绑定时自动弹出绑定面板；旁注"未绑定 · 点击配置"也可随时打开）。
- OpenCode Go：登录过 opencode 的机器自动检测 `~\.local\share\opencode\auth.json` 的 `opencode-go` 条目（可关），或手动粘贴 Go key；**Zen key 不通用**（该端点必 403），自动检测绝不采用。
- key 一律 DPAPI 加密存 `local\<name>.dpapi`；保存后输入框立即清空不回显；保存即验证一次，失败按错误码提示（密钥无效/无 Go 订阅等）。
- ~~OpenAI Admin key 绑定~~：**M11a（2026-09-15 用户裁决）整行移除**，`src/sources/openai.py` 与其凭据、设置项已删除；线路规格留档 `openai_go_wire_spec.md` 备查。

## A4 Codex / ChatGPT Plan 窗口限额（M10，**实验性**）

- 第 4 家供应商「Codex（实验性）」：显示 ChatGPT 订阅的 Codex **5h / 周 已用 % + 重置倒计时**（plan_type 做徽章；Pro 积分余额、窗口重置券计数进 tooltip）。
- ⚠️ 实验性声明：走 **非官方前端接口**（`chatgpt.com/backend-api/codex/usage`），ToS 灰区、仅只读低频（≥60s），**可能随时失效**；默认不启用，设置页手动勾选。
- token 自动读取（M10b，按序取第一个合格命中，仅 `auth_mode=chatgpt`）：① `local\auth.json`（frozen=exe 同级）→ ② 项目根 / exe 同级 `auth.json` → ③ `~\.codex\auth.json`（Codex CLI 登录产物）；面板显示"已自动检测：<来源路径>（尾 4 位）"。
- 异机/无 CLI 登录：设置页手动粘贴 access_token（DPAPI 加密存储）；token 任何时刻不回显、不进日志，与 OpenAI 平台 key 完全不互通。
- 请求需携带 `originator: codex_cli_rs` 等 CF 指纹头（已内置，见 `codex_chatgpt_wire_spec.md`「CF 边缘指纹层」）。
- 国内需代理：在「网络代理 → 作用范围」勾选 Codex 项（同 Clash 混合端口即可）；401 提示「登录已过期」重贴 token，Cloudflare 拦截按网络档退避。

## A5 网络代理（M8，境外源在国内联网）

- OpenCode Go / Codex 在国内直连常被墙。设置页「网络代理」分组：勾选启用 → 填本地 HTTP 代理（典型 Clash/V2Ray 混合端口 `127.0.0.1:7890`，地址框与端口框分开填或合填 `host:port` 均可）→ 勾选作用范围（仅这两家，**百炼永不走代理**）。
- 仅支持 **HTTP/CONNECT 型代理**（`http://host:port`）；**不支持 socks**。代理 URL 可含 `http://user:pass@host:port` 认证段，但界面/日志/错误提示会脱敏为 `user:***@`。
- 「测试连通」按钮零凭据依赖：向探测端点发起，拿到任意 HTTP 状态码（含 401）即判「通道正常」，连接失败才报「通道未建立（检查代理地址/软件）」。
- 出口地区被上游封锁（Cloudflare 403 region）时会提示「切换海外节点」而非「密钥无效」（`REGION_BLOCKED` 已单独分类；「测试连通」同样橙字提示换节点）。
- 地址非法（无端口/socks/畸形）时按直连处理并给橙色提示；代理改动即存，下一轮采集（含设置面板内"测试/验证"）立即生效。

## A6 更新机制细节（M15-M28，GitHub Releases）

- 设置页「更新」分组：☑自动更新（默认开；**检查触发点=程序启动后 ~5s、打开设置页时、每日 5 点后首帧**，统一 6 小时频控合并）、当前版本、「镜像源（可选）」、「检查更新」手动按钮（无视频控）。
- 发现新版本的出口：主窗右下角 3px 橙点（仅"有未发现新版"时亮、零行高变化）——点击直达设置页并立即检查；无新版或检查失败自动灭。
- 更新源=GitHub Releases 最新 release 的 `TokenWidget.exe`；仓库默认 `WuJerry9376/token-widget`（已内置配置 DEFAULTS，可在 `local\config.json` 的 `update.repo` 覆盖，置空=未配置零网络）。github api 默认直连（proxy_targets 不含 update），直连失败且代理开启时自动经代理重试一次。
- **发现新版=专属弹窗确认（M19）**：手动点「检查更新」（或点橙点进设置页触发）发现新版 → 自动弹出确认窗：当前版本→新版本、发布时间、包大小、发行说明（≤6 行），底部「立即更新」/「取消」。点「立即更新」直接开始下载替换（弹窗即确认，无二次询问），窗内实时显示下载百分比与校验状态；失败给橙字原因+「重试」「关闭」，目录不可写时出「提权更新」（一次 UAC）。弹窗被取消后设置页状态行保留「发现新版 vY」+「查看」可随时重开。**定时/启动路径发现只亮橙点、不弹窗**（防打扰）。
- **镜像备用源（M18）**：设置页「镜像源（可选）」粘贴即用（如 `ghfast.top` 或 `https://ghfast.top/`，也兼容 `https://ghfast.top/https://…` 占位式——两者都规范化为「前缀+原URL」拼接存储）。下载回退链=**直连 → 代理（开启时）→ 镜像**，成功通道在状态行标注。**版本信息（检查/哈希）始终只走 GitHub 官方 API，镜像永不参与元数据**。注意：镜像是第三方服务，可读到你下载的字节，但有官方 API 下发的 SHA-256 哈希把关——`asset.digest` 存在则**必校验**（不符即删报错；镜像腿缺哈希直接拒收，直连/代理腿缺哈希放行并在状态说明）。
- **升级重启机制（M28，v1.9.1 起生效）**：下载校验完成后的替换重启不再经任何命令行脚本——新版本实例直接接管改名，**全程无黑窗闪现、无「Security validation failure」弹窗**；改名失败仍有橙字提醒与提权出路（行为不变）。⚠️ 过渡期须知：**v1.9.0→v1.9.1 本次升级仍由旧脚本执行，可能再见一次 Security validation 弹窗/未自动重启——替换已成功，双击即新版；自 1.9.1 起全程无弹窗无黑窗。**
- **版本近况（v1.9.1，当前发布版）**：更新链去 cmd 化（M28）——替换重启由新实例自我接管改名，无弹窗、无黑窗；⚠️ 唯一一次过渡：**v1.9.0→v1.9.1 本次升级仍由旧脚本执行，可能再见一次 Security validation 弹窗/未自动重启——替换已成功，双击即新版；自 1.9.1 起全程无弹窗无黑窗**。v1.9.0：**Per-Monitor v2 DPI 感知**（混合缩放多屏拖拽文字始终清晰、跨屏/改缩放 250ms 内自动重缩放）+ UI 文案全面去「窗口」字样。v1.8.3：百炼套餐到期提示（≤7 天橙/≤3 天红）+ 刷新图标层序统一 + Go 三主条 + 高光绝对阈值。v1.8.2：foot 图标换官方 GitHub Invertocat 素材。v1.8.1：发现新版改专属弹窗确认。v1.8.0：foot GitHub 图标 + 镜像备用源 + SHA-256 校验。**完整版本历史以 [Releases 页](https://github.com/WuJerry9376/token-widget/releases) 为准。**
- **安全设计：定时路径只读发现、绝不自动下载**——下载与替换只在用户于确认弹窗点「立即更新」后发生；替换由 staged 新实例在旧进程退出后完成改名序列（旧 exe 改名→新 exe 正名就位→清残留，M28 起不经任何命令行脚本），`local\` 下凭据与设置零触碰。

## A7 移植到其他电脑

1. **只拷 `TokenWidget.exe` 一个文件**（目标机需 Windows 10/11 x64，免装 Python）。可选再拷 `local\config.json` 带走偏好；**不要拷 `bailian_cookie.dpapi`**——DPAPI 凭据与本机本用户绑定，异机必然解密失败（程序会安全降级为"需重新登录凭据"引导，不会崩）
2. 双击运行，首次启动自动在 exe 旁创建 `local\`；百炼行显示橙色"需重新登录凭据…"
3. 点该行胶囊 → 在**这台目标机的浏览器**登录 `bailian.console.aliyun.com` → F12 网络 → 任选一条发往 `bailian-cs` 的请求 → 复制完整 `Cookie` 粘贴保存（本机 DPAPI 重新加密）
4. 被 SmartScreen/杀软拦时：属性→解除锁定，或加白名单（未签名单文件打包的常见误报；本机 Defender 实测 0 检出；其他杀软厂商结果可能不同）
5. 开机自启按需在设置页开启（写当前用户 HKCU，逐台各自设置）；多屏拖动位置自动记忆
6. 多台机器可同时跑同一账户（只读低频轮询互不冲突）；任一台上重新登录阿里云可能使旧 Cookie 失效，届时该机按提示重贴即可

## A8 开发与构建目录

- 技术栈：Python 3.12 + Tkinter，**运行时零第三方依赖**（stdlib only；仅 dev 取证/素材工具用 PIL）
- 目录：`src/`（sources=采集适配层，ui/scheduler/settings_panel=浮窗，auth=DPAPI 凭据，autostart=注册表单值）· `scripts/probe_api.py`（M0 连通 probe）· `tests/`（渲染/设置/异常注入自测）· `build/`（spec/图标/一键打包，详见 `../build/README.md`）
- CLI 采集自测：`python cli.py`
- 计划与验收：`../PLAN.md` · `M5_acceptance_checklist.md`

## A9 合规与风险须知

- 百炼个人版无官方余量 API，本工具使用其控制台只读查询接口（与多个开源监控工具同路径），**上游改版可能失效**；查询频率 ≥60s，不做任何自动化推理调用
- 请勿将 `local\bailian_cookie.dpapi` 发给他人——它等价于你的控制台登录态

## 门面素材工具

- `tools/make_gif.py`：demo 动图的离屏实拍+合成工具（README 已下线动图，保留可重摄能力；产物路径仍指向 docs/screenshots，重跑前注意）。
- 截图墙：`tests/capture_m20.py`（v1.8.x 系列）与 `local/` 下临时门面脚本产出；重拍走 `tests/capture_m22.py / capture_m24.py`（演示数据注入渲染层，与真数据同路径）。
