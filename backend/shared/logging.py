# -*- coding: utf-8 -*-
"""
Voice Bridge 统一日志工具
=========================
- 支持 traceId 上下文追踪
- 多级日志模式：简洁模式（默认）/ 详细模式 / 调试模式
- 调试模式：包含 PID、全局状态、调用栈
- 文件日志为主，控制台美化输出
- 完整的异常处理记录
- Windows ANSI 颜色支持
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
import json
import threading
import traceback as tb_module
from contextvars import ContextVar
from pathlib import Path
from datetime import datetime
from typing import Optional

# Windows ANSI 颜色支持
_WINDOWS_ANSI = False
try:
    import colorama
    colorama.init(autoreset=True, strip=False)
    _WINDOWS_ANSI = True
except ImportError:
    pass

# ==================== 模块加载时禁用 Pillow 冗余日志（必须提前执行）====================
# 解决 Pillow Image.py:388 刷屏问题 - 必须在 Pillow 被导入前执行
try:
    _pil_logger = logging.getLogger("PIL")
    _pil_logger.setLevel(logging.WARNING)
    _pil_logger.propagate = False
except Exception:
    pass

try:
    _pil_img_logger = logging.getLogger("PIL.Image")
    _pil_img_logger.setLevel(logging.WARNING)
    _pil_img_logger.propagate = False
except Exception:
    pass

# 禁用 asyncio Proactor 冗余日志
try:
    _asyncio_logger = logging.getLogger("asyncio")
    _asyncio_logger.setLevel(logging.WARNING)
    _asyncio_logger.propagate = False
except Exception:
    pass

# ==================== 调试模式控制 ====================
# 优先级：命令行参数 > 环境变量 > 配置文件
_DEBUG_MODE: bool = False
_DEBUG_CONFIG_FILE: str = ""


def _load_debug_config() -> bool:
    """从配置文件加载调试模式设置"""
    global _DEBUG_CONFIG_FILE
    config_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "tray_config.json"),
        os.path.join(os.path.dirname(__file__), "..", "tray_config.json"),
        "tray_config.json",
    ]
    for path in config_paths:
        if os.path.exists(path):
            _DEBUG_CONFIG_FILE = path
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return config.get("debug", False)
            except Exception:
                pass
    return False


def is_debug_mode() -> bool:
    """检查是否开启调试模式（优先级：命令行 > 环境变量 > 配置文件）"""
    global _DEBUG_MODE
    
    if _DEBUG_MODE:
        return True
    
    # 检查命令行参数
    if "--debug" in sys.argv:
        _DEBUG_MODE = True
        return True
    
    # 检查环境变量
    if os.environ.get("VB_DEBUG", "").lower() in ("1", "true", "yes"):
        _DEBUG_MODE = True
        return True
    
    # 检查配置文件
    if _load_debug_config():
        _DEBUG_MODE = True
        return True
    
    return False


def set_debug_mode(enabled: bool) -> None:
    """设置调试模式"""
    global _DEBUG_MODE
    _DEBUG_MODE = enabled
    
    # 同步到配置文件
    if _DEBUG_CONFIG_FILE:
        try:
            with open(_DEBUG_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            config["debug"] = enabled
            with open(_DEBUG_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def get_debug_mode() -> bool:
    """获取调试模式状态"""
    return is_debug_mode()


# ==================== 全局配置 ====================
_log_mode: str = "detail"  # "simple" | "detail" | "debug"
_log_file_path: str = ""
_enable_console: bool = False
_console_handler: Optional["logging.StreamHandler"] = None

# ==================== 全局状态注册表 ====================
# 用于定期打印全局状态
_global_state_getters: dict[str, callable] = {}
_state_print_lock = threading.Lock()
_last_state_print_time: float = 0
_STATE_PRINT_INTERVAL: float = 10.0  # 10秒打印一次


def register_state_getter(name: str, getter: callable) -> None:
    """注册全局状态获取函数"""
    _global_state_getters[name] = getter


def unregister_state_getter(name: str) -> None:
    """取消注册全局状态获取函数"""
    _global_state_getters.pop(name, None)


def _print_global_state(logger: logging.Logger) -> None:
    """打印全局状态（DEBUG模式专用）"""
    global _last_state_print_time
    
    if not is_debug_mode():
        return
    
    now = time.time()
    if now - _last_state_print_time < _STATE_PRINT_INTERVAL:
        return
    
    with _state_print_lock:
        if now - _last_state_print_time < _STATE_PRINT_INTERVAL:
            return
        _last_state_print_time = now
    
    state_parts = []
    for name, getter in _global_state_getters.items():
        try:
            value = getter()
            state_parts.append(f"{name}={value}")
        except Exception as e:
            state_parts.append(f"{name}=<error: {e}>")
    
    if state_parts:
        logger.debug(f"[全局状态] {' | '.join(state_parts)}")


# ==================== traceId 上下文 ====================
_current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)
_current_device_id: ContextVar[str | None] = ContextVar("current_device_id", default=None)


def generate_trace_id() -> str:
    """生成 8 位短 traceId"""
    return uuid.uuid4().hex[:8]


def generate_request_id() -> str:
    """生成 16 位请求 ID"""
    return uuid.uuid4().hex[:16]


def set_trace_id(trace_id: str) -> None:
    _current_trace_id.set(trace_id)


def get_trace_id() -> str | None:
    return _current_trace_id.get()


def clear_trace_id() -> None:
    _current_trace_id.set(None)


def set_device_id(device_id: str) -> None:
    _current_device_id.set(device_id)


def get_device_id() -> str | None:
    return _current_device_id.get()


def clear_device_id() -> None:
    _current_device_id.set(None)


# ==================== 日志模式设置 ====================
def set_log_mode(mode: str) -> None:
    """设置日志模式: simple=简洁, detail=详细, debug=调试"""
    global _log_mode
    _log_mode = mode


def set_log_file(log_path: str) -> None:
    """设置日志文件路径"""
    global _log_file_path
    _log_file_path = log_path
    _current_trace_id.set(None)


def set_console_output(enabled: bool) -> None:
    """
    动态开关控制台输出
    
    Args:
        enabled: True=开启控制台输出, False=关闭控制台输出
    """
    global _enable_console, _console_handler
    
    _enable_console = enabled
    root_logger = logging.getLogger()
    
    if enabled:
        if _console_handler is None:
            _console_handler = logging.StreamHandler(sys.stdout)
            _console_handler.setLevel(logging.DEBUG if is_debug_mode() else logging.INFO)
            _console_handler.setFormatter(ConsoleFormatter())
            root_logger.addHandler(_console_handler)
        else:
            _console_handler.setLevel(logging.DEBUG if is_debug_mode() else logging.INFO)
    else:
        if _console_handler:
            _console_handler.setLevel(logging.CRITICAL + 1)


# ==================== 格式器 ====================
class FileFormatter(logging.Formatter):
    """
    文件日志格式器
    
    简洁模式: [时间][级别] 消息
    详细模式: [时间][级别] [文件:行号] [traceId] 消息
    调试模式: [时间][级别] [PID:xxx] [traceId] [deviceId] [模块] 消息
    """

    def format(self, record: logging.LogRecord) -> str:
        trace_id = get_trace_id()
        device_id = get_device_id()
        msg = record.getMessage()
        time_str = self._format_time(record)
        pid = os.getpid()
        
        # 获取模块信息
        module = os.path.basename(record.pathname) if record.pathname else "?"
        func = record.funcName if record.funcName else ""
        module_info = f"{module}:{record.lineno}" if record.lineno else module
        
        if _log_mode == "debug" or is_debug_mode():
            # 调试模式：最详细
            ctx_parts = [f"PID:{pid}"]
            if trace_id:
                ctx_parts.append(f"trace:{trace_id}")
            if device_id:
                ctx_parts.append(f"device:{device_id}")
            ctx_parts.append(f"{module_info}")
            return f"[{time_str}][{record.levelname}] [{'|'.join(ctx_parts)}] {msg}"
        elif _log_mode == "detail":
            # 详细模式
            if trace_id:
                return f"[{time_str}][{record.levelname}] [{module_info}] [trace:{trace_id}] {msg}"
            return f"[{time_str}][{record.levelname}] [{module_info}] {msg}"
        else:
            # 简洁模式
            if trace_id:
                return f"[{time_str}][{record.levelname}] {msg} [trace:{trace_id}]"
            return f"[{time_str}][{record.levelname}] {msg}"

    def _format_time(self, record: logging.LogRecord) -> str:
        """格式化时间：精确到毫秒"""
        ct = datetime.fromtimestamp(record.created)
        return ct.strftime("%m-%d %H:%M:%S") + f".{int(record.msecs):03d}"


class ConsoleFormatter(logging.Formatter):
    """
    控制台美观格式
    - ERROR: 红色 + ❌
    - WARNING: 黄色 + ⚠️
    - INFO: 青色 + ➤
    - DEBUG: 灰色 + 🔍
    """

    _C = {
        'red': '\033[91m',
        'yellow': '\033[93m',
        'cyan': '\033[96m',
        'gray': '\033[90m',
        'bold': '\033[1m',
        'reset': '\033[0m',
        'magenta': '\033[95m',  # 调试模式专用
    }

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        
        # 过滤高频轮询请求
        if record.levelno == logging.INFO:
            if any(m in msg for m in ("heartbeat", "OPTIONS", "GET /", "POST /")):
                if any(ip in msg for ip in ("127.0.0.1", "::1", "localhost")):
                    return ""
        
        # 美观图标
        icons = {'ERROR': '❌', 'WARNING': '⚠️', 'INFO': '➤', 'DEBUG': '🔍', 'CRITICAL': '💥'}
        icon = icons.get(record.levelname, '○')
        
        # 根据级别设置颜色
        if record.levelname == 'CRITICAL':
            color = f"{self._C['red']}{self._C['bold']}"
            end = self._C['reset']
        elif record.levelname == 'ERROR':
            color = self._C['red']
            end = self._C['reset']
        elif record.levelname == 'WARNING':
            color = self._C['yellow']
            end = self._C['reset']
        elif record.levelname == 'INFO':
            color = self._C['cyan']
            end = self._C['reset']
        elif record.levelname == 'DEBUG':
            color = self._C['magenta']
            end = self._C['reset']
        else:
            color = self._C['gray']
            end = self._C['reset']
        
        # 时间格式
        ct = datetime.fromtimestamp(record.created)
        time_str = ct.strftime("%m-%d %H:%M:%S")
        
        # 详细/调试模式
        if _log_mode == "debug" or is_debug_mode():
            pid = os.getpid()
            trace_id = get_trace_id() or ""
            filename = os.path.basename(record.pathname) if record.pathname else "?"
            lineno = record.lineno if record.lineno else "?"
            extra = f" [P{pid}]"
            if trace_id:
                extra += f" [T:{trace_id}]"
            extra += f" [{filename}:{lineno}]"
            return f"{color}{time_str}{end} {icon}{extra} {msg}"
        elif _log_mode == "detail":
            filename = os.path.basename(record.pathname) if record.pathname else "?"
            lineno = record.lineno if record.lineno else "?"
            return f"{color}{time_str}{end} {icon} [{filename}:{lineno}] {msg}"
        
        return f"{color}{time_str}{end} {icon} {msg}"


# ==================== 日志过滤器 ====================
class RequestLogFilter(logging.Filter):
    """过滤高频轮询请求日志"""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "/api/admin/device/" in msg and "request_start" in msg:
            return False
        if record.levelno == logging.INFO:
            if any(ip in msg for ip in ("127.0.0.1", "::1")):
                if any(m in msg for m in ("OPTIONS", "GET /", "POST /")):
                    return False
        return True


# ==================== 调试模式专用过滤器 ====================
class DebugStateFilter(logging.Filter):
    """调试模式下定期打印全局状态"""

    def __init__(self, interval: float = 10.0):
        super().__init__()
        self.interval = interval
        self._last_print = 0.0

    def filter(self, record: logging.LogRecord) -> bool:
        if not is_debug_mode():
            return True
        
        import time
        now = time.time()
        if now - self._last_print >= self.interval:
            self._last_print = now
            # 触发全局状态打印（通过一个特殊的 DEBUG 日志）
            logger = logging.getLogger("vb")
            state_parts = []
            for name, getter in _global_state_getters.items():
                try:
                    value = getter()
                    state_parts.append(f"{name}={value}")
                except Exception:
                    state_parts.append(f"{name}=<error>")
            if state_parts:
                logger.debug(f"[全局状态] {' | '.join(state_parts)}")
        return True


# ==================== 日志初始化 ====================
_logging_initialized = False
_initialized_logger: Optional[logging.Logger] = None
_debug_state_filter: Optional[DebugStateFilter] = None


def setup_logging(
    log_dir: Optional[str] = None,
    log_level: str = "INFO",
    mode: str = "detail",
    enable_console: bool = True,
) -> logging.Logger:
    """
    初始化日志系统（文件为主，统一格式）
    """
    global _log_mode, _log_file_path, _enable_console, _logging_initialized, _initialized_logger
    global _debug_state_filter
    
    if _logging_initialized and _initialized_logger is not None:
        return _initialized_logger
    
    _logging_initialized = True
    _log_mode = mode
    _enable_console = enable_console
    
    # 检查调试模式
    debug_mode = is_debug_mode()
    if debug_mode:
        _log_mode = "debug"  # 强制使用调试模式
    
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "vb.log"
    _log_file_path = str(log_file)

    root_logger = logging.getLogger()
    
    # 根据调试模式设置日志级别
    if debug_mode:
        root_logger.setLevel(logging.DEBUG)
    else:
        root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # 禁用 uvicorn 日志
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uv_logger = logging.getLogger(logger_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = False

    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # 文件 handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(RequestLogFilter())
    if debug_mode:
        file_handler.addFilter(DebugStateFilter(10.0))
    file_handler.setFormatter(FileFormatter())
    root_logger.addHandler(file_handler)

    # 控制台 handler
    global _console_handler
    if enable_console:
        _console_handler = logging.StreamHandler(sys.stdout)
        _console_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)
        _console_handler.setFormatter(ConsoleFormatter())
        root_logger.addHandler(_console_handler)

    logger = logging.getLogger("vb")
    _initialized_logger = logger
    
    # 启动信息
    if enable_console:
        mode_display = "debug" if debug_mode else mode
        sys.stdout.write(f"[日志] 模式={mode_display} | 文件={log_file}\n")
        sys.stdout.flush()
    logger.info(f"Voice Bridge 启动 | 模式={'debug' if debug_mode else mode}")
    
    if debug_mode:
        logger.debug("[调试] 调试模式已开启")

    return logger


# ==================== 便捷日志获取 ====================
_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器"""
    if name.startswith("vb"):
        return logging.getLogger(name)
    return logging.getLogger(f"vb.{name}")


def get_log_file_path() -> str:
    """返回日志文件路径"""
    global _log_file_path
    if _log_file_path:
        return _log_file_path
    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    return os.path.join(log_dir, "vb.log")


def get_log_file_info() -> dict[str, str | int | bool]:
    """获取日志文件信息"""
    log_path = get_log_file_path()
    if not os.path.exists(log_path):
        return {"exists": False, "path": log_path, "size": 0}
    
    stat = os.stat(log_path)
    return {
        "exists": True,
        "path": log_path,
        "size": stat.st_size,
        "size_str": _format_size(stat.st_size),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    }


def _format_size(size: int) -> str:
    """格式化文件大小"""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f} KB"
    else:
        return f"{size/1024/1024:.1f} MB"


def parse_recent_logs(lines: int = 100, level: str | None = None) -> list[dict[str, str]]:
    """解析最近日志"""
    log_path = get_log_file_path()
    if not os.path.exists(log_path):
        return []

    result: list[dict[str, str]] = []
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            log_lines = f.readlines()
            for line in log_lines[-lines:]:
                line = line.strip()
                if not line:
                    continue
                
                if level:
                    if level.upper() not in line:
                        continue
                
                parts = line.split(']', 2)
                if len(parts) >= 2:
                    time_str = parts[0][1:]
                    level_str = parts[1][1:]
                    msg = parts[2] if len(parts) > 2 else ""
                    
                    result.append({
                        "time": time_str,
                        "level": level_str,
                        "message": msg.strip()
                    })
    except Exception:
        pass

    return list(reversed(result))


def get_recent_logs_tail(lines: int = 50) -> str:
    """获取最近日志的原始文本"""
    log_path = get_log_file_path()
    if not os.path.exists(log_path):
        return ""
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            tail_lines = all_lines[-lines:]
            return ''.join(tail_lines)
    except Exception:
        return ""


# ==================== asyncio 异常处理 ====================
def _suppress_asyncio_warnings() -> None:
    """抑制 asyncio 相关已知问题的异常输出"""
    import asyncio
    import socket
    
    _original_excepthook = sys.excepthook
    
    def _custom_excepthook(exc_type, exc_value, exc_traceback):
        # 抑制 Windows asyncio Proactor 连接丢失异常
        if exc_type is RuntimeError and exc_value and "_ProactorBasePipeTransport._call_connection_lost" in str(exc_value):
            return
        if exc_type is AttributeError and exc_value and "_call_connection_lost" in str(exc_value):
            return
        # 抑制 ConnectionResetError（远程主机强迫关闭连接）
        if exc_type is ConnectionResetError:
            return
        if exc_type is OSError and exc_value and "10054" in str(exc_value):
            return  # WinError 10054 = ConnectionResetError
        _original_excepthook(exc_type, exc_value, exc_traceback)
    
    sys.excepthook = _custom_excepthook


# ==================== 便捷异常记录函数 ====================
def log_exception(logger: logging.Logger, exc: Exception, context: str = "") -> str:
    """
    记录异常信息（包含完整堆栈）
    """
    trace = ''.join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
    full_msg = f"[异常] {context}: {type(exc).__name__}: {exc}\n{trace}" if context else f"[异常] {type(exc).__name__}: {exc}\n{trace}"
    logger.error(full_msg)
    return full_msg


def log_async_exception(logger: logging.Logger, exc: Exception, context: str = "") -> str:
    """异步函数中记录异常"""
    return log_exception(logger, exc, context)


# ==================== 调试专用：获取调用栈 ====================
def get_call_stack(depth: int = 5) -> str:
    """获取调用栈（用于调试）"""
    stack = tb_module.extract_stack()
    if len(stack) > depth:
        stack = stack[-depth:]
    return '\n'.join(tb_module.format_list(stack))


# ==================== 调试专用：关键函数装饰器 ====================
import functools
import time as time_module


def debug_decorator(func):
    """自动打印函数调用栈和参数的装饰器（调试模式专用）"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not is_debug_mode():
            return func(*args, **kwargs)
        
        logger = logging.getLogger("vb")
        stack = get_call_stack(4)
        logger.debug(f"[调用] {func.__module__}.{func.__qualname__}() 被调用\n{stack}")
        
        start_time = time_module.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time_module.time() - start_time
            logger.debug(f"[返回] {func.__qualname__}() 耗时 {elapsed:.3f}s")
            return result
        except Exception as e:
            elapsed = time_module.time() - start_time
            logger.debug(f"[异常] {func.__qualname__}() 耗时 {elapsed:.3f}s: {e}")
            raise
    
    return wrapper


def debug_async_decorator(func):
    """异步版本的调试装饰器"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if not is_debug_mode():
            return await func(*args, **kwargs)
        
        logger = logging.getLogger("vb")
        stack = get_call_stack(4)
        logger.debug(f"[调用] {func.__module__}.{func.__qualname__}() 被调用\n{stack}")
        
        start_time = time_module.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time_module.time() - start_time
            logger.debug(f"[返回] {func.__qualname__}() 耗时 {elapsed:.3f}s")
            return result
        except Exception as e:
            elapsed = time_module.time() - start_time
            logger.debug(f"[异常] {func.__qualname__}() 耗时 {elapsed:.3f}s: {e}")
            raise
    
    return wrapper


# ==================== 前端日志处理 ====================
_frontend_log_callbacks: list[callable] = []


def register_frontend_log_handler(callback: callable) -> None:
    """注册前端日志处理器"""
    _frontend_log_callbacks.append(callback)


def handle_frontend_log(level: str, message: str, trace_id: str = "", device_id: str = "", extra: dict = None) -> None:
    """处理前端上报的日志"""
    logger = logging.getLogger("vb")
    
    # 设置上下文
    if trace_id:
        set_trace_id(trace_id)
    if device_id:
        set_device_id(device_id)
    
    log_msg = f"[前端] {message}"
    
    level_map = {
        "DEBUG": (logger.debug, logging.DEBUG),
        "INFO": (logger.info, logging.INFO),
        "WARN": (logger.warning, logging.WARNING),
        "WARNING": (logger.warning, logging.WARNING),
        "ERROR": (logger.error, logging.ERROR),
        "CRITICAL": (logger.critical, logging.CRITICAL),
    }
    
    handler, levelno = level_map.get(level.upper(), (logger.info, logging.INFO))
    
    # 错误日志自动带调用栈
    if levelno >= logging.ERROR:
        stack = tb_module.format_exc()
        if stack and stack != "NoneType: None\n":
            log_msg += f"\n[前端调用栈]\n{stack}"
    
    handler(log_msg)
    
    # 清理上下文
    if trace_id:
        clear_trace_id()
    if device_id:
        clear_device_id()
