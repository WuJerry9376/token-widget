# 百炼控制台网关调用规格（国内站个人版）— 供 probe/M1 实现

> 来源：CodexBar(AlibabaTokenPlanUsageFetcher/Parser/APIRegion.swift) + token-monitor(cn-personal limits.js) + OmniRoute(qwenTokenPlanQuotaFetcher.ts) 三实现交叉验证，逐字节提取于 2026-09-10（lib-1）。分歧处取"并集最保守形态"。

## 0. 固定常量（三实现一致）

| 项 | 值 |
|---|---|
| quotaOrigin（POST 目标） | `https://bailian-cs.console.aliyun.com` |
| gateway/dashboardOrigin | `https://bailian.console.aliyun.com` |
| region | `cn-beijing` |
| product | `sfm_bailian` |
| action | `BroadScopeAspnGateway` |
| commodityCode | `sfm_tokenplansolo_public_cn`（addon 用 `sfm_tokenplansoloaddon_public_cn`） |
| consoleSite | `BAILIAN_ALIYUN` |
| dashboardURL | `https://bailian.console.aliyun.com/cn-beijing?tab=plan#/efm/subscription/token-plan/personal` |

⚠️ 关键结构：POST 打到 **bailian-cs**，但 `Origin`/`Referer` 填 **bailian**（dashboard 域）；Cookie 必须是从 quota 请求（bailian-cs 能收到的那份）复制的。

## 1. URL

`POST https://bailian-cs.console.aliyun.com/data/api.json?action=BroadScopeAspnGateway&product=sfm_bailian&api=<encodeURIComponent(api)>&_v=undefined`
- `api=` 值做 `%2F` 编码（与抓包一致；CodexBar 原样 `/` 亦可用）

## 2. 请求头（全 POST；均浏览器表单请求形态）

```
Content-Type: application/x-www-form-urlencoded
Accept: application/json, text/plain, */*
Cookie: <整串>
X-Requested-With: XMLHttpRequest
User-Agent: <Chrome UA>
Origin: https://bailian.console.aliyun.com
Referer: https://bailian.console.aliyun.com/
x-xsrf-token: <login_aliyunid_csrf 原值>
x-csrf-token: <同值>
```
必需 Cookie 字段：`login_aliyunid_ticket`、`login_aliyunid_csrf`、`login_current_pk`、`cna`（→cornerstoneParam.X-Anonymous-Id）。

## 3. POST body（form-urlencoded）

```
product=sfm_bailian
action=BroadScopeAspnGateway
region=cn-beijing
language=zh-CN
params=<一层嵌套 JSON 字符串，见下>
sec_token=<可选，解析到时才加>
```

`params` JSON：
```json
{"Api":"<完整api串>","V":"1.0","Data":{
  "commodityCode":"sfm_tokenplansolo_public_cn",   // usage/quota-config 也带（OmniRoute 行为，多传无害）
  "cornerstoneParam":{
    "feTraceId":"<uuid4 小写>","feURL":"<dashboardURL>","protocol":"V2",
    "console":"ONE_CONSOLE","productCode":"p_efm","switchUserType":3,
    "domain":"bailian.console.aliyun.com","consoleSite":"BAILIAN_ALIYUN",
    "userNickName":"","userPrincipalName":"","xsp_lang":"zh-CN",
    "X-Anonymous-Id":"<cna 值>"
}}}
```
🚫 两条硬禁令：cornerstoneParam **不得带硬编码 `switchAgent`**（→Workspace.NotAuthorised）；不得把国内 Cookie 配国际身份（→Login.NotLogined）。

## 4. 四接口差异（`.../v2/` 前缀 `zeldaHttp.apikeyMgr./tokenplan/personal/api/v2`）

| api | Data 额外字段 |
|---|---|
| `usage` | 仅 commodityCode+cornerstoneParam |
| `quota-config` | 同上 |
| `subscription` | commodityCode 必须 |
| `addon/list` | `{"commodityCode":"sfm_tokenplansoloaddon_public_cn","status":["ACTIVE"],"pageNum":1,"pageSize":10}`；⚠️ 百炼国内站该路径**未证实**，失败须容错 |

## 5. sec_token 获取（三级，全失败则裸发）

1. **dashboard HTML**：`GET <dashboardURL>`，必须带导航头（`Accept: text/html...`、`Sec-Fetch-Site: same-origin`、`Sec-Fetch-Mode: navigate`、`Sec-Fetch-Dest: document`、Referer=裸源）；按序正则：`"secToken":"..."`、`"sec_token":"..."`、`secToken[:=]'...'`、`sec_token[:=]'...'`、`SEC_TOKEN[:=]'...'`（window.ALIYUN_CONSOLE_CONFIG）
2. `GET https://bailian.console.aliyun.com/tool/user/info.json`（Cookie+Referer 裸源+Accept json）→ 递归（含展开内嵌 JSON 字符串）找 `secToken`/`sec_token`；顺带取 nickName 等账户标签
3. Cookie 里现成 `sec_token=` 值
- 未登录判定：info.json `successResponse=false`

## 6. 响应信封与错误分类

真实结果在 body，网关对一切错误都回 HTTP 200：
```
{code:"200", data:{DataV2:{data:{success:true, code:"SUCCESS", data:<payload>}}}}
```
1. **先递归展开内嵌 JSON 字符串**（网关常双重 stringify，漏了会把好响应当空的）
2. 外层 `successResponse===false`，或**递归任一 frame `success|Success===false`** → 失败
3. 错误分类（对 code+message 小写启发）：
   - `needlogin|login|postonlyortokenerror|tokenerror|request has expired|refresh page|请求已经过期` → **Cookie 过期**（数天~数周一次重贴）
   - `notauthoris?zed|unauthorized|access denied|forbidden` → 鉴权失败；**但 `workspace.notauthoris?zed` 除外**——那是缺 sec_token 的信号，补 token 重试，**绝不能提示用户重贴 Cookie**
   - 响应非 JSON（HTML）→ 视为登出
4. usage 返回 success 但 payload 无 `per*Percentage` → 空窗口，**最多 3 次 × 400ms** 重试
5. 每窗口字段皆可选（5h 曾被临时下线）
6. 缓存节奏：usage 60s；subscription/quota-config 1h

## 7. 字段路径与单位（**百分比是 0..1 小数，不是百分数**）

- usage payload：`per1WeekPercentage`/`per1WeekResetTime`、`per5HourPercentage`/`per5HourResetTime`（毫秒 epoch；<1e12 则 ×1000）；读取端防御：`v>1 → v/100`
- subscription payload：`specCode`（lite/standard/pro/max；键兼容 spec_code/planName）、`status`、`remainingDays`、`startTime/endTime`(ms)
- quota-config payload：`{<spec>: {"five_hour|fiveHour": <Credits>, "weekly": <Credits>}}`；实测 lite 700/2500、pro 12000/40000（weekly 与官方文档吻合）
- addon payload：items 在 `items|list|records|data` 任一键；字段 `totalCredits/remainingCredits/endTime`
- **剩余公式**：`剩余 = (1 − per1WeekPercentage) × quota-config[specCode].weekly + Σ addon.remainingCredits`
