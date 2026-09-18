# HANDOVER — token-widget 维护交接文档

> 供**其他会话**接手本项目维护的第一入口。读本文件 + 按"接手顺序"读其余文档后，即可安全开工。
> 快照时间：2026-09-22，HEAD=`9fae0c7`，工作树干净。

## 0. 项目一句话
Windows 桌面便笺风额度浮窗：**百炼 Token Plan / OpenCode Go / ChatGPT Codex（实验性）** 余量显示。单 exe、stdlib-only、GitHub Releases 自更新。

- 仓库：`https://github.com/WuJerry9376/token-widget`（public）
- 当前发布：**v1.9.1**（`releases/latest` 已复验）；本地 `dist\TokenWidget.exe`=1.9.1，**桌面常驻双进程运行中**
- 质量基线：**11 套 187 项测试全绿**（`pwsh -File tests\run_all_m9b.ps1`）

## 1. 接手顺序（新会话先读）
1. 本文件（纪律与坑）
2. `PLAN.md`（需求决策史+里程碑账，§7 是用户裁决记录）
3. `docs/operations.md`（运维手册全文：绑定细节/显示语义表/合规细节）
4. `build/README.md`（**发版 SOP**，含版本号规则与每次换装记录）
5. 涉及线路改动前读对应 spec：`docs/bailian_gateway_spec.md`、`docs/openai_go_wire_spec.md`、`docs/codex_chatgpt_wire_spec.md`（均为逐字节实测提取，**唯一事实来源**）

## 2. 铁律清单（违反即事故）
### 凭据
- `.gitignore` 已排除：`local/`、`dist/`、根 `auth.json`、`*.dpapi`、`scripts/dbg_archive/`——**任何提交前跑禁入扫描**：`git ls-files | Select-String 'auth\.json|dpapi|^local/|^dist/'` 必须空
- 凭据哈希基线：`local\bailian_cookie.dpapi` = `FBA4C5B5DD94553871511DA622A6C7701E6660CFF4076EBB0734A32513452739`（用户续期后内容变更正常；测试守卫要求的是"测试运行前后不变"）
- Cookie/token 值**绝不打印/回显/入日志**；DPAPI 绑机绑用户，异机=重新粘贴
- 根目录 `auth.json` 是用户投放的**明文 ChatGPT OAuth** 联调凭据：只读使用，处置（转 DPAPI/删除）需用户下令

### 门禁与环境坑
- 全绿是 commit/release 硬前置；**跑门禁不要设 `PYTHONIOENCODING=utf-8`**（干扰子进程捕获→test_settings 假红）
- 本机无 `rg`，用 `Select-String`；PowerShell 用 `pwsh.exe`（PS7）
- 本机会话**非管理员**：改显示器缩放/禁用虚拟屏/写 HKLM 均需提权——遇到就报告，不硬闯

### 发版（细节见 build/README，流程摘要）
1. 双源升版：`src/version.py` + `build/version_info.txt`（三处）——test_settings 有**看门断言**，漏一处必红；README A6 版本近况行同步
2. 版本规则：功能里程碑 →次版本+1；小修 →修订号+1
3. `build.ps1` 构建；**它先清 dist 再要求复布 `dist\local`**（守卫：逐文件 mtime 新者胜；顺序错了首跑会 NO_CREDENTIAL 假象）
4. 冒烟：GBK console 验证（历史修复不许回退）+ windowed 常驻 + 注册表 HKCU Run 快照 IDENTICAL + MpCmdRun 定向扫描
5. git：commit → annotated tag → `git pull --rebase` → push --follow-tags → `gh release create vX.Y.Z dist\TokenWidget.exe`（gh 全路径 `C:\Program Files\GitHub CLI\gh.exe`，已授权 WuJerry9376）
6. 门面素材若因 UI 文案/版本过时：重拍 `tests/capture_m24.py` → 更新 `docs/screenshots/feature_*`（已知滞后：settings 图 foot 仍 v1.9.0）

### 数据源不变量
- 百炼：控制台网关（**非官方**），Cookie 会过期→橙态续期流是特性不是 bug；**百炼永不走代理**
- Codex：请求必带 `originator: codex_cli_rs`（缺=Cloudflare 403 challenge）；**禁发 Accept-Encoding**（gzip/br 无解码器）；401=token 过期走橙档
- OpenCode Go：**Zen key 打 Go 端点必 403**；自动检测只认 `opencode-go` 条目 type=api
- 更新链 M28 起**无 cmd**：marker 驱动、新实例自我改名接管；`restart_update.cmd` 已永久退役（测试有禁回流断言）
- 区域封锁 403（unsupported_country_region_territory）→ `REGION_BLOCKED` 橙档"换海外节点"，**不得**报成密钥无效

### UI 纪律
- 全几何 `P(逻辑px)×S`；字号一律 `font_pixel_size` 负像素制；PMv2 DPI（进程值应为 2）
- 用户可见文案：**零「窗口」字样、零「~5h」**（有全画面禁字断言）；三色 `#3BC371/#FEC211/#EF0000`；细条方向锚字规则（codex/Go 条「已用」向、百炼加油包「剩」向）
- M3c 像素纯净判据（顶边条带/蒙版外=0）任何渲染改动后复测
- 常驻实例：非重建换装**不要杀**；窗口落位 state.json=(2004,24)

## 3. 架构地图（改哪里去哪找）
| 域 | 文件 | 要点 |
|---|---|---|
| 采集 | `src/sources/{bailian,bailian_gateway,opencode_go,codex}.py` | Usage 统一契约 `base.py`（plan_end/note/windows）；各家 60s 缓存+fetch_now |
| 调度 | `src/scheduler.py` | 线程→queue→`root.after`；退避 `poll≤d≤1800`；kick 位合并 |
| 渲染 | `src/ui.py` | 单一 Canvas；行分派 percent/usd/credits；`_rot_raise` 层序收口 |
| 设置/面板 | `src/settings_panel.py` | _Card 语言；ProviderKeyPanel/UpdateDialog；foot 图标 assets 四档 |
| 凭据 | `src/auth.py` | DPAPI 原子写；`find_codex_auth` 三候选搜索序 |
| 更新 | `src/updater.py` | 检查频控 6h+日期戳；下载 direct→proxy→mirror 回退+SHA-256 锚；swap=main.py 启动早期 marker 消费 |
| 代理 | `src/netconfig.py` | normalize/脱敏 `sanitize_proxy_msg`；targets 白名单机制 |
| 打包 | `build/{token-widget.spec,build.ps1,version_info.txt}` | datas=assets；console 变体**不经 spec**（无 assets，调试注意） |
| 测试 | `tests/run_all_m9b.ps1` | 11 套 187；capture_* 为像素取证工具 |

## 4. 待办与已知边界（接手后别当新 bug）
1. **D 组重启演练**（用户择机）：设置勾自启→重启→验证浮窗回归（autostart 只写 HKCU Run 单值 `token-widget`）
2. **混缩真机 DPI 实渲**：PMv2 已交付并同 DPI 跨屏实证；真 150% 档未验——遇混合缩放硬件跑 `tools/diag/diag_m26_xscreen.py` 补
3. 虚拟屏 DISPLAY9（1920×1080@96）仍连接未禁用（需提权/用户设备管理器）；`test_geometry` 等按动态枚举写，勿硬编码屏数
4. 加油包"到期日"UI 展示：`sources` 已可得 endTime，契约未透出（一行扩展+渲染）——用户未裁决
5. Codex token 自动 refresh（refresh_token 轮换落盘）=二期候选；当前过期=橙态重贴
6. dev 机两凭据过期（bailian Cookie / Codex token）显示橙态=**数据态非 bug**（用户明示不管）
7. 生产机部署=Releases 下载或整 dist 拷走（含 auth.json 副本按凭据对待）

## 5. 里程碑史（略读版，全文 PLAN.md §8）
M0-M5 调研/采集/浮窗/设置/打包（百炼先行）→ M6-M7 OpenAI·Go 实装+加油包条+↻ 按钮 → M8-M11a 代理/REGION 分类/贴边吸附/版本 foot（**OpenAI API 侧经用户裁决整体移除**，代码留 wire spec）→ M10/M21 Codex provider+官方 Invertocat 图标（AGENTS.md 有跨项目图标规则）→ M15-M19 更新机制全链+弹窗化 → M23-M24 套餐到期/Go 三主条/高光绝对阈/去窗字 → M26 PMv2 DPI → M28-M29 无 cmd 更新链+README 使用者化。**用户风格**：小步快跑、验收制、诚实文案反感浮夸、装饰性内容从严。
