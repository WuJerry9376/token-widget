# ChatGPT Plan（Codex 窗口限额）线路规格 —— 实验性 provider 备用

> 来源：lib-2 调研（2026-09-14），多实现交叉（codex-proxy codex-types.ts / aimux limits.ts / Codex CLI）。
> 定性：**非官方前端接口**，ToS 灰区，仅只读低频（≥60s）；UI 需标"实验性"。与 API 平台（openai provider）完全独立，不共用凭据。

## 端点与认证
```
GET https://chatgpt.com/backend-api/codex/usage
Authorization: Bearer <ChatGPT OAuth access_token>
User-Agent: codex_cli_rs/<ver>（社区实现常用固定值）
```
- token 来源：`~/.codex/auth.json` → `tokens.access_token`（Codex CLI 登录产物；`auth_mode=chatgpt`）；access 过期但有 refresh 时可刷（实现首期不做刷新，过期→橙态续期流，语义同百炼 Cookie）
- ⚠️ 与 API key/admin key 完全不互通；备用端点 `/backend-api/wham/usage`

## 响应字段（CodexUsageResponse 逐字摘自生产类型）
```
plan_type : "plus"|"pro"|"team"|"pay_as_you_go"|...
rate_limit : {
  allowed : bool, limit_reached : bool,
  primary_window   : { used_percent, limit_window_seconds, reset_after_seconds, reset_at } | null,
  secondary_window : { 同上 } | null
}
code_review_rate_limit : {…同构} | null
additional_rate_limits : [ { limit_name, metered_feature, rate_limit:{…}|null } ]
credits : { has_credits, unlimited, overage_limit_reached, balance:"12.345"(十进制串) }
spend_control : { reached, individual_limit }
rate_limit_reached_type : { type, details } | null
```

## 关键判读规则
1. **窗口按 `limit_window_seconds` 识别**：18000=5h、604800=周；**禁止**按 primary/secondary 位置写死（无 5h 窗的套餐，周窗会出现在 primary）
2. `reset_at`=epoch 秒、`reset_after_seconds`=倒计时，二者取先有者
3. `used_percent` 0..100 → 契约 0..1（>1 才 /100，同 Go 防御）
4. credits：Plus `has_credits=false`；Pro/PAYG 有 `balance`（$ 字符串）→ 可作 usd 副显
5. `allowed=false / limit_reached=true` → 行状态橙色"窗口已耗尽"
6. 错误：401（token 过期/无效→续期流，语义=百炼 LOGIN_EXPIRED 档）；403/HTML（Cloudflare 拦截，按网络档退避加大；per-IP 并发 ≤5）；`detail`/`error.message` 为错误文案源

## Usage 契约映射（provider 名建议 `codex`，enabled 列表第 4 家）
- unit=percent（同 Go 多窗渲染）：windows=[Window("5h"),Window("周")]（缺则不出）；pct_used 取最紧窗
- 有 balance 时 tooltip/副行加"积分余额 $x.xx"；plan_type 进 spec 徽章位
- M11c 细条方向定案：主条一律**已用向**；细条一律**右文案=方向锚字、图文同向**——codex 副细条
  「已用 x% · 倒计时」（已用向），百炼加油包细条「剩 X / 总Y」（剩余向）；codex 行窗短名「5h / 周窗」
- M11d 槽位与口径定案：5h 恒主条、周恒副细条（与松紧解耦，缺位递补：无 5h 周升主条、无周仅主条）；
  大数字=主条窗剩余占比（所见即所得；此行为 UI 侧覆写，不改本表 pct_used=最紧窗的源层口径）；
  黄/红阈值仍各窗独立判（副条自着色承载另一窗的紧迫度）
- 无 token → not_configured（零网络）；绑定流=ProviderKeyPanel 变体：自动检测 `~/.codex/auth.json` + 手动粘贴 access_token

## 实现备忘
- 主机 chatgpt.com 亦需海外出口 → 复用 network.proxy_targets 机制（targets 加 "codex"）
- token 属会话级凭据：DPAPI 存储、UI 永不回显（同 admin key 纪律）
- 失效预期：路径/字段漂移风险高，provider 骨架保持独立文件便于一刀切换

## CF 边缘指纹层（M10a 403 矩阵定案，2026-09-14 实机验证）
> 结论：**403 ≠ 401**。缺正确指纹头时 Cloudflare 边缘直接 challenge（`cf-mitigated: challenge`
> + HTML "Just a moment"），与 token 有效性无关——token 层根本没被评估。旧分类把 403/HTML
> 归"网络档退避"仍成立（分层与实测一致），但补头后此档应极少触发。

- **`originator: codex_cli_rs` 是放行开关**：产品 UA（保留 token-widget 身份不伪装）+ originator
  即 200（J1 实证）；只换/不换 UA、加 account/browser 全套头但缺 originator 均 403（A/B/C 组）。
- 加固对（J2 实证同样通）：`Sec-Fetch-Mode: cors` + `Sec-Fetch-Dest: empty`。产品采 J1+J2 合集。
- **禁发 `Accept-Encoding`**（H1 教训）：显式声明 → 响应体 gzip 而 urllib 不解码 → JSON 解析必炸；
  不声明则服务端给 identity，urllib 默认行为即正确。
- `/backend-api/wham/usage` 备用端点对指纹**不敏感**（A_wham 最小头也 200），可作漂移备胎。
- 直连（无代理）同指纹组合亦 200（D_direct）——代理非放行条件。

## 实测新字段（M10b 采集清单）
```
user_id / account_id / email        : ⚠️ PII —— 零入库零外显，解析层不读取
model_usage.<model>                 : { available, available_at, credits_would_enable }（暂不采）
promo                               : 实测 null（暂不采）
rate_limit_reset_credits : { available_count:int, applicable_available_count:int }
    → 已采：available_count>0 时 Usage.note「窗口重置券：可用 x」（tooltip 有则显、无则不显）
```

## refresh 通道二期结论（M10a 评估，暂不实现）
- ChatGPT OAuth refresh_token 的 `auth.apple.net/oauth/token` grant 为公开固定参数，技术上
  可自刷（access 过期 exp≈30 天可自动续）；**但**刷新伴随 refresh_token 轮换落盘（滑动会话），
  涉写用户 `auth.json`/DPAPI 管理 rt，凭据面扩大、失败态复杂——收益（少一次手动重登）不抵风险。
- 一期策略维持：access 过期 → 401 → KEY_INVALID 橙态「登录已过期」续期流（重登 Codex CLI 或重贴）。
