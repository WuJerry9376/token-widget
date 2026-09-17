# 桌面 Token 余量小部件 — 实施计划 v1.2（项目收官）

> 状态：**已交付**（2026-09-11 整理清理完毕）。M0~M5 全里程碑通过；遗留观察项见 §8 尾。
> 2026-09-10：v0.1 初稿 → v0.3 回填百炼（lib-1）→ v1.0 回填 OpenAI / OpenCode Go（lib-2）→ v1.1 用户确认全部决策点。2026-09-11：v1.2 收官。

## 0. 首期范围（据 §7 确认结果）

- **实际收录**：仅百炼个人版（当前唯一持有并绑定的账户）
- **接口占位、默认禁用**：OpenAI、OpenCode Go（用户暂无账户；source 适配器照写，UI 隐藏；日后迁移平台时在设置页填凭据即启用，问题届时调试）
- **M0 阻塞输入**：需用户从百炼控制台浏览器抓取一次 Cookie（步骤见 §5-M0）

## 1. 需求定义（已确认）

- ✔ **多供应商**：① 阿里云百炼 Token Plan 个人版（当前 opencode 绑定）② OpenAI Platform ③ OpenCode Go；架构预留任意供应商插件位
- ✔ **形态**：桌面浮窗（无边框、可拖拽），"总在最前"可选开关
- ✔ **交付**：免安装 exe；开机自启可选开关（默认关）
- ✔ **轮询**：默认 300s，可配 60s~60min；低余量自动提速至 60s；UI 显示"最后刷新时间"
- ✔ 提醒阈值（已确认）：剩余 <15% 黄、<5% 红（+可选系统通知）；外观默认便笺风，细节 M2 微调
- ✔ OpenAI / OpenCode Go：首期仅接口占位、默认禁用（暂无账户；日后迁移平台时在设置页填凭据启用，问题届时调试）

## 2. 数据来源（三家全部定稿）

| 供应商 | 路径 | 性质 | 能否拿到绝对余量 |
|---|---|---|---|
| 百炼个人版 | 控制台网关（Cookie） | ⚠️ 非官方 | ✅ Credits |
| OpenAI | Admin key→官方 costs/usage；普通 key→credit_grants 兜底 | ✅官方(需admin)/⚠️兜底 | 已用$✅ 余额$⚠️仅兜底 |
| OpenCode Go | 官方 usage 端点 | ✅ 官方 | ❌ 仅百分比+倒计时 |

（E1 凭据泄露面、E2 请求频率两项合规审查结果登记在 `docs\M5_acceptance_checklist.md` §F）

### 2.1 百炼个人版（定稿）

- **计量语义**：单位 **Credits**（按模型/思考/工具动态折算，部分夜间五折），**7 天滚动窗口**：Lite 2,500 / Standard 10,000 / Pro 40,000，到期重置不结转；用量包 20,000 Credits/个
- **5 小时窗口（决策已定）**：服务端疑似真实存在 lite=700/pro=12000 每 5h 暗限流，但接口 `per5Hour*` 字段时有时无、曾被临时下线 → **UI 默认不显示；source 若取到该字段则自动副显一行，取不到完全隐藏**
- **接口**（CodexBar/OmniRoute/token-monitor/oh-myusage 四家开源实测）：
  `POST https://bailian-cs.console.aliyun.com/data/api.json?product=sfm_bailian&action=BroadScopeAspnGateway&api=<api名>`
  - `zeldaHttp.apikeyMgr./tokenplan/personal/api/v2/usage` → `per1WeekPercentage/per1WeekResetTime`（`per5Hour*` 有时缺省）
  - `…/v2/quota-config` 档位总额；`…/v2/subscription` specCode/到期；`…/v2/addon/list` 用量包 total/remainingCredits
- **鉴权**：浏览器登录 Cookie（`login_aliyunid_ticket` 等）+ `x-xsrf-token`（`login_aliyunid_csrf`）+ `sec_token`（控制台 HTML `SEC_TOKEN` 或 `/tool/user/info.json`）；body 带 `cornerstoneParam`（productCode: p_efm），不硬编码 `switchAgent`
- **公式**：`剩余 ≈ (1 − per1WeekPercentage) × quota-config[specCode].weekly + Σ addon.remainingCredits`
- **实现**：移植 CodexBar `AlibabaTokenPlanUsageFetcher.swift` / OmniRoute `qwenTokenPlanQuotaFetcher.ts`（sec_token 缺失、`Workspace.NotAuthorised`、空响应重试、60s 缓存等坑已踩平）
- **已证实不可行**：推理响应头 ❌；`sk-sp` key 查额度 ❌；BssOpenApi 仅现金余额 ❌；个人版无官方 OpenAPI ❌（团队版才有 ModelStudio AK/SK 接口，升级后为长期稳定路径）

### 2.2 OpenAI（定稿 · 首期接口占位，默认禁用）

- **语义**：USD 计费，无"token 总额度"概念 → 显示「本月已用 $ + 可用余额 $（best-effort）+ credit 到期」
- **主选（官方）**：**Organization Admin API key** → `GET /v1/organization/costs`（按天 $）+ `/v1/organization/usage/completions`（token）
  - 坑：普通 `sk-` key、project/service-account key 一律 401/403；Admin key 不能做推理，须与普通 key 分开存储；cursor 分页（31d/页）
  - 新鲜度：按天 bucket，与 dashboard 对账有微小差异 → 5min+ 轮询足够
- **兜底（非官方）**：普通 key → `GET /v1/dashboard/billing/credit_grants` → `total_available`/`grants[].expires_at`（不在官方参考内，随时可能失效）
- **已弃**：`dashboard/billing/usage`+`/subscription` 在真实 api.openai.com 上不稳（现主要存活于 one-api/new-api 类中转网关），不作主选
- **限额**：官方无"账户余额上限"读取口 → 支持用户手填月度预算做分母

### 2.3 OpenCode Go（定稿 · 首期接口占位，默认禁用）

- **官方接口**：`GET https://opencode.ai/zen/go/v1/usage`，`Bearer <Go key>`
  - key 来源：`~/.local/share/opencode/auth.json` 的 **`opencode-go`** 条目（**Zen key 打此端点必 403**）；本机该文件现为空 `{}` → 需用户提供 Go key 或先经 opencode 登录写入
- **语义**：仅 **rolling(~5h)/weekly/monthly 三窗口的 percent + resetsAt**，服务端不下发绝对 $/token → 显示「窗口已用 % + 重置倒计时」
- **错误**：401 key 无效；403 `EntitlementError` = 无 Go 订阅；429 源限流
- 备选：dashboard cookie 走 `/_server subscription.get`（可带出 Zen 余额）；本地 SQLite 成本史（估算）
- **现成先例**：Win-CodexBar（CodexBar 的 Windows 版，支持 OpenAI/OpenCode Go/百炼等）→ 可作 provider 逻辑移植母体，见 §6-R7

## 3. 技术选型（已确认）

**Python 3.12 + Tkinter**，uv 管理，PyInstaller onefile 打包。
- 不选 PySide6（exe 60~120MB 偏重）/ Rainmeter（需宿主、鉴权麻烦）/ Electron（过重）
- UI 层抽象，未来可换 PySide6；网络层用 httpx

## 4. 架构设计

```
token-widget/
├── PLAN.md
├── src/
│   ├── main.py            # 入口：GUI + 轮询调度
│   ├── registry.py        # 供应商适配器注册表
│   ├── sources/
│   │   ├── base.py        # ProviderSource 抽象：fetch() -> Usage{mode,used,total,remaining,pct,resets_at,unit,note}
│   │   ├── bailian.py     # §2.1（Cookie 网关，7d 主显 + 5h 自动副显）
│   │   ├── openai.py      # §2.2（admin costs 主选 + credit_grants 兜底 + 手填预算）
│   │   └── opencode_go.py # §2.3（% 窗口三行）
│   ├── auth.py            # 凭据管理：百炼 Cookie/sec_token、各类 key 的存取（DPAPI）+ 过期检测与续期引导
│   ├── config.py          # 供应商启停 + 凭据引用 + 周期/阈值/置顶/自启
│   └── state.py           # 窗口位置、缓存、上次成功值
├── scripts/probe_api.py   # M0 逐家连通验证（打印原始响应）
└── dist/
```

- 单窗口多行；每家按 §2 语义渲染：百炼=Credits 进度条+重置倒计时（5h 仅在接口返回时自动副显）；OpenAI=$ 双值；Go=三窗口 %+倒计时（后两家默认禁用时不渲染该行）
- 凭据：key/Cookie 只存本机 DPAPI 加密文件或凭据管理器，不明文落盘；百炼 Cookie 首期"手动粘贴"录入，浏览器自动导入二期
- 接口失败 → 保留最后成功值灰显 + 指数退避（封顶 30min）；401/未授权 → 橙色"需刷新凭据"
- 无边框 + 拖拽 + 右键菜单（刷新/置顶/设置/退出）；自启写 `HKCU\...\Run`

## 5. 里程碑

- **M0 数据源验证（阻塞项；首期范围＝仅百炼实测）**
  - 前置用户输入（Cookie 抓取，一次性，约 2 分钟）：
    1. 浏览器登录打开 `https://bailian.console.aliyun.com`，进入 Token Plan「用量/我的订阅」页
    2. F12 → 网络(Network) → 刷新页面 → 找到发往 `bailian-cs.console.aliyun.com/data/api.json` 的请求
    3. 复制该请求 **Request Headers** 里完整的 `Cookie` 值和 `x-xsrf-token` 值，交给我（或粘贴到约定本地文件）
    4. `sec_token` 由 probe 脚本自动从 `/tool/user/info.json` 获取，失败时从页面 HTML 里 `SEC_TOKEN: "..."` 手工提取
  - probe 按 §2.1 实测 usage / quota-config / subscription / addon 四接口，打印原始 JSON；验收＝全部可解析且百分比×总额与页面显示一致
  - OpenAI / OpenCode Go：probe 代码与 source 骨架照写，但**不实调**（无凭据）；日后再启用并届时调试
- **M1 采集层 CLI**：registry + 三 source（含占位两家）+ 统一 Usage 模型
- **M2 最小浮窗**：多行渲染 + 拖拽 + 关闭
- **M3 完善**：设置页（启停/凭据/周期/阈值/置顶/预算手填）、状态记忆、凭据过期续期流、托盘（可选）
- **M4 打包**：PyInstaller onefile + 图标 + 自启开关实测
- **M5 验收**：24h 连续运行；断网/401/403/429/Cookie 过期/上游改版异常态；多显示器；重启验证自启

## 6. 风险与对策

1. **百炼=非官方契约**：改版即失效 → 可插拔 source + 移植成熟实现 + UI 异常提示 + 本地估算降级链
2. **百炼 Cookie 数天~数周过期**：过期检测 + 一键重贴流程必须进 M3，否则静默变砖
3. **凭据安全**：Cookie 含主账号登录态 → 仅本机加密存储，绝不外传；OpenAI admin key 单独存储、禁用推理
4. **条款合规**：仅低频只读查询（≥60s），README 明示；不对套餐 key 做自动化推理
5. **OpenAI 余额无官方口**：best-effort 标注；无 admin key 时仅剩 credit_grants（可能 404）→ 首期 OpenAI 行允许"部分指标缺失"渲染
6. **OpenCode Go / OpenAI 暂无账户**（已确认）：首期仅占位 source；日后启用时接口可能已变，届时重新调研调试
7. **重复造轮子提示**：Win-CodexBar 已覆盖同类功能（菜单栏形态、非浮窗）→ 本方案以"浮窗+便笺风+三家聚合"差异化；provider 逻辑优先从其 Swift/JS 实现移植以省时日
8. **exe 杀软误报**（PyInstaller 常见）→ 备选 venv+快捷方式；必要时签名（成本另议）

## 7. 决策记录（2026-09-10 用户确认，全部闭环）

- 多供应商 ✔ 浮窗+可选置顶 ✔ exe ✔ 自启可选 ✔ 默认 300s ✔
- **Q1** 接受百炼 Cookie+非官方控制台接口（唯一可行路）→ 采纳，含过期续期流
- **Q2** 无 OpenAI Admin key → OpenAI 仅留 source 接口占位、默认禁用；日后迁移平台时填凭据启用，问题届时调试
- **Q3** 无 OpenCode Go 订阅（本机 auth.json 为空 `{}` 已核实）→ 同样接口占位、默认禁用
- **Q4** 接受 Go 只显示百分比（无绝对额度）
- **Q5** 百炼 5h 暗限流：UI 默认不显示，接口若返回 `per5Hour*` 则自动副显
- **Q6** 阈值 <15% 黄 / <5% 红；外观默认便笺风，M2 微调

## 8. 进度

- [x] 确认绑定源与端点
- [x] 形态/交付/轮询用户确认（v0.2）
- [x] lib-1 百炼调研回填（v0.3）
- [x] lib-2 OpenAI+Go 调研回填（v1.0）
- [x] §7 全部决策用户确认 → v1.1 定稿
- [x] **M0 数据源验证：通过**（2026-09-10 实测）
  - [x] Cookie DPAPI 加密落盘 `local/bailian_cookie.dpapi`；`src/auth.py` 解密往返 OK
  - [x] 逐字节规格提取（lib-1 复用会话，CodexBar/token-monitor/OmniRoute 三实现交叉）→ 落盘 `docs/bailian_gateway_spec.md`
  - [x] probe 四接口全 200 且可解析：**subscription**=pro/VALID/余17天；**quota-config** pro weekly=40,000（5h=12,000）；**usage** 本周已用 60.0%、重置 09-11 02:45（`per5Hour*` 本次缺省→验证了"自动隐藏"策略正确）；**addon/list 国内站亦可用**：1×extrabundle 剩 1,509/20,000、09-29 到期
  - [x] sec_token 经 dashboard HTML 自动解析成功；剩余合计 ≈17,499 Credits
  - ⚠️ 微信推送遇 iLink context_token 过期：通知已入守护进程挂起队列（待用户下一条入站微信消息自动补发）
  - 备注：外部一致性（与控制台页面肉眼比对）由用户后续确认，不影响 M1 开工
- [x] **M1 采集层 CLI：完成**（fix-1，2026-09-10，真实调用验证通过）
  - 落地：`src/sources/{base,bailian_gateway,bailian,openai,opencode_go}.py` + `registry.py` + `config.py` + `cli.py`；stdlib-only
  - 实跑：bailian pro 剩余 17,077（周窗剩余+addon 1,509）、已用 61.1%、重置倒计时正确；占位源 not_configured 渲染正常；导入零告警
  - 显示语义定稿：合计分母含 addon 总额（60,000），addon 单列副显——如需"仅周窗口分母"改一行
  - 遗留转上层：stale 回填、退避、低余量提速 → M2 调度器
- [x] **M2 浮窗：完成并验收**（des-1，2026-09-10）
  - 独立验收：`tests/test_render.py` 14/14 通过；实跑 35s 拉真实数据正常；**sources/registry/config/auth/cli 时间戳证实零改动**
  - @observer 截图审查 8/10：便签质感/行结构/菜单状态全落地；6 项小缺陷（±1 数值自洽、更新时间重复、进度条空槽对比度、小字偏软、贴边裁切疑点）转入打磨
- [x] **M3 设置/续期流：完成并验收**（des-1 交付 + des-2 视觉必修关闭）
  - des-2 落实：蒙版残留 clip 修复（像素证据：蒙版外非背景像素 12→0）、"删除线"根因=9px 灰字连读（升 10.5px f_note 根治）、7 建议修全做、口径文案行；16+13 回归全绿
- [x] **M4 打包：完成**（fix-2 脚手架 + 收口重建）
  - `dist\TokenWidget.exe` 10.6MB onefile windowed；构建 7.5s；Defender 本机 0 检出
  - frozen `local/` 修复（orchestrator 实施于 config/state/auth 三头部）经 exe 部署实证：exe 同级 local 读写生效、cookie 解密成功（`bailian=OK` 非 NO_CREDENTIAL）
  - 部署形态定稿：**exe + 同级 local/ 文件夹**；凭据哈希全程未变（FBA4C5B5…52739）；dry-run 注册表零落盘；console 变体与 dist\local 副本已清理
- [x] **M5 验收：完成（2026-09-11 收官）**：清单 `docs\M5_acceptance_checklist.md` §F 全表登记
  - [x] **A 异常注入 + B 钳制：完成**（fix-3：`tests/test_anomaly.py` A1~A10+守护 13/13、`tests/test_geometry.py` B1/B3 9/9；零网络/零真实落盘/不扰 soak/cookie 哈希复核一致）
    - **验收发现 2 处 scheduler 真缺陷**：①退避公式 `min(poll, …)` 使退避永不超 poll ②`kick()` 无人消费 → "立即刷新"不即时
    - [x] **均已修复**（fix-4：退避 `poll≤d≤1800` 逐轮翻倍；kick `_wake.wait`+`_force` 位合并 ≤2s 生效；四套件 15/9/16/13 全绿）
  - [x] **M5 换装完成**（fix-2：修复版源码 → 新 `TokenWidget.exe` 10.6MB/7.3s；dist\local 三件部署、窗口落位实证 frozen 读同级 local；双哈希一致）
  - [x] **C1 长稳 soak 跑满 12h**：72 样本、0 异常行；子进程 WS 恒 8.5MB、句柄恒 98（无泄漏）；总 WS 96→106MB 缓漂（PyInstaller 主进程侧，可接受）；期间跨越 7 天窗口 02:45 重置点自动归零，重置语义活体自证。数据：`docs\screenshots\soak_sample.csv`
  - [x] **E1~E3**：凭据无泄露面（print 路径静态审查）；频率合规（≤4 请求/轮、双钳 ≥60s）；dist\local 为正式部署形态；哈希 FBA4…52739 全程未变
  - [x] **终检**：收官前四套件复跑 16/13/9/15 全绿；`local\` 仅存运行三件；开发残渣（截图/采样脚本/_pyi/__pycache__）已清

### 交付后待办（不阻塞，用户择机）
- D 自启+重启演练：用户已确认延后自行验证（勾选设置页"开机自启"→重启→看浮窗回归）
- B2 双屏实机项：副屏部署时顺手验证；若副屏缩放比与主屏不同致文字发糊 → 回来提 PMv2 适配（会话 des/fix 可复用）
- E4 VERSIONINFO 版本资源：下次重建顺带加入（唯一 diff）
- ~~日后启用 OpenAI/OpenCode Go~~ → **M6 已实装（2026-09-11，fix-5）**：auth 通用 secret（DPAPI）+ 两家真 fetcher（照 `docs\openai_go_wire_spec.md`）+ 设置页 ProviderKeyPanel 绑定流（保存即验证/即清空/不回显）；86 项检查全绿；真实 key 首跑待用户提供

### M8 网络代理（2026-09-14，**v1.2.0 已换装交付**）
- 需求：国内无法直连 OpenAI（本机 FlClash HTTP 代理 `127.0.0.1:7890` 已探实在监听）
- **M8 实现**（fix-5）：`src/netconfig.py`（normalize/脱敏/proxy_for/build_opener）+ `config.network`（enabled/url/targets）+ openai/opencode_go opener 注入 + 设置页「网络代理」分组；**百炼/调度/主窗零改动**；HTTP/CONNECT only（socks 文案注明不支持）；测试连通=任意 HTTP 响应即通道正常、零凭据依赖
- **视觉轮**（des-2 + obs-2 第 4 轮 8.5/10 无必修）：测试连通按钮两态（禁用融纸/常态 TRACK 底+描边）、代理组行距收 2px、全角括号回归锁（核实代码本已全角）；截图 `m8_settings(.png/_on.png)`
- **重建 v1.2.0**（fix-2）：10.7MB/18.2s、属性 1.2.0 复核、**cookie 守卫**三件 COPIED(new)、新实例常驻 (1800,310)、console 证据行 `bailian=LOGIN_EXPIRED | 下轮 600s`（橙态系 Cookie 服务端过期既有事实；600s=退避公式生效顺带实证）、注册表零变化、MpCmdRun 0 检出
- 基线：**8 套件 118 全绿**（16+13+9+15+11+22+14+18）；orchestrator 复验
- **待用户**：~~重贴百炼 Cookie~~ ✅ **2026-09-14 用户已在实际使用设备上完成续期，使用无异常；百炼模块经用户豁免：后续无改动则不再做回归验证**。本机 dev 副本 cookie 保持过期态属正常（DPAPI 绑机不可互拷，未来本机重建/冒烟见 LOGIN_EXPIRED 橙态**不是 bug，勿"修复"**）。剩：绑 OpenAI Admin key（勾代理 127.0.0.1:7890）/ Go key 首跑 / D 组重启演练
- 遗留小项：代理关闭时若欲"测直连"，`_sync_probe_btn` 单点放宽门槛（des-2 已注记）
- 需求：国内无法直连 OpenAI（用户本机 FlClash 类代理，典型 `127.0.0.1:7890`）
- 设计边界：代理**仅作用于 OpenAI / OpenCode Go**（`network.proxy_targets`），**百炼路径零改动**；HTTP/CONNECT 形态（Clash/V2Ray 混合端口通常同为 HTTP）；SOCKS 明确不支持并在文案注明
- 实现面：`config.network{proxy_enabled, proxy_url, proxy_targets}` + 新 `src/netconfig.py`（normalize/选型/脱敏）+ 两 source 传输层可选 opener 注入 + 设置页"网络代理"分组（启用/地址/端口/作用域/**测试连通**：拿到任意 HTTP 响应即通道正常，零凭据依赖）
- 安全：代理 URL 含认证段时错误消息/tooltip/日志一律脱敏（`://user:***@`）
- 验收基线：离线 fixture（不依赖真实代理软件）+ 既有 100 全绿；完成后 → 视觉抽查 → **v1.2.0 重建换装**（版本规则）→ 用户填 FlClash 端口实测
- **M6**（fix-5）：OpenAI/Go 真 fetcher（照 `docs\openai_go_wire_spec.md`）+ auth 通用 secret（DPAPI）+ 设置页 ProviderKeyPanel（保存即验证/即清空/不回显、三家复选框解禁、Go Zen-key 绝不自动采用）；3 处 wire-spec 偏差有记录理由
- **M7**（des-2 两轮）：加油包独立细条（floor 单一取数源三处对账、剩余占比向、无包零占位）+ 标题行手绘 ↻（=立即刷新同路径、悬停底色、60°步进旋转 30s 超时）；obs-2 审查 1 必修（1,509/1,508 分歧）+7 建议全关，含 Pro 徽章端点桩真根因（arc 端点帽→闭合折线描边）
- **M7b/M8 后续**（2026-09-14）：↻ 旋转反向（des-2，画布 -60° 步进=屏幕 CW，反向锁入 test_m7）；**REGION_BLOCKED 分类**（fix-5：Cloudflare 地理 403 不再误报 KEY_INVALID，独立分类+「切换海外节点」文案+同链路 grants 自动跳过+测试连通三态化，基线 118→122）；**M9 贴边吸附**（des-3：释放即吸工作区边 ≤SNAP_PX28、3帧90ms ease-out、终值即落 state、多屏 EnumDisplayMonitors 择面积屏、悬空软着陆；REGION 进橙档配「立即重试」；130/130）
- **OpenAI key 实测定论**（2026-09-14，用户切海外节点后）：所给 `sk-admin-*` 为**有效 Organization Admin key**（org/costs 200 page 信封；/v1/models 403 缺 api.model.read scope=Admin 型反证）；30 天消费 $0.00，CLI 端到端 GREEN。usd 零消费+无预算时"—"显示微调进行中（des-4）
- **E4 兑现**（fix-2）：VERSIONINFO 中文产品名、README 版本规则（每里程碑次版本+1）；Defender 定点扫描 0 检出
- 基线演进：**100 → 118 → 122 → 130 → 131**；orchestrator 各轮独立复验；注册表零落盘、cookie 哈希全程未变
- **v1.3.0 已换装**（fix-2，2026-09-14）：收编 ↻ 反向 + REGION_BLOCKED 分类橙档 + M9 贴边吸附 + usd"余额未知"显示（$0.00+指引句）；门禁 131/131 后构建 10.7MB/16.6s、属性 1.3.0、dist\local 四件（含 openai_admin_key）哈希一致、直启不吸实证、注册表零变化、Defender 0 检出；本机常驻版现含 OpenAI 行（$0.00 已用态）
- **构建守卫待改进**（低优先，下轮重建顺手）：build.ps1 清 dist 先于复制，"copy-when-newer"无法保全仅 dist 侧更新的凭据（如用户在生产机续期后回拷场景）→ 清理前把 dist\local 暂存回项目侧
- **v1.4.0 已换装**（fix-2，2026-09-14）：收编 **M10 Codex provider**（第 4 家「Codex（ChatGPT Plan 窗口限额）」，实验性、默认不启用；按 `docs\codex_chatgpt_wire_spec.md`——chatgpt.com/backend-api/codex/usage + ChatGPT OAuth token（~/.codex/auth.json 自动检测或粘贴），窗口按 limit_window_seconds 匹配 5h/周，错误四分类，面板第 4 框+绑定流复用 403 分类体系）；门禁 **148/148**（10 套件）；构建 10.7MB/9.8s、属性 1.4.0、dist\local 四件守卫 COPIED、registry 四源冒烟、默认渲染不含 codex 行实证（零调用）、注册表 IDENTICAL、Defender 0 检出；本机常驻落位 (2004,24)=state 现值
- **下一步（用户侧）**：生产机部署 v1.4.0（dist 全套拷走或只拷 exe 重走绑定流）；**Codex provider 首跑**=生产机需有 Codex CLI 登录（~/.codex/auth.json）或手动粘贴 access_token，设置页勾「Codex（实验性）」启用；Go key 首跑（如仍要）；D 组重启演练
- **调试期临时事项**（M10b 关联）：用户已将 ChatGPT OAuth `auth.json`（access_token exp 09-17，含 refresh_token）放入项目根目录用于联调——**明文 OAuth 凭据**，交付版应以 DPAPI secret 存储（沿用 codex_access_token 体系）；调试完成后与用户确认该文件删除或转存方案
- **v1.5.0 已换装**（fix-2+fix-5/6，2026-09-15）：M10 真实联调定案——403 根因=CF 边缘指纹缺 `originator: codex_cli_rs`（矩阵 J1/J2 实证，非 IP/token 问题）；修复+**M10b 自动读取**（`find_codex_auth` 三候选：local\auth.json→exe同级→~/.codex，手动粘贴入口保留=异机部署用，检测行三态显示来源/尾4位）+ Usage.note 重置券 + 禁发 Accept-Encoding 注记；真实链路 `codex=OK(plus·周窗3%·5h 0%·券1)`；门禁 **151/151**；dist\local 五件（**含用户 auth.json 副本，属敏感凭据，dist 分发/清理按凭据对待**）；README v1.5.0 行
- **调试脚本归档**：`scripts/dbg_archive/`（矩阵/探针/脱敏结果，9 件保留可复现）
- **v1.6.0 已换装**（fix-2，2026-09-15）：M11a 移除验证（注册表三源、admin key 两处清零、dist 无 openai 痕迹）+ M11b 新行高实证（330×248、codex=OK 已用 19.0%、直启不吸、注册表 IDENTICAL、Defender 0 检出）；obs-2 第 5 轮 8/8.5 无必修
- **v1.6.1 已换装（M11 里程碑闭环，2026-09-15）**：M11c 收编（副条字档/短名/券字重/细条方向锚字「剩」）；门禁 136；冒烟 `codex=OK(已用 22.0%)` 真实链路、无 openai 字段、注册表 IDENTICAL、Defender 0 检出；修订号规则首用。**产品定态：三源=百炼+OpenCode Go(占位)+Codex；Codex 行=双窗条+券角标**
- **v1.6.2 已换装**（M11d：des-3 固定槽 + fix-2，2026-09-15）：Codex **5h 恒主条/周恒副条**（与源层"最紧者"排序解耦，缺窗单边递补）、5h 标题去「窗」、大数字随主条=5h 剩余%（代价如实：5h 空闲显 100%，周紧迫由副条红档承载；可一行回退 min 口径）；136/136、冒烟 codex=OK 44.0%（5h 真实用量语义自洽）、高 248px、注册表 IDENTICAL、Defender 0 检出
- **M12 四项 UI 上线**（des-3 + fix-2 v1.6.3，2026-09-15）：设置页代理组未启用整组禁用联动；Codex 标签去「（实验性）」（面板内实验性提示保留）；阈值三色 #3BC371/#FEC211/#EF0000（一处常量集中改）；↻ 图标 4× 超采样 PhotoImage 预旋转 6 帧（Tk 无 per-pixel alpha→under-texture 方案，27-89ms 一次生成，M3c 纯净判据不触）；obs 级像素存证 m12_* 四图
- **M12h 热修**（orchestrator 实施，fix-2 v1.6.3 冒烟定档→已修）：console 变体 `--verbose` 下 `↻` 日志行 GBK 码页必崩（windowed 交付形态不受影响）；ui.py:605 改「刷新图标」文案，gbk 环境实测 exit=0 + 136 全绿；**v1.6.4 已重建收编**（console 变体 GBK 冒烟列为该轮必做判据，二进制实证销案；顺带注记 build.ps1 清 dist 先于布置致首跑 NO_CREDENTIAL 属部署顺序瞬时态，README 已注）
- **M13 已交付（v1.6.5，2026-09-15）**：设置面板 foot 行右端 `v{APP_VERSION} · by Jerry Wu`（FAINT 档、零增高、动态取自新建 `src/version.py`=版本单一事实源；与 build/version_info.txt 双源同步由 test_settings 看门断言防漂移；期间定档 test:168 静态 pin 与升版矛盾→改格式校验）；136/136、GBK 回归绿、capture_m13 PASS，桌面常驻=**v1.6.5**
- **git 版本管理启用**：仓库 init 完成（`f1f61c7` 基线导入 → `34bcfcb` v1.6.5，annotated tag `v1.6.5`）；`.gitignore` 硬排除 `local/`、`dist/`、根 `auth.json`、`*.dpapi`、`scripts/dbg_archive/`；`git ls-files` 凭据/产物扫描=空；**约定：此后每换装版本一 commit + 一 tag，随 rebuild 收口执行、orchestrator 复核**
- **M14 已交付（v1.6.6，2026-09-15）**：Codex 5h/周升级为**双等尺寸主条对称信息块**（各配文字行+9px 主条、组间距 12 逻辑px/条-条 19px、行高 114→100 反降；固定槽/递补/独立阈值色/M11d 大数字口径不变）；capture_m11 真实链路因 dev 机凭据过期（Codex OAuth 401 + bailian Cookie 过期）未出图，判据就绪待凭据续期后一键补——**生产机凭据为新的不受影响**。fix-2 重建 v1.6.6（136 门禁、GBK 冒烟 exit=0 双橙态如实渲染、192px 橙态高度双因注记、注册表 IDENTICAL、Defender 0 检出）；git `2f9830b` + tag `v1.6.6`，禁提交物扫描 CLEAN
- **M15 更新机制（客户端侧完成，2026-09-15，fix-6）**：`src/updater.py`（GitHub Releases API：`parse_release/is_newer` 三段数字比较/`check` 6h 频控+失败代理回落/`download_and_stage` .part+Content-Length 校验/`render_restart_cmd` 纯函数+退出后替换重启、`local\` 零触碰）+ 设置页「更新」分组（**自动更新默认勾选**、当前版本、检查更新后台线程、发现新版→手动「立即下载并更新」+内联二次确认——**定时路径只读发现绝不无感替换**）；config 加 `update{enabled,repo,last_check}`；新测试 20 项，**全量基线 156/156**；repo slug 走配置零写死
- **GitHub 发布（已完成，2026-09-15）**：public 仓库 `WuJerry9376/token-widget`（main + tags 全推送，内容级密钥扫描 CLEAN 仅测试桩）；**v1.7.0 Release 首发**挂 TokenWidget.exe（11.2MB），更新链闭环双测过：`releases/latest→v1.7.0`、真 config `updater.check→已是最新 v1.7.0`；此后每版本：升版→build→commit+tag→push→`gh release create v<ver> dist\TokenWidget.exe`（build/README 已实化模板）。**注意**：dev 机 dist config.json 磁盘上无 update 节属正常——load_config 合并 DEFAULTS 必有（enabled 默认开 + slug 定仓）；gh 依赖已装（Program Files\GitHub CLI）
- **M16 触发点与 UAC 加固（v1.7.1，2026-09-17，fix-6）**：自动检查三触发点=**启动~5s / 打开设置页 / 每日 5 点后首帧**（6h 频控+`last_auto_date` 日期戳合并防重，复用既有 tick 无新轮询）；设置页勾选文案净化为「自动更新」（频率括注按用户令删除+防回流断言）；发现新版出口=主窗 foot 版本签名旁 **3px 橙点**（点击直达设置页并 force 刷新，等版自动熄灭）；替换前目录权限预检→不可写时「提权更新」一次性 UAC（不静默退出）；cmd 替换失败落 `local\update\FAILED.txt` 下次开页消费提醒。基线 **162/162**；真实链路：启动触发生产实证（config 落 last_check+日戳）；GitHub releases/latest=v1.7.1、asset 就位；git `d26a3b5`+tag 已推送。6 条偏差合理（无常驻新轮询/无 update 节整体静默守卫/改名序维持等）
- **M17（v1.7.2，2026-09-17，fix-6）**：skipped 状态行精简为「上次检查：HH:MM/跨日/--」（频控逻辑不动+禁词防回流）；「☆ 加星」按钮一键开仓页（webbrowser，零凭据）→ 被 M18 改向为 foot 图标。基线 165；Release v1.7.2 上架。**发版 git 流程定样：每功能轮收口=commit+annotated tag+push+gh release create 一条龙，由 orchestrator 派打包线执行、门禁通过为硬前置；程序本体永不碰 git/push**。镜像源裁决：加为**下载备用链**（直连→代理→镜像），信任锚=GitHub API 的 asset.digest SHA256 强校验（镜像缺 digest 拒收），元数据永不走镜像——M18 实施
- **M18 镜像源+foot 图标（v1.8.0，2026-09-18，fixer）**：①星形按钮改向落地——更新分组「支持」行删除（面板断言含不回流守卫），设置页 foot 行版本签名左侧 **GitHub 剪影图标**（settings_panel 自持 `gen_gh_mark`：4×4 子点解析覆盖超采样 PhotoImage、premultiply 纸底 put，同 ui._gen_rot_icons 技术栈、零改 ui.py；高=f_note 行高 DPI 自适应，FAINT 墨/hover 转 SOFT；点击 webbrowser 开仓页失败橙字兜底；slug 空隐藏零占位；tooltip「打开 GitHub 仓库页」；10× 取证 `local\m18_ghicon.png` 双态合成 PASS）；②镜像备用源——config update 节补 `mirror:""`（DEFAULTS 合并向后兼容）、设置页「镜像源（可选）」粘贴即存 normalize（纯前缀/占位式两形态统一 "scheme://host/" 拼接式、socks/userinfo/畸形拒绝、空=不使用）、旁注信任链声明；`download_and_stage` 回退链 **直连→代理(build_opener)→镜像拼URL**、返回 DownloadResult 记 used_channel+note、三链全败聚合脱敏报错；**digest 信任锚**：parse_release 读 asset.digest（归一 "sha256:<hex64>"、跟选中 asset 腿）、流式 hashlib 必校验（不符删件报错换腿；镜像腿缺 digest 拒收；直连/代理缺 digest 放行+note 如实说明）；check 恒官方 API 零镜像（测试钉 URL 断言）。M15 套 29→**31**（u26 改造 foot 图标、u28 mirror normalize+链序、u29 digest 四态），门禁 **167/167**；build 10.8MB/8.3s 属性 1.8.0、GBK 冒烟 exit=0 stderr 0B 无 openai、守卫四件哈希一致+openai 复净；README 更新节补镜像用法与"镜像第三方可读下载字节、官方哈希把关"提示
- **M19 更新确认弹窗化（v1.8.1，2026-09-19，fixer/M18 作者）**：用户反馈 v1.7.1「发现新版后没有可确认更新的按钮」（内联可发现性差）→ 手动「检查更新」/橙点 force 发现新版即弹 **UpdateDialog**（_Card 纸面语言：缝线标题条「发现新版本 vY」+ ✕；信息区=vX→vY、published_at→UTC 时刻、asset.size→MB 一位小数、notes textwrap≤6 行尾…；底部「立即更新」保存实底档+「取消」浅描边档）。触发纪律：a 手动弹/b 橙点 force 弹/c 状态行留「发现新版」+「查看」重开（单例、关面板级联散）/d 定时发现**绝不弹**只亮橙点（防打扰）。「立即更新」=直接进下载（原内联"立即下载并更新→确认更新→取消"三步退役、禁词回流守卫），弹窗内状态区 hist 留痕：≥512KB 节流刷 %→「校验通过·接管替换」通道审计→NEED_ELEVATION 提权档/失败橙字+重试/关闭；staged 免重下、worker 残余事件关窗安全（poll alive 守卫）。updater 元数据扩：parse_release 六元组(+size+published_at，跟选中 asset 腿/顶层容错)、download_and_stage 补 progress_cb(展示层故障不断流)。M15 套 31→**33**（u21 改造弹窗自动弹+渲染+查看+禁词、u22 加不弹断言、u30 执行链、u31 纯函数），门禁 **169/169**；实拍 `local\m19_dialog.png` 三态合成（待命/hover/进度）PASS；不做强制 grab（简单权衡，弹窗置顶+✕ 即散）
- 遗留小项：加油包"到期日"数据源未透出（sources 无字段）；console 变体不挂版本资源（调试专用，无碍）；auth.json 明文 OAuth 若用户日后要求，可加"首读后转 DPAPI secret 并删文件"一键（refresh 自动续期二期）；dev 机两凭据待续（Codex CLI 重登/重贴 token；百炼 Cookie 重贴），续后跑 `python tests\capture_m11.py` 补 M14 实拍
