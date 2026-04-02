# -*- coding: utf-8 -*-
"""
Voice Bridge 托盘系统
- 基于 pystray + PIL
- 单击：显示/隐藏控制台窗口
- 双击：打开主页
- 右键：菜单
"""
import os
import sys
import time
import webbrowser
import logging
import threading
from typing import Optional

from shared.network import get_local_ip

# 托盘依赖
try:
    from pystray import Menu, MenuItem
    from pystray._win32 import Icon as Win32Icon
    import pystray._win32 as _win32_module
    _win32api = _win32_module.win32
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

logger = logging.getLogger("vb")

# 配置存储（默认详细模式）
_config: dict = {
    "console_visible": True,
    "log_mode": "detail",  # 默认为详细模式
}
_config_file = os.path.join(os.path.dirname(__file__), "..", "tray_config.json")


def _load_config() -> None:
    global _config
    try:
        if os.path.exists(_config_file):
            import json
            with open(_config_file, "r", encoding="utf-8") as f:
                _config.update(json.load(f))
    except Exception:
        pass


def _save_config() -> None:
    try:
        import json
        with open(_config_file, "w", encoding="utf-8") as f:
            json.dump(_config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _create_icon_image():
    """创建托盘图标（麦克风）"""
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new('RGB', (size, size), color=(52, 152, 219))
    draw = ImageDraw.Draw(img)
    draw.ellipse([12, 4, 52, 44], fill=(255, 255, 255))
    draw.rectangle([24, 44, 40, 58], fill=(255, 255, 255))
    draw.arc([8, 46, 56, 62], 0, 180, fill=(255, 255, 255), width=3)
    return img


def _open_home(icon=None, item=None) -> None:
    """打开主页"""
    webbrowser.open("http://localhost:7266")


def _toggle_console(icon=None) -> None:
    """切换控制台窗口显示/隐藏"""
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            _config["console_visible"] = not _config["console_visible"]
            ctypes.windll.user32.ShowWindow(hwnd, 5 if _config["console_visible"] else 0)
            _save_config()
            logger.info(f"控制台{'显示' if _config['console_visible'] else '隐藏'}")
    except Exception as e:
        logger.warning(f"切换控制台失败: {e}")


def _set_log_mode(mode: str) -> None:
    """设置日志模式"""
    _config["log_mode"] = mode
    _save_config()
    try:
        from shared.logging import set_log_mode
        set_log_mode(mode)
    except Exception:
        pass
    logger.info(f"日志模式: {mode}")


def _toggle_console_output(enabled: bool) -> None:
    """设置控制台日志输出开关（只控制日志，不影响窗口）"""
    _config["console_output"] = enabled
    _save_config()
    try:
        from shared.logging import set_console_output
        set_console_output(enabled)
    except Exception:
        pass
    logger.info(f"控制台输出: {'开启' if enabled else '关闭'}")


def _show_logs(icon=None, item=None) -> None:
    """打开日志文件"""
    try:
        from shared.logging import get_log_file_path
        log_path = get_log_file_path()
    except Exception:
        log_path = os.path.join(os.path.dirname(__file__), "..", "logs", "vb.log")
    if os.path.exists(log_path):
        os.startfile(log_path) if sys.platform == "win32" else webbrowser.open(log_path)
    else:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)


# 记录父进程（bat 脚本）的控制台窗口句柄
_parent_console_hwnd = None


def _close_launcher_window():
    """关闭 bat 启动脚本的 cmd 窗口"""
    try:
        import ctypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        WM_CLOSE = 0x0010
        
        # 通过窗口标题找到 "Voice Bridge Launcher" 窗口
        launcher_title = "Voice Bridge Launcher"
        hwnd = user32.FindWindowW(None, launcher_title)
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    except Exception:
        pass


def _init_parent_console():
    """初始化父进程控制台窗口句柄（由 main.py 调用）"""
    global _parent_console_hwnd
    try:
        import ctypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        # 获取当前控制台窗口句柄
        _parent_console_hwnd = user32.GetConsoleWindow()
    except Exception:
        pass
    # 立即关闭启动器的 cmd 窗口
    _close_launcher_window()


def _restart_service(icon=None, item=None) -> None:
    """重启服务：关闭当前控制台，启动新控制台"""
    global _icon, _parent_console_hwnd
    
    # 先停止托盘图标
    if _icon:
        _icon.stop()
        _icon = None
    
    def _close_server_window():
        """关闭当前 Voice Bridge Server 窗口"""
        try:
            import ctypes
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            WM_CLOSE = 0x0010
            # 通过标题关闭窗口
            hwnd = user32.FindWindowW(None, "Voice Bridge Server")
            if hwnd:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            # 也关闭记录的主控台窗口
            if _parent_console_hwnd:
                user32.PostMessageW(_parent_console_hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass
    
    try:
        import subprocess
        script_path = os.path.join(os.path.dirname(__file__), "main.py")
        CREATE_NEW_CONSOLE = 0x00000010
        # 启动新进程（新建控制台窗口）
        subprocess.Popen(
            [sys.executable, script_path],
            creationflags=CREATE_NEW_CONSOLE,
            cwd=os.path.dirname(script_path)
        )
        # 关闭当前窗口
        _close_server_window()
    except Exception as e:
        logger.error(f"重启失败: {e}")
    os._exit(0)


def _exit_app(icon=None, item=None) -> None:
    """退出程序"""
    global _icon
    if _icon:
        _icon.stop()
    os._exit(0)


# ===== 自定义 Icon：支持双击左键打开主页 =====
class TrayIcon(Win32Icon):
    def __init__(self, *args, on_double_click=None, **kwargs):
        self._on_double_click = on_double_click
        self._last_click_time = 0
        super().__init__(*args, **kwargs)

    def _on_notify(self, wparam, lparam):
        if lparam == _win32api.WM_LBUTTONUP:
            now = time.time()
            if self._on_double_click and (now - self._last_click_time) < 0.3:
                # 双击
                self._on_double_click(self)
            else:
                # 单击
                _toggle_console(self)
            self._last_click_time = now
        elif lparam == _win32api.WM_RBUTTONUP:
            # 右键显示菜单
            super()._on_notify(wparam, lparam)


# 全局变量
_icon: Optional[TrayIcon] = None


def _create_menu() -> Menu:
    """创建右键菜单（使用 checked 回调实现动态勾选）"""
    return Menu(
        MenuItem("打开主页", _open_home),
        Menu.SEPARATOR,
        MenuItem("日志模式", Menu(
            MenuItem("简洁", lambda: _set_log_mode("simple"), checked=lambda item: _config.get('log_mode') == 'simple'),
            MenuItem("详细", lambda: _set_log_mode("detail"), checked=lambda item: _config.get('log_mode') == 'detail'),
        )),
        MenuItem("控制台输出", Menu(
            MenuItem("开启", lambda: _toggle_console_output(True), checked=lambda item: _config.get('console_output', True)),
            MenuItem("关闭", lambda: _toggle_console_output(False), checked=lambda item: not _config.get('console_output', True)),
        )),
        Menu.SEPARATOR,
        MenuItem("查看日志文件", _show_logs),
        MenuItem("重启服务", _restart_service),
        Menu.SEPARATOR,
        MenuItem("退出", _exit_app),
    )


def start_tray() -> None:
    """启动托盘"""
    global _icon

    if not HAS_TRAY:
        logger.warning("pystray 未安装，托盘功能不可用")
        return

    if _icon is not None:
        return

    _load_config()

    def _run_tray():
        global _icon
        try:
            img = _create_icon_image()
            _icon = TrayIcon(
                "Voice Bridge",
                img,
                menu=_create_menu(),
                on_double_click=_open_home,  # 双击 → 打开主页
            )
            _icon.run(setup=False)
        except Exception as e:
            logger.error(f"托盘启动失败: {e}")

    thread = threading.Thread(target=_run_tray, daemon=True, name="VB-Tray")
    thread.start()
    logger.info("系统托盘已启动")


def stop_tray() -> None:
    """停止托盘"""
    global _icon
    if _icon:
        _icon.stop()
        _icon = None
