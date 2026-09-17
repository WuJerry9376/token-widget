# token-widget M4 打包说明

## 文件构成

| 路径 | 作用 |
|---|---|
| `build/token-widget.spec` | PyInstaller 配置：onefile、windowed（noconsole）、`name=TokenWidget`、图标、hiddenimports、`datas=[]`（**不打包** local/、cookie、config） |
| `build/build.ps1` | 一键重建脚本（见下） |
| `build/icon/make_icon.py` | 图标生成器（纯 stdlib：手写 PNG → PNG-in-ICO，256/48/32） |
| `build/icon/token-widget.ico` | 应用图标（便签风：奶油底 + 卷角），已嵌入 exe |
| `build/_pyi/` | PyInstaller 中间产物（可删，build.ps1 每次清空） |

## 重建 = 跑一条命令

```powershell
pwsh.exe -NoLogo -NoProfile -File "build\build.ps1"
```

- 默认重新生成图标 → 清空 `dist\` 与 `build\_pyi\` → PyInstaller → 产物 PE 校验 → 打印大小/版本/耗时。
- `-SkipIcon`：复用已有 ico（des-2 修完 UI 后重建 exe 时可用，省一次图标生成，~0.1s，无所谓）。
- `-ConsoleVariant`：附加构建 `dist\TokenWidgetConsole.exe`（**仅调试冒烟用**：windowed exe 的 stdout 被重定向到 devnull，看不到 `--verbose` / `--autostart-dry-run` 文本输出时才需要；不随正式版分发）。
- 环境要求：Python 3.12 + PyInstaller 6.x（已装）；入口 `main.py` 相对 spec 的上级目录解析，任意 cwd 可跑。

## 版本号规则（E4：VERSIONINFO）

- `build/version_info.txt` 为 exe 资源版本单一来源（spec `version=` 引用）。
- **每个功能里程碑次版本 +1**：1.0（M4 首包）→ 1.1（M6/M7 合并后）→ 1.2…；
  修订号（第三位）留给热修。升里程碑时同步改 `filevers/prodvers` 与
  `FileVersion/ProductVersion` 字符串。

## 冒烟验证命令（对应当前 dist 产物）

```powershell
# a. 40s 自退 + windowed stdout 防护不崩
Start-Process dist\TokenWidget.exe -ArgumentList '--quit-after','40','--verbose' -PassThru
# b. 自启 dry-run（windowed 无回显，看注册表不变；要看文本用 console 变体）
dist\TokenWidgetConsole.exe --autostart-dry-run
```

## ~~已知问题~~ 已修复（2026-09-10 M4 收口）：frozen 下 `local/` 数据目录解析

> **修复现状**：`src/config.py`、`src/state.py`、`src/auth.py` 三头部已由 orchestrator
> 按下方方案实施（frozen → `Path(sys.executable).parent/"local"`）。收口实证：
> `dist\local\` 部署三文件后，windowed exe 45s 自退 exit=0 且退出时**更新了
> `dist\local\state.json`（mtime 变化，内容合法 x/y/always_on_top）**；console 变体
> `--verbose` 输出 `bailian=OK(剩 16,324 … 63.0%)`（非 NO_CREDENTIAL）→ cookie 经
> exe 同级 `local\` 读取成功。项目根 `local\`（含 DPAPI cookie，哈希
> `FBA4C5…2739` 前后一致）全程未被 exe 触碰。

以下为修复前的原始问题记录（留档）：

`src/config.py`、`src/state.py`、`src/auth.py` 均以
`Path(__file__).resolve().parent.parent / "local"` 解析数据目录。探针 exe 实测证据：

```
frozen: True
_MEIPASS: C:\...\Temp\_MEI00001dcc2
config.LOCAL_DIR:        C:\...\Temp\_MEI00001dcc2\local     ← 进程退出即删除
auth.BAILIAN_COOKIE_FILE: C:\...\Temp\_MEI00001dcc2\local\bailian_cookie.dpapi
```

后果：exe 每次启动都看不到真实配置/窗口位置/DPAPI cookie（冒烟实测界面显示
`bailian=NO_CREDENTIAL`），且会把默认配置写进临时目录后随进程蒸发。**exe 目前功能上
不能读真实凭据，但不崩溃、退出码 0。**

### 已实施的最小修复（M4 收口前由 orchestrator 落地）

三个模块共同的头部逻辑替换为（或抽一个 `src/paths.py` helper 统一引用）：

```python
import sys
from pathlib import Path
if getattr(sys, "frozen", False):
    LOCAL_DIR = Path(sys.executable).resolve().parent / "local"   # exe 同目录
else:
    LOCAL_DIR = Path(__file__).resolve().parent.parent / "local"  # 项目根（现状）
```

涉及行：`config.py:10`、`state.py:11`、`auth.py:16`。不改函数签名与任何业务逻辑。

## 部署目录结构（当前生效形态，收口已实证）

数据在 exe 外部、**exe 同目录的 `local\` 子目录**（修复后形态）：

```
<部署目录>\
  TokenWidget.exe
  local\
    config.json            # 首次运行自动生成默认值
    state.json             # 程序自动写（窗口位置等）
    bailian_cookie.dpapi   # 需从现有环境迁移（DPAPI 与用户账户绑定，
                           # 只能在同一 Windows 用户下解密，复制即有效）
```

不要把 `local\` 打进 exe（spec 中 `datas=[]` 已保证）；凭据/配置外置是设计要求。

## 杀软误报提示

- PyInstaller onefile 自解压 + 无签名的 bootloader 是常见误报诱因（heuristics:
  `Generated:PIEX/Packed` 类）。本项目已做的缓解：**不 UPX**、不打包任何数据。
- 本机现状：Windows Defender 实时保护开启下，构建与多次运行 **0 检出**（冒烟实测）。
- 分发前建议：目标机若用其他杀软先白名单验证；长期方案为代码签名（PLAN §8 R8，成本另议）。

## des-2 修完 UI 后的重建流程（✅ 2026-09-10 已按此完成 M4 收口）

1. `pwsh -File build\build.ps1`（一条命令，含图标；实测 7.5–15s，产物 10.6 MB）
2. 冒烟：`--quit-after 45 --verbose`（退出码 0、无残留进程）+ `--autostart-dry-run`
3. 回归：`python tests\test_render.py`（16）与 `python tests\test_settings.py`（13）
4. local/ 实证：`dist\local\` 放三文件 → state.json 被 exe 更新、console 变体显示
   `bailian=OK`；验证后已删除 `dist\local\`（凭据副本不留 dist）与 console 变体 exe。

## M4 收口结论

- `dist\TokenWidget.exe`（10.6 MB，windowed onefile）= 可分发形态：**exe + 同级
  `local\`** 一起部署；不带 `local\` 时首次运行会自动生成默认 config，凭据需
  用户经设置/续期流写入或从现有环境迁移）。
- 待办移交 M5 验收（PLAN §4 第 8 项）。

## 换装记录

> 规则确认：功能里程碑次版本 +1；非里程碑小修动修订号。**M13 起版本双源同步纪律：
> `src/version.py` APP_VERSION 与 `build/version_info.txt` 三处必须同轮升版，
> tests\test_settings.py:182 看门断言漂移即红（静态 pin 已于 168 改为 X.Y.Z 格式
> 校验，防漂移职责归看门）。**

- **2026-09-16 v1.6.6 换装（M14 / des-3：Codex 5h/周双等尺寸主条对称信息块、组间距
  12 逻辑px、行高 114→100、ui_rows 双主条断言组重写）**：双源升版 version.py +
  version_info.txt（看门 PASS）；门禁 9 套 **136/136 全绿**；重建 **10.7 MB /
  22.3s**，PE 通过，属性 1.6.6（UTF-8 复核）。GBK console 冒烟 exit=0、stderr
  0B，证据行 `轮询完成: bailian=LOGIN_EXPIRED | codex=KEY_INVALID | 下轮 600s`——
  ⚠️ **两行橙态系 dev 机凭据过期（Codex OAuth 401 / Cookie 过期），属数据状态非
  回归；生产机凭据为新，不受影响**。windowed 常驻双进程落位 (2004,24)，全窗高
  实测 **192px**（含双因：行高 114→100 净降 + KEY_INVALID 橙态无 codex 数据块；
  正常态 M14 全窗高以 ui_rows 断言组为准），截图 `local\m14_ship_state.png` 目检
  两行橙档渲染、↻ 在位无异常；HKCU Run **IDENTICAL**；**MpCmdRun 0 检出**；
  console 已删、0 孤儿、0 WER、cookie 基线不变；守卫四件哈希一致、openai 残留
  复净 ✓；dist = exe + local 四件。收口：git commit + tag v1.6.6，禁提交物扫描
  为空。
- **2026-09-15 v1.6.5 换装（M13 / des-5：`src/version.py` 单一版本源
  APP_VERSION、设置面板 foot 行右端 `v{APP_VERSION} · by Jerry Wu` FAINT 档零增高、
  同步看门入 test_settings）**：本轮曾于门禁步**正确中止一次**——168 行过时静态
  pin `== "1.6.4"` 与升版冲突，orchestrator 定档修复（改 X.Y.Z 格式校验）后续跑。
  双源同步：version.py="1.6.5" + version_info.txt 三处 1.6.5（fix-2 换装职责）。
  门禁 9 套 **136/136 全绿**；重建 **10.7 MB / 14.1s**，PE 通过，属性 1.6.5
  （UTF-8 复核）。**GBK console 复验**（v1.6.4 修复回归 + M13 后无 ↻ 类字符）：
  `PYTHONIOENCODING=gbk --quit-after 40 --verbose` exit=0、stderr 0B，行含
  `[ui] 刷新图标超采样光栅化×6：30.7ms` 与 `bailian=LOGIN_EXPIRED | codex=OK(剩 —
  已用 18.0%) | 下轮 600s`（无 openai ✓），验毕 console 已删。守卫四件哈希一致、
  openai 残留复净 ✓；windowed 常驻双进程落位 (2004,24) 330×248 responding=True；
  HKCU Run **IDENTICAL**；**MpCmdRun 0 检出**；0 WER、cookie 基线不变。署名实证
  `python tests\capture_m13.py` → **M13 CAPTURE: PASS**，
  `local\m13_settings_footer.png`（39KB）右端 **v1.6.5 · by Jerry Wu** 上屏。
  收口：git commit + tag v1.6.5，禁提交物扫描（auth.json/dpapi/local//dist/）为空。
- **2026-09-15 v1.6.4 换装（M12h 热修：ui.py:605 日志文案 '↻'→「刷新图标」——
  销案 v1.6.3 轮定档的 console GBK 缺陷）**：门禁 9 套件 **136/136 全绿**；重建
  **10.7 MB / 12.5s**，PE 通过，属性 1.6.4。**修复上二进制实证**：console 变体在
  `PYTHONIOENCODING=gbk` 下 `--quit-after 40 --verbose` **exit=0、stderr 0 字节**，
  证据两行：`[ui] 刷新图标超采样光栅化×6：35.4ms (S=1.000)`（新文案原样穿过 GBK
  管道）与 `轮询完成: bailian=LOGIN_EXPIRED | codex=OK(剩 — 已用 92.0%) | 下轮 60s`
  （橙态预期、无 openai 字段）。注：首轮 GBK 冒烟曾在 dist\local 布置前跑出
  `bailian=NO_CREDENTIAL`——非回归，系部署顺序副作用，布置后重跑即恢复预期态；
  本轮实证以布置后那次为准。守卫四件哈希一致、openai 残留复净 ✓；windowed 正式版
  常驻双进程、落位 (2004,24) 330×248 responding=True；HKCU Run **IDENTICAL** 无
  token-widget 值；**MpCmdRun 0 检出**；console 已删、0 孤儿、0 WER、cookie 基线
  不变；dist = exe + local 四件。
- **2026-09-15 v1.6.3 换装（M12 视觉 / des-3：①设置页代理组未启用整组禁用联动
  ②Codex 标签去「（实验性）」③阈值三色 #EF0000/#FEC211/#3BC371 ④↻ 图标 4× 超采样
  PhotoImage 预旋转 6 帧）**：门禁 9 套件 **136/136 全绿**；重建 **10.7 MB / 13.6s**，
  PE 通过，属性 1.6.3（UTF-8 复核）。守卫四件哈希一致、openai 残留复净 ✓。
  ⚠️ **换装发现源码隐患**：console 调试变体跑 `--verbose` 在 GBK 码页机崩溃
  （`ui.py:605` 新增日志行 `print("↻ 超采样光栅化×6…")`，U+21BB 无 GBK 映射 →
  UnicodeEncodeError，PyInstaller console bootloader 的 stdout 恒绑系统 OEM 码页，
  `PYTHONIOENCODING/PYTHONUTF8` 均不能覆盖）。**交付形态 windowed 不受影响**
  （stdout=None 走 main.py utf-8 devnull 防护，且默认无 --verbose）；正式版常驻
  正常（PID 4392/14444）。建议源码侧后续把该行文案改为「刷新」或去除 ↻ 字符。
  冒烟改用正式版截图存证 `local\m12_ship_icon.png`：窗口 (2004,24) 330×248、
  **↻ 高清在位**、Codex "PLUS 券×1" 无实验性、大数字 16%=5h 剩余、副条「周 已用
  32.0%·5d18h 后重置」短名、bailian 橙「凭据已失效」——M12 四项全部上屏 ✓。
  HKCU Run 前后 IDENTICAL；**MpCmdRun 0 检出**；console 已删、0 错误事件
  （崩溃发生于 console 子进程 stderr，未触 WER）、0 孤儿；dist = exe + local 四件。
- **2026-09-15 v1.6.2 换装（M11d 视觉 / des-3：Codex 行 5h 恒主条、周恒副条固定槽，
  5h 标题去「窗」，大数字随主条 = 5h 剩余%，单边递补与 other:N 规则不变）**：门禁
  9 套件 **136/136 全绿**；重建 **10.7 MB / 13.4s**，PE 通过，属性 1.6.2（UTF-8
  复核）。守卫：四件 COPIED(new) + 哈希一致；openai 残留复净 ✓。冒烟（从简）：
  console 证据行 `轮询完成: bailian=LOGIN_EXPIRED | codex=OK(剩 — 已用 44.0%) |
  下轮 600s`——无 openai 字段 ✓；常驻双进程、窗口 (2004,24) 高 **248px** 实值、
  responding=True；HKCU Run 前后 **IDENTICAL** 无 token-widget 值。**MpCmdRun
  0 检出**。console 已删、0 孤儿、0 WER、cookie 基线不变；dist 结构 = exe + local
  四件。
- **2026-09-15 v1.6.1 换装（M11c 视觉 polish / des-3：副条尾注字档统一、
  「周窗·5h窗」短名、券×N 字重降档、细条方向锚字定案——加油包右文案补「剩」字、
  codex 保「已用」）**：修订号规则首次启用（非里程碑小修 → 第三位 +1）。门禁 9 套件
  **136/136 全绿**；重建 **10.7 MB / 13.9s**，PE 通过，属性 1.6.1（UTF-8 复核）。
  守卫：build 清 dist → 四件（config/state/cookie/auth.json）COPIED(new) + 哈希
  一致；残留复净（两处无 openai_admin_key、dist config 无 "openai"）✓。冒烟（从简）：
  console 证据行 `轮询完成: bailian=LOGIN_EXPIRED | codex=OK(剩 — 已用 22.0%) |
  下轮 600s`——无 openai 字段 ✓；常驻双进程（窗口 15960）responding=True、落位
  (2004,24) 高 248px；HKCU Run 前后 **IDENTICAL** 无 token-widget 值。**MpCmdRun
  0 检出**。console 已删、0 孤儿、0 WER、cookie 基线不变；dist 结构 = exe + local
  四件。
- **2026-09-15 v1.6.0 全量换装（M11a：OpenAI API 侧全量移除——registry 三家、
  openai.py/test_m6_openai 删除、admin key 两处清零、config/面板/代理作用域同步；
  M11b：Codex 行双窗进度条 + 券角标、行高 116→114）**：预构建门禁 **9 套件 136/136
  全绿**（16+13+9+15+22+15+18+8+20）；版本三处升 1.6.0；重建 **10.7 MB / 26.3s**，
  PE 通过，属性 1.6.0（UTF-8 复核中文无误）。守卫：四件（config 9/15 新含
  codex 无 openai / state / cookie / **auth.json 凭据副本随部署走**）全
  COPIED(new) + 哈希一致；**陈旧扫描：两处均无 openai_admin_key.dpapi、dist config
  不含 "openai"** ✓。冒烟：console 证据行 `轮询完成: bailian=LOGIN_EXPIRED |
  codex=OK(剩 — 已用 19.0%) | 下轮 600s`——**无 openai 字段**、codex 真实链路 OK；
  常驻双进程（5768/11764）responding=True、窗口 (2004,24) 高 **248px** = M11b 新行
  高实值（330×248）；`--print-geometry` 直启不吸；dry-run 单参数 + windowed
  exit=0、HKCU Run 前后 IDENTICAL（系统侧 EdgeAutoLaunch 值为快照期既有，与本任务
  无关）、无 token-widget 值。**MpCmdRun 0 检出**。console 已删、0 孤儿、0 WER；
  dist 结构 = exe + local 四件。
- **2026-09-15 v1.5.0 全量换装（M10b Codex 真实联调定修 / fix-6：`originator:
  codex_cli_rs` + Sec-Fetch 头组过 Cloudflare、禁发 Accept-Encoding、
  `auth.find_codex_auth` 三候选自动读取（local\auth.json → exe 同级\auth.json →
  ~/.codex）、绑定面板检测行三态、Usage.note 重置券、真实链路 plus/周窗 3% 实证；
  enabled 与 proxy targets 均已含 codex）**：预构建门禁 **10 套件 151/151 全绿**
  （16+13+9+15+15+22+15+18+8+20）；版本三处升 1.5.0；重建 **10.7 MB / 10.7s**，
  PE 通过，属性 1.5.0（UTF-8 复核中文无误）。守卫：build 清 dist 后**五件**全
  COPIED(new)、项目=dist 哈希逐一一致——含 config.json（23:58 含 codex）与**新增
  `dist\local\auth.json`（用户 Codex OAuth 凭据副本，3886B，frozen 候选①路径，
  ⚠️ 属敏感凭据：随 dist 部署整体走，分发/清理时按凭据对待）**。冒烟：console
  证据行 `轮询完成: bailian=LOGIN_EXPIRED | openai=OK(剩 —) | codex=OK(剩 — 已用
  3.0%) | 下轮 600s`——**codex=OK 真实链路**（周窗 3% 与联调实证一致；bailian 橙态
  既有事实）；常驻双进程（12452/10284）responding=True、窗口 (2004,24) = state
  落位、窗口高 120→358px（三行数据渲染）；`--print-geometry` 三行 `+2004+24` 直启
  不吸；dry-run 单参数绝对路径 + windowed exit=0、HKCU Run 前后 **IDENTICAL**。
  **MpCmdRun 0 检出**。console 已删、0 孤儿、0 WER；dist 结构 = exe + local 六件。
- **2026-09-14 v1.4.0 全量换装（M10 第 4 家 provider "Codex"：ChatGPT Plan 窗口
  限额——auth.detect_codex_token + sources/codex.py + 设置页第 4 框/绑定面板 +
  registry/config/ui/cli 触点；⚠️ 实验性，默认不启用，enabled 不含 codex 时零网络
  调用）**：**预构建门禁 10 套件 148/148 全绿**（16+13+9+15+15+22+15+18+8+17）后进
  构建；`version_info.txt` 三处升 1.4.0；重建 **10.7 MB / 9.8s**，PE 通过，属性
  FileVersion/ProductVersion **1.4.0**（UTF-8 复核）。守卫：build 清 dist 后四件
  （config/state/cookie/admin_key）全 **COPIED(new)**、项目=dist 两凭据哈希一致；
  **无 codex secret 文件（实验性未绑，属预期）**。冒烟：registry 四源齐
  `[bailian, openai, opencode_go, codex]`；常驻双进程（2752/10192）responding=True、
  窗口 **(2004,24) = state 现值**（M10 测试期 20:21 用户拖位写回，非旧 1800,310，
  守卫按 mtime 新者同步）；console 证据行 `轮询完成: bailian=LOGIN_EXPIRED |
  openai=OK(剩 —) | 下轮 600s`——**无 codex 字段**（默认不启用零调用 ✓）、openai
  经代理 OK、bailian 橙态为 cookie 过期既有事实；`--print-geometry` 三行均
  `+2004+24` = 直启不吸 ✓；dry-run 单参数绝对路径 + windowed exit=0、HKCU Run
  名集合前后 **IDENTICAL** 无 token-widget 值。**MpCmdRun 定点扫描 0 检出**。
  console 已删、0 孤儿、0 WER；项目 local 四件时间戳未被构建触碰。
- **2026-09-14 v1.3.0 全量换装（四里程碑收编：↻ 旋转反向（des-2）→ REGION_BLOCKED
  分类 + 测试连通三态（fix-5）→ M9 贴边吸附 + REGION 橙档（des-3）→ usd "余额未知"
  显示微调（des-4））**：**预构建门禁 9 套件 131/131 全绿**（16+13+9+15+15+22+15+18+8）
  后进构建；`version_info.txt` 三处升 1.3.0；重建 **10.7 MB / 16.6s**，PE 通过，
  属性 FileVersion/ProductVersion **1.3.0**（UTF-8 复核）。守卫：build 清 dist 后
  四件（config/state/cookie/**openai_admin_key.dpapi 新增**）全部 COPIED(new)，
  项目与 dist 哈希两两一致（config 含 enabled openai + network.proxy 127.0.0.1:7890
  如实同步）。冒烟：常驻双进程（6916/16248）responding=True、窗口 (1800,310) =
  state 落位；console 证据行 `轮询完成: bailian=LOGIN_EXPIRED | openai=OK(剩 —) |
  下轮 600s`（openai=OK 经代理链路成功，"剩 —"即 des-4 余额未知显示；bailian 橙态
  为 cookie 过期既有事实非回归）；`--print-geometry` 三行均 `+1800+310` = M9 直启
  不吸 ✓；dry-run 单参数绝对路径、HKCU Run 名集合前后 IDENTICAL 且无 token-widget
  值、windowed 正式版 dry-run exit=0。**MpCmdRun 定点扫描 0 检出**。console 变体
  已删、0 孤儿、0 WER 事件；项目 local 四件时间戳未被构建触碰（config 17:09:53 /
  state 18:04:58 为用户测试期正常值）。
- **2026-09-14 v1.2.0 全量换装（M8 网络代理：netconfig + config.network + 境外源
  opener 注入 + 设置页代理分组两态按钮；M8 视觉轮：按钮态/行距/全角回归锁）**：
  `version_info.txt` 升 1.2.0（三处），`build.ps1` 重建 **10.7 MB / 18.2s**，PE 通过，
  属性 FileVersion/ProductVersion **1.2.0**（UTF-8 复核中文产品名无误）。cookie 守卫
  执行：build.ps1 清空 dist 后 `dist\local` 三件全部 **COPIED(new)**、无覆盖/跳过
  （项目 cookie 哈希 = 基线 `FBA4C5…2739` 不变；项目 state mtime 9/14 系 M8 开发期
  刷新，属预期）。常驻拉起：双进程（152/13064）responding=True、窗口 (1800,310) =
  state 位置。console 变体证据行：`轮询完成: bailian=LOGIN_EXPIRED | 下轮 600s`
  （橙态属既有事实非回归；仅 bailian 一行 = openai/go 零调用；600s 为退避生效）。
  dry-run：单参数绝对路径形态（console 代跑捕获，windowed 正式版同函数 exit=0）、
  HKCU Run 值名集合前后一致且无 token-widget 值。**MpCmdRun 定点扫描 0 检出**。
  console 变体已删；dist 仅正式版 + local。
- **2026-09-11 v1.1.0 全量换装（M6 OpenAI/Go 实装 + M7 加油包细条/↻/审查修复 + E4
  VERSIONINFO）**：`build.ps1 -ConsoleVariant` 重建 **10.7 MB / 26.2s**，PE 通过；
  exe 属性 FileVersion/ProductVersion **1.1.0**、ProductName "Token 余量浮窗"、
  FileDescription "LLM API 额度桌面浮窗"、语言 0x0804/0x04b0（PowerShell 控制台
  显示乱码仅为码页因素，UTF-8 复核为真字符）。部署 `dist\local\` 三件（无 M6 新
  dpapi 密钥文件）。冒烟：console 45s 显示 `轮询完成: bailian=OK(剩 38,9xx 已用
  6.4%)` 且仅 bailian 一行（openai/go 不在 enabled → 零网络调用）；windowed 常驻
  双进程 responding=True、窗口 (1800,310) = state 位置；dry-run 输出 exe 绝对路径
  单参数、HKCU Run 值名集合前后一致；截图 `local\ship_m7.png` 见加油包细条
  "1,508 / 20,000" 与底行一致、↻ 在位；**Defender MpCmdRun 定点扫描 0 检出**。
  项目 cookie 哈希 `FBA4C5…2739` 不变。console 变体已删，dist 仅正式版 + local。
- **2026-09-10 M5 换装重建（含 scheduler 修复版：退避公式 + kick 唤醒）**：
  `build.ps1` 重建 10.6 MB / 7.3s，PE 校验通过；杀旧实例（PID 6004/8668）→ 重布
  `dist\local\` 三件 → 新版常驻（PID 3820/15480，responding=True，WER 0 事件）。
  frozen local/ 读取行为证据：窗口物理位置 L=1800 = `dist\local\state.json` 的
  x=1800（state 回写仅发生在拖拽/退出时，常驻 15s 内无 mtime 属正常）。项目原
  cookie 哈希复核 `FBA4C5…2739` 不变。采样器（`local\soak_sampler.ps1`，PID 8388）
  存活；csv 无采样行系脚本自身缺陷：onefile 恒 2 进程使第 7 行
  `[math]::Round($p.WorkingSet64/1MB)` 抛 `op_Division`，与换装间隙无关（55s 间隙
  未落入任何 600s 采样点，EXITED/miss 行 = 0）。

## 发布新 release（M15 自动更新的服务器侧）

> 客户端更新源 = GitHub Releases 最新 release 的 `TokenWidget.exe` 资源（settings_panel/updater）。
> repo slug 默认 `WuJerry9376/token-widget`（public，config DEFAULTS 内置；客户端可在
> `local\config.json` 的 `update.repo` 覆盖，构建侧代码不写死）。

1. 更新 `build\version_info.txt` 与 `src\version.py` 的 APP_VERSION（两者必须一致，settings 门禁校验）
2. `pwsh -File build\build.ps1` → 产出 `dist\TokenWidget.exe`
3. 打 tag 并发布（repo 已定仓）：

```powershell
gh release create v<版本> dist\TokenWidget.exe --repo WuJerry9376/token-widget --generate-notes --latest
```

- 资源名必须保持 `TokenWidget.exe`（updater 按名匹配；多 .exe 且无主名时客户端宁缺勿错）
- tag 用 `vX.Y.Z` 形态（客户端会去 v 前缀做三段数字比较，semver 非数字尾缀会被截断）
- 客户端 6h 频控 + 定时只读提示；下载/替换仅用户明确动作触发（见 README「更新」小节安全说明）
