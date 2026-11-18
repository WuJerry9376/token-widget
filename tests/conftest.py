"""pytest 会话级卫生（2026-11-18 flake 取证后新增）。

根因链（frame dump 实证）：套件里 test_render/test_geometry/test_m26_dpi 等
创建过真实 Tk root 与 tkfont.Font（绑定创建线程的 Tcl 解释器）。测试结束后
Font 对象滞留待回收；当**某个 worker 线程**恰好把分配推过 GC 阈值，
`Font.__del__` 的跨线程 Tcl 删除在该线程执行——主线程没在 pump 事件循环，
调用永久阻塞（现场：bailian-interactive-login 卡在 font.py:__del__，
cmds=[] queue=0，15s 不自愈）。属测试卫生问题，产品主循环常驻 pump 不受此道。

对策：会话期间关闭分代 GC（套件体量小，内存无压力），结束后统一回收。
"""
import gc


def pytest_configure(config):
    gc.collect()
    gc.disable()


def pytest_unconfigure(config):
    try:
        gc.enable()
        gc.collect()
    except Exception:
        pass
