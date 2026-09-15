# OpenAI / OpenCode Go 线路规格（M6 实现唯一事实来源）

> **（2026-09-15 用户裁决：OpenAI API 侧已从产品移除——`src/sources/openai.py`/绑定面板/
> `openai_*` 凭据与配置节均已删除；本文件留档备查，§1 OpenAI 部分不再维护，§2 Go 部分仍有效。）**

> 来源：CodexBar(openai.js/OpenCodeGoUsageFetcher.swift/docs)、openclaw extensions/openai/usage.ts、
> token-monitor opencode/goApi.js、dsh-opencode-go-usage（lib-2 逐字节提取，2026-09-11）。
> 标注：【源】=代码原文摘录；【未证实】=需自测。范围决策见文末 §3。

## 1. OpenAI Platform

### 1.1 主选：Organization Admin API
```
GET https://api.openai.com/v1/organization/costs
    ?start_time=<unix秒>&end_time=<unix秒>&bucket_width=1d&limit=<天数>&group_by=line_item
    [&project_ids=proj_…][&page=<cursor>]
GET https://api.openai.com/v1/organization/usage/completions   （同参数，group_by=model）
Headers: Authorization: Bearer <OPENAI_ADMIN_KEY>;  Accept: application/json
```
- 分页：响应 `{"object":"page","data":[…],"has_more":bool,"next_page":str}`；游标参数名 `page`；
  保护【源】：单请求 ≤31 天、≤100 页、next_page 重复即止。默认历史 30 天。
- 响应字段路径：
  - costs：`data[].results[].amount.value`（USD 数值）、`.amount.currency=="usd"`、`.line_item`（分组维度）
  - completions usage：`data[].results[].{input_tokens,input_cached_tokens,input_audio_tokens,output_tokens,output_audio_tokens,num_model_requests,model}`
- **已用 $ 聚合**【源 openai.js】：`cost = Σ_bucket Σ_results amount.value`（按 period 求和），渲染 "Spend"。
- tokens 口径（两家实现不一致，风险①）：采用 **tokens = input + input_audio + output + output_audio**，`input_cached` 单列不并入。
- 错误映射【源】：仅凭 HTTP **401/403** 判 "Admin API key required"，两家生产实现都不解析 body；
  本实现可另行解析标准信封 `{error:{message,type,code}}` 细化提示（信封格式【较可信】）。
- 新鲜度：bucket 按天，当天有对账差异（docs 原话）；轮询 ≥5min 为宜。
- 项目/service-account key 不能当 Admin key 用（docs 明示）。

### 1.2 兜底：legacy 余额（普通 sk- key，非官方）
```
GET https://api.openai.com/v1/dashboard/billing/credit_grants
Headers: Authorization: Bearer <普通 sk- key>
```
- 响应【源】：顶层 `total_granted / total_used / total_available`（USD），`grants.data[].expires_at`（unix 秒）。
- 派生【源】：`usedPercent = granted>0 ? used/granted : (available>0?0:100)`；`resetsAt = 最早未过期 grant.expires_at`。
- 判定：HTTP≠200 或 body 非 JSON 对象 → 直接视为不可用（不解析 HTML）。
- 仅在配置开关 `allow_balance_fallback=true` 且 org 路径失败时尝试。端点现状【未证实·随时可能失效】。
- `dashboard/billing/usage|subscription` 生产实现均未引用（只存活于中转网关生态）——**不实现**。

### 1.3 UI 最小信息集（对齐 CodexBar）
- 主行：`本月已用 $X`（org costs）；有 admin 失败但 fallback 成功时：`余额 $available（granted $total）+ 最近到期`。
- 可选：Requests、Tokens(in/out)、Cached（详情 tooltip 即可）。

## 2. OpenCode Go（仅实现线路 A·官方 usage API）

### 2.1 请求【源 OpenCodeGoUsageFetcher.swift fetchAPIUsage】
```
GET https://opencode.ai/zen/go/v1/usage
Headers: Authorization: Bearer <Go key>;  Accept: application/json;  User-Agent: <app名>
```

### 2.2 响应（API 变体字段名！三处实现一致）
```
usage.rolling.percent   : 0..100 直接百分数（不乘 100）
usage.rolling.status    : 字符串；"rate-limited" 视为 100%
usage.rolling.resetsAt  : ISO8601 带小数秒（也兼容 epoch 数字：>1e12 毫秒 / >1e9 秒）
usage.weekly.* / usage.monthly.* : 可选同构
（可选 renewAt 订阅续费时间）
```
- ⚠️ Web dashboard 变体是 `usagePercent`+`resetInSec`（整数秒）——**不同源不混用**；本实现按 API 变体读，遇 `usagePercent` 形态做兼容兜底（风险②）。
- ⚠️ rolling 窗口时长不在响应中，显示按服务端语义"~5h"文案（风险⑥）。
- 绝对 $/token 不下发（ZEN_LIMITS 服务端秘密）→ 行只显示 % + 倒计时。
- 校验：rolling 必须存在；weekly/monthly 缺省则不渲染该窗（与百炼 5h 策略同构）。
- 轮询：≥60s；限流常量为工程默认，非官方 SLA。

### 2.3 key 来源
- 手动粘贴（设置页）；或自动读 `%USERPROFILE%\.local\share\opencode\auth.json`
  顶层 `opencode-go` 条目 = `{type:"api", key:"…"}`（type≠api 丢弃）【源 token-monitor isGoApiCredential】。
- ⚠️ Zen key（`opencode` 条目）打此端点**必 403**——自动检测时绝不回退用 Zen key。

### 2.4 错误映射表【源两家合并】
| HTTP/条件 | 判定 | UI 语义 |
|---|---|---|
| 401 | key 无效 | 红/橙"密钥无效" |
| 403 + `body.error.type=="EntitlementError"` | 有效但无 Go 订阅 | `not_configured` 型提示"此 key 无 Go 订阅" |
| 403 其他 | 代理/WAF | "不可用" |
| 429 | 源限流 | 退避加大 |
| ≠200 | 读 body `message/error/detail` 或 HTML `<title>` 前 80 字符 | 通用错误 |
**必须解析 403 body 的 error.type**，不能只看 status。

## 3. M6 范围决策（orchestrator 定）
1. Go 只实现线路 A；**不做** cookie 线路 B/C（脆弱、无 key 级鉴权，绝对 $ 需求出现时再议）。
2. OpenAI 实现 1.1 + 开关式 1.2；预算设置页手填（`OpenAI 预算（$）`解除 disabled，作为 total 分母，used 取 costs 求和）。
3. 凭据一律 DPAPI 本机存储（扩展 `src/auth.py` 通用 save/load），设置页输入框保存后即刻清空不回显。
4. 新增 error_code 语义：`KEY_INVALID`、`NO_SUBSCRIPTION`、`RATE_LIMITED`、`NETWORK`、`PARSE_EMPTY`；UI 复用现有橙(需凭据)/灰(stale)分档。
5. 无真实 key 可实调 → 验收以 fixture 离线测试为准（含双字段变体、epoch/ISO 双形态、EntitlementError body）；真实密钥绑定后的首跑由用户触发，异常按 bailian 同款续期流处理。
