"""应用版本号单一事实源（M13：设置面板右下角版本签名取自此处）。

同步纪律：每次重建换装，本值随 build\\version_info.txt 同步升版
（filevers/prodvers 元组、FileVersion、ProductVersion 三处一并改）——
该同步由 fix-2 换装流程负责执行；tests\\test_settings.py 的
settings_render 用例做机器看门（断言 APP_VERSION 必出现在
version_info.txt 中），漏同步即门禁红。
"""

APP_VERSION = "1.6.6"
