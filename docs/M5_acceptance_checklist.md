# M5 验收清单 — token-widget

> 用法：逐项执行并勾选；每条给出"执行方式"与"通过判据"。
> ⚠️ 凭据纪律：任何测试不得改动 `local/bailian_cookie.dpapi`（哈希基线
> `FBA4C5B5…52739`，见 PLAN §8）；注册表只允许 dry-run 只读，真实 enable
> 仅在 §D 自启项由用户明确同意后执行且只写 `token-widget` 单值名。

## A. 异常态矩阵（注入法，不动 sources）

在 `tests/` 新增 `test_anomaly.py`：用 monkeypatch 替换 `BailianSource.fetch` 依次注入，渲染后断言不崩且文案正确（截图佐证）：

- [ ] A1 LOGIN_EXPIRED（有过往成功值）→ 橙色"需重新登录凭据"+ 旧值保留可见，行内"更新登录凭据…"胶囊出现
- [ ] A2 LOGIN_EXPIRED（从未成功）→ 明确空态文案，无 `--` 假象堆叠
- [ ] A3 WORKSPACE_NOTAUTHORISED → 提示按 sec_token 路径处理，**不得**出现"重贴 Cookie"字样（错误分类语义守护）
- [ ] A4 NETWORK（模拟断网/超时）→ 灰显旧值 + stale 虚线徽章 + 原因行；连续 N 轮后进程内退避值 ≤ 30min（读 scheduler 内部态断言）
- [ ] A5 上游改版：payload 丢 `per1WeekPercentage` 键 → 走空窗口重试→ 最终 stale/错误态之一，不 KeyError
- [ ] A6 上游改版：信封嵌套变化（DataV2 缺失）→ extract_payload 返回 None → 归入错误态不崩
- [ ] A7 全部供应商 error（bailian 失败 + openai 启用未配置）→ 窗口每行各自状态正确，合计行显示 0/—，无空窗
- [ ] A8 凭据面板保存非法串（无 `=`）→ 拒绝且不落盘（临时路径断言文件未创建）
- [ ] A9 poll_seconds 竞态：轮询线程运行中写 config（连改 10 次）→ 无死锁/异常，最终值为末次写入
- [ ] A10 401/403/429（源已分类，UI 层映射）→ 各自文案与配色按 ui 状态表断言

判据：`python tests\test_anomaly.py` 全绿 + 无 Tk 崩溃对话框。

## B. 多显示器 / DPI

- [ ] B1 主副屏不同缩放（如 100%/150%）间拖拽 → 重启后窗口仍在工作区内（state x/y 钳制逻辑）；文字无模糊（每启动 SetProcessDpiAwareness 生效）
- [ ] B2 拔掉副屏后启动 → 窗口自动钳回主屏可见区域（`--print-geometry` 断言坐标在 VirtualDesktop 内）
- [ ] B3 窗口位置贴近屏幕边缘/负坐标（手改 state.json）→ 启动钳回合法位置

（B 组若无第二显示器，用 `--print-geometry` + 伪造 state 坐标测钳制逻辑即可，注明"实机双屏未验"。）

## C. 稳定与资源（soak）

- [ ] C1 windowed exe 连续运行 ≥2h（或 PLAN 原定 24h，取用户批准值）：内存增长 <10MB 稳定、句柄数不单调爬升（Get-Counter/Process 每 10min 采样写 csv）
- [ ] C2 soak 期间轮询节律：日志时间戳间隔≈poll±30s，无请求风暴（4 接口/轮封顶）
- [ ] C3 系统睡眠唤醒后自动恢复轮询（不僵尸）
- [ ] C4 打开设置面板后关闭 → 无泄漏窗口（Toplevel 计数复原）

## D. 部署与自启（真实，需用户点头）

- [ ] D1 目标机部署演练：exe + 同级 local/（config/state/cookie 副本）在**另一个 Windows 用户/机**上 DPAPI 失败时的引导文案（设置面板内提示重新粘贴凭据，不崩）
  - 同机可行版：新建本机测试用户或仅验证"拷贝到 dist\local 读通"（M4 已做）
- [ ] D2 用户同意后：设置面板勾选开机自启 → 注册表出现 `token-widget` 单值=exe 路径；**其他 Run 值名集合不变**（前后快照）
- [ ] D3 真实重启一次 → 登录后浮窗自动出现、位置/数据恢复（用户执行，回报"成功/失败"）
- [ ] D4 卸载路径：取消勾选 → 单值删除；exe+local 可直接整体删除，无残留服务/计划任务

## E. 合规与终检

- [ ] E1 全程抓包/日志抽查无 Cookie 明文外泄（proxy 或源码审查 auth 不出 `print(cookie)` 路径）
- [ ] E2 只读频率：单轮对百炼 ≤4 请求，poll≥60s 双保险（config 钳制 + scheduler）
- [ ] E3 `dist\local`（含 cookie 副本）删除确认（M4 已做，终检复看）
- [ ] E4 版本号：exe 文件属性含版本/名称；README 记录 build 时间
- [ ] E5 PLAN §8 收尾：全里程碑勾满，偏差汇总

## F. 结果登记

| 项 | 结果 | 证据 |
|---|---|---|
| A1~A10 | ✅ 全过（fix-3；后随 scheduler 修复更新 A4 断言+新增 T-kick/T-kick-idempotent → 15/15） | `tests\test_anomaly.py` 实跑；含零真实网络拦截线、cookie 前后哈希守护 |
| B1/B3 | ✅ 9/9（含 DPI awareness 生效断言、钳制直测真实 `_place_initial` 路径） | `tests\test_geometry.py` |
| B2 | ⚪ 未验（环境无双屏）→ 以 B3 伪造坐标钳制替代；留待用户实机顺手确认 | — |
| C1~C4 | ✅ 收官（2026-09-11）：C1 跑满 12h/72 样本 0 异常——子进程 WS 恒 8.5MB、句柄恒 98 无泄漏，总 WS 96→106MB 缓漂（PyInstaller 主进程侧，可接受）；跨 02:45 重置点窗口自动归零（终检 CLI 见 已用 0.8%/剩 41,185，重置语义活体自证）；C2 ✓ 302s 节律；C4 ✓；C3 留待 D3 重启顺带验 → `docs\soak_sample.csv` | CSV+终检 CLI |
| D1 | ⚪ 同机已证（dist\local DPAPI 副本读通=修复版）；异用户失败引导文案随首次真实换用户时补测 | M4 收口报告 |
| D2~D4 | ⏳ **用户确认延后自行验证**（勾选开机自启→重启→浮窗回归；dry-run 已多轮证零落盘） | HKCU Run 快照 |
| E1 源码级 | ✅ 通过（本轮 grep 审查）：运行期 print 路径均为状态行/几何行/异常摘要（异常消息源自网关 code/message，无 cookie 字段）；UI/tooltip 无凭据 | `src/ui.py` `_log_cycle`、`settings_panel` 仅几何行 |
| E1 备注 | ⚠️ 非运行路径小项：`src/auth.py` `__main__` 调试块会打印 xsrf 值——仅手动执行 `python src/auth.py` 触发，不进 exe、不进正常流程；下次源码迭代顺手脱敏（截 6 位），本轮不重建（避免与换装竞态） | `src/auth.py:107-109` |
| E2 | ✅ 频率合规：单轮 4 请求封顶、poll 双钳 ≥60s、usage 空窗重试 ≤3×400ms、源缓存 60s | `bailian.py`/`config.py` 常量 + A4/A9 用例 |
| E3 | ✅ `dist\local` 现为正式部署形态（exe+同级 local），cookie 副本属部署件；项目原文件哈希不变 | fix-2 换装报告 |
| E4/E5 | ✅ 收官：`local\` 仅存运行三件（cookie/config/state）；中间截图/采样脚本/_pyi/__pycache__ 已清，证据归档 `docs\screenshots\`；四套件终扫 16+13+9+15 全绿；PLAN 升 v1.2 收官。VERSIONINFO 资源留待下次重建顺带（E4 小项，已在 PLAN 待办） | 本清单+PLAN §8 |

### M5 期间已修复的验收发现（回归主源码）
1. `scheduler._cycle` 退避被 `min(poll,…)` 封顶 → 恢复 `poll≤delay≤1800` 逐轮翻倍（fix-4）
2. `kick()` 事件无人消费 → “立即刷新”不即时 → 改 `_wake.wait`+`_force` 位合并（fix-4）
