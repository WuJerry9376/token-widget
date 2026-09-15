# Token 余量浮窗（token-widget）

桌面便笺风小部件：常驻显示各 LLM 订阅/账户的额度余量。实装阿里云百炼 Token Plan 个人版 + OpenCode Go（真实采集）+ Codex/ChatGPT Plan 窗口限额（实验性）。（M11a 起 OpenAI API 侧按用户裁决移除。）

## 快速开始（最终用户）

1. 取 `dist\TokenWidget.exe`（单文件，~10.6MB）放到任意目录
2. 首次运行自动创建同级 `local\` 并生成默认配置
3. 右键浮窗 → **设置…** → 勾选百炼后若提示"需重新登录凭据" → 点击行内 **"更新登录凭据…"**：
   - 浏览器打开并登录 `bailian.console.aliyun.com` → F12 网络 → 任选一条发往 `bailian-cs.console.aliyun.com` 的请求 → 复制 Request Headers 里完整 `Cookie` 值 → 粘贴保存
   - Cookie 仅以 DPAPI（当前 Windows 用户）加密存于本机 `local\bailian_cookie.dpapi`，不会外传；换电脑/换用户需重新粘贴
4. 可选：设置页打开"开机自启"（仅写 HKCU Run 的 `token-widget` 单值）；"总在最前"开关；轮询周期 60~3600s（默认 300s）
5. 余量颜色：剩余 <15% 黄、<5% 红；接口连续失败时灰显最后成功值并标注陈旧

## 显示语义

| 供应商 | 显示 | 数据源 | 备注 |
|---|---|---|---|
| 百炼个人版 | 7 天周期剩余 Credits + 重置倒计时；有 5h 数据时自动副显；加油包单列 | 控制台网关（非官方契约，移植 CodexBar/OmniRoute 实测逻辑，见 `docs\bailian_gateway_spec.md`） | Cookie 过期会提示重贴 |
| OpenCode Go | 5h/周/月窗口已用 % + 倒计时 | `zen/go/v1/usage`（Go key，`~/.local/share/opencode/auth.json` 的 `opencode-go` 条目） | 无绝对额度下发 |
| Codex（实验性） | 5h/周窗口已用 % + 重置倒计时；积分/重置券进 tooltip | ChatGPT 订阅 OAuth（见下方 Codex 小节） | 非官方接口，可能随时失效 |

## 移植到其他电脑

1. **只拷 `TokenWidget.exe` 一个文件**（目标机需 Windows 10/11 x64，免装 Python）。可选再拷 `local\config.json` 带走偏好；**不要拷 `bailian_cookie.dpapi`**——DPAPI 凭据与本机本用户绑定，异机必然解密失败（程序会安全降级为"需重新登录凭据"引导，不会崩）
2. 双击运行，首次启动自动在 exe 旁创建 `local\`；百炼行显示橙色"需重新登录凭据…"
3. 点该行胶囊 → 在**这台目标机的浏览器**登录 `bailian.console.aliyun.com` → F12 网络 → 任选一条发往 `bailian-cs` 的请求 → 复制完整 `Cookie` 粘贴保存（本机 DPAPI 重新加密）
4. 被 SmartScreen/杀软拦时：属性→解除锁定，或加白名单（未签名单文件打包的常见误报；本机 Defender 实测 0 检出）
5. 开机自启按需在设置页开启（写当前用户 HKCU，逐台各自设置）；多屏拖动位置自动记忆
6. 多台机器可同时跑同一账户（只读低频轮询互不冲突）；任一台上重新登录阿里云可能使旧 Cookie 失效，届时该机按提示重贴即可

## 开发与构建

- 技术栈：Python 3.12 + Tkinter，**运行时零第三方依赖**（stdlib only）
- 目录：`src/`（sources=采集适配层，ui/scheduler/settings_panel=浮窗，auth=DPAPI 凭据，autostart=注册表单值）· `scripts/probe_api.py`（M0 连通 probe）· `tests/`（渲染/设置/异常注入自测）· `build/`（spec/图标/一键打包，详见 `build\README.md`）
- 重建 exe：`pwsh -File build\build.ps1`（~20s）
- CLI 采集自测：`python cli.py`
- 计划与验收：`PLAN.md` · `docs\M5_acceptance_checklist.md`

## 合规与风险须知

- 百炼个人版无官方余量 API，本工具使用其控制台只读查询接口（与多个开源监控工具同路径），**上游改版可能失效**；查询频率 ≥60s，不做任何自动化推理调用
- 请勿将 `local\bailian_cookie.dpapi` 发给他人——它等价于你的控制台登录态

## 如何绑定 OpenCode Go（M6 起"占位"已转真实；M11a 起本页不再含 OpenAI）

- 右键浮窗 → 设置… → 勾选 OpenCode Go（未绑定时自动弹出绑定面板；旁注"未绑定 · 点击配置"也可随时打开）。
- OpenCode Go：登录过 opencode 的机器自动检测 `~\.local\share\opencode\auth.json` 的 `opencode-go` 条目（可关），或手动粘贴 Go key；**Zen key 不通用**（该端点必 403），自动检测绝不采用。
- key 一律 DPAPI 加密存 `local\<name>.dpapi`；保存后输入框立即清空不回显；保存即验证一次，失败按错误码提示（密钥无效/无 Go 订阅等）。
- ~~OpenAI Admin key 绑定~~：**M11a（2026-09-15 用户裁决）整行移除**，`src/sources/openai.py` 与其凭据、设置项已删除；线路规格留档 `docs\openai_go_wire_spec.md` 备查。

## 网络代理（M8，境外源在国内联网）

- OpenCode Go / Codex 在国内直连常被墙。设置页「网络代理」分组：勾选启用 → 填本地 HTTP 代理（典型 Clash/V2Ray 混合端口 `127.0.0.1:7890`，地址框与端口框分开填或合填 `host:port` 均可）→ 勾选作用范围（仅这两家，**百炼永不走代理**）。
- 仅支持 **HTTP/CONNECT 型代理**（`http://host:port`）；**不支持 socks**。代理 URL 可含 `http://user:pass@host:port` 认证段，但界面/日志/错误提示会脱敏为 `user:***@`。
- 「测试连通」按钮零凭据依赖：向探测端点发起，拿到任意 HTTP 状态码（含 401）即判「通道正常」，连接失败才报「通道未建立（检查代理地址/软件）」。
- 出口地区被上游封锁（Cloudflare 403 region）时会提示「切换海外节点」而非「密钥无效」（`REGION_BLOCKED` 已单独分类；「测试连通」同样橙字提示换节点）。
- 地址非法（无端口/socks/畸形）时按直连处理并给橙色提示；代理改动即存，下一轮采集（含设置面板内"测试/验证"）立即生效。

## Codex / ChatGPT Plan 窗口限额（M10，**实验性**）

- 第 4 家供应商「Codex（实验性）」：显示 ChatGPT 订阅的 Codex **5h / 周 窗口已用 % + 重置倒计时**（plan_type 做徽章；Pro 积分余额、窗口重置券计数进 tooltip）。
- ⚠️ 实验性声明：走 **非官方前端接口**（`chatgpt.com/backend-api/codex/usage`），ToS 灰区、仅只读低频（≥60s），**可能随时失效**；默认不启用，设置页手动勾选。
- token 自动读取（M10b，按序取第一个合格命中，仅 `auth_mode=chatgpt`）：① `local\auth.json`（frozen=exe 同级）→ ② 项目根 / exe 同级 `auth.json` → ③ `~\.codex\auth.json`（Codex CLI 登录产物）；面板显示"已自动检测：<来源路径>（尾 4 位）"。
- 异机/无 CLI 登录：设置页手动粘贴 access_token（DPAPI 加密存储）；token 任何时刻不回显、不进日志，与 OpenAI 平台 key 完全不互通。
- 请求需携带 `originator: codex_cli_rs` 等 CF 指纹头（已内置，见 `docs\codex_chatgpt_wire_spec.md`「CF 边缘指纹层」）。
- 国内需代理：在「网络代理 → 作用范围」勾选 Codex 项（同 Clash 混合端口即可）；401 提示「登录已过期」重贴 token，Cloudflare 拦截按网络档退避。
