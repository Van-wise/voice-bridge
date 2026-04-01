# -*- coding: utf-8 -*-
"""
Voice Bridge 统一日志工具
=========================
- 支持 traceId 上下文追踪
- 多级日志模式：简洁模式（默认）/ 详细模式
- 文件日志为主，控制台美化输出
- 完整的异常处理记录
- Windows ANSI 颜色支持
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from datetime import datetime
import traceback as tb_module
from typing import Optional

# Windows ANSI 颜色支持
_WINDOWS_ANSI = False  # 默认值
try:
    import colorama
    colorama.init(autoreset=True, strip=False)
    _WINDOWS_ANSI = True
except ImportError:
    pass  # Linux/Mac 直接支持 ANSI

# ==================== 全局配置 ====================
_log_mode: str = "simple"  # "simple" | "detail"
_log_file_path: str = ""    # 记录日志文件路径供外部访问
_enable_console: bool = False  # 控制台输出开关
_console_handler: Optional["logging.StreamHandler"] = None  # 控制台 handler 引用

# ==================== traceId 上下文 ====================
_current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)


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


# ==================== 日志模式设置 ====================
def set_log_mode(mode: str) -> None:
    """设置日志模式: simple=简洁, detail=详细"""
    global _log_mode
    _log_mode = mode


def set_log_file(log_path: str) -> None:
    """设置日志文件路径"""
    global _log_file_path
    _log_file_path = log_path
    _current_trace_id.set(None)  # type: ignore[call-arg]


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
        # 开启控制台输出
        if _console_handler is None:
            _console_handler = logging.StreamHandler(sys.stdout)
            _console_handler.setLevel(logging.INFO)
            _console_handler.setFormatter(ConsoleFormatter())
            root_logger.addHandler(_console_handler)
        else:
            _console_handler.setLevel(logging.INFO)
    else:
        # 关闭控制台输出（移除 handler）
        if _console_handler:
            _console_handler.setLevel(logging.CRITICAL + 1)  # 设置为最高级别，等于禁用


# ==================== 格式器 ====================
class FileFormatter(logging.Formatter):
    """
    文件日志格式器
    
    简洁模式: [时间][级别] 消息
    详细模式: [时间][级别] [文件:行号] [traceId] 消息
    """

    def format(self, record: logging.LogRecord) -> str:
        trace_id = get_trace_id()
        msg = record.getMessage()
        time_str = self._format_time(record)
        
        if _log_mode == "detail":
            # 详细模式：包含文件名、行号、traceId
            filename = os.path.basename(record.pathname) if record.pathname else "?"
            lineno = record.lineno if record.lineno else "?"
            if trace_id:
                return f"[{time_str}][{record.levelname}] [{filename}:{lineno}] [trace:{trace_id}] {msg}"
            return f"[{time_str}][{record.levelname}] [{filename}:{lineno}] {msg}"
        else:
            # 简洁模式
            if trace_id:
                return f"[{time_str}][{record.levelname}] {msg} [trace:{trace_id}]"
            return f"[{time_str}][{record.levelname}] {msg}"

    def _format_time(self, record: logging.LogRecord) -> str:
        """格式化时间：MM-DD HH:MM:SS.mmm"""
        ct = datetime.fromtimestamp(record.created)
        return ct.strftime("%m-%d %H:%M:%S") + f".{int(record.msecs):03d}"


class ConsoleFormatter(logging.Formatter):
    """
    控制台美观格式
    - ERROR: 红色 + ❌
    - WARNING: 黄色 + ⚠️
    - INFO: 青色 + ➤
    - 详细模式显示文件名和行号
    - 过滤高频轮询请求
    """

    # ANSI 颜色代码
    _C = {
        'red': '\033[91m',
        'yellow': '\033[93m',
        'cyan': '\033[96m',
        'gray': '\033[90m',
        'bold': '\033[1m',
        'reset': '\033[0m',
    }

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        
        # 过滤高频轮询请求（本地心跳/轮询）
        if record.levelno == logging.INFO:
            if any(m in msg for m in ("heartbeat", "OPTIONS", "GET /", "POST /")):
                if any(ip in msg for ip in ("127.0.0.1", "::1", "localhost")):
                    return ""
        
        # 美观图标
        icons = {'ERROR': '❌', 'WARNING': '⚠️', 'INFO': '➤', 'DEBUG': '🔍'}
        icon = icons.get(record.levelname, '○')
        
        # 根据级别设置颜色
        if record.levelname == 'ERROR':
            color = f"{self._C['red']}{self._C['bold']}"
            end = self._C['reset']
        elif record.levelname == 'WARNING':
            color = self._C['yellow']
            end = self._C['reset']
        elif record.levelname == 'INFO':
            color = self._C['cyan']
            end = self._C['reset']
        else:
            color = self._C['gray']
            end = self._C['reset']
        
        # 时间格式
        ct = datetime.fromtimestamp(record.created)
        time_str = ct.strftime("%m-%d %H:%M:%S")
        
        # 详细模式：添加文件名和行号
        if _log_mode == "detail":
            filename = os.path.basename(record.pathname) if record.pathname else "?"
            lineno = record.lineno if record.lineno else "?"
            location = f"[{filename}:{lineno}]"
            return f"{color}{time_str}{end} {icon} {location} {msg}"
        
        return f"{color}{time_str}{end} {icon} {msg}"

    def _format_time(self, record: logging.LogRecord) -> str:
        ct = datetime.fromtimestamp(record.created)
        return ct.strftime("%H:%M:%S")


# ==================== 日志过滤器 ====================
class RequestLogFilter(logging.Filter):
    """过滤高频轮询请求日志"""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # 过滤心跳
        if "/api/admin/device/" in msg and "request_start" in msg:
            return False
        # 过滤高频轮询
        if record.levelno == logging.INFO:
            if any(ip in msg for ip in ("127.0.0.1", "::1")):
                if any(m in msg for m in ("OPTIONS", "GET /", "POST /")):
                    return False
        return True


# ==================== 日志初始化 ====================
_logging_initialized = False  # 防止重复初始化
_initialized_logger: Optional[logging.Logger] = None  # 缓存 logger


def setup_logging(
    log_dir: Optional[str] = None,
    log_level: str = "INFO",
    mode: str = "simple",
    enable_console: bool = True,
) -> logging.Logger:
    """
    初始化日志系统（文件为主，统一格式）
    仅首次调用生效，后续调用返回已有的 logger
    """
    global _log_mode, _log_file_path, _enable_console, _logging_initialized, _initialized_logger
    
    # 防止重复初始化
    if _logging_initialized and _initialized_logger is not None:
        return _initialized_logger
    
    _logging_initialized = True
    _log_mode = mode
    _enable_console = enable_console

    # 确定日志目录
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "vb.log"
    _log_file_path = str(log_file)

    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # 禁用 uvicorn 默认日志处理器
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uv_logger = logging.getLogger(logger_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = False

    # 移除已有 handler
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # --- 文件 handler（完整记录）---
    file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
    file_handler.addFilter(RequestLogFilter())  # 过滤高频轮询
    file_handler.setFormatter(FileFormatter())
    root_logger.addHandler(file_handler)

    # --- 控制台 handler（美观输出，关键信息和操作反馈）---
    global _console_handler
    if enable_console:
        _console_handler = logging.StreamHandler(sys.stdout)
        _console_handler.setLevel(logging.INFO)  # INFO 及以上输出到控制台
        _console_handler.setFormatter(ConsoleFormatter())
        root_logger.addHandler(_console_handler)

    logger = logging.getLogger("vb")
    
    # 缓存 logger
    _initialized_logger = logger
    
    # 启动信息（紧凑格式，直接写到 stdout）
    if enable_console:
        sys.stdout.write(f"[日志] 模式={mode} | 文件={log_file}\n")
        sys.stdout.flush()
    logger.info(f"Voice Bridge 启动 | 模式={mode}")

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
        return {"exists": False, "path": log_path, "size": 0}  # type: ignore[return-value]
    
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
            # 取最后 N 行
            for line in log_lines[-lines:]:
                line = line.strip()
                if not line:
                    continue
                
                # 按级别过滤
                if level:
                    if level.upper() not in line:
                        continue
                
                # 解析日志行
                parts = line.split(']', 2)
                if len(parts) >= 2:
                    time_str = parts[0][1:]  # 去掉 [
                    level_str = parts[1][1:]  # 去掉 [
                    msg = parts[2] if len(parts) > 2 else ""
                    
                    result.append({
                        "time": time_str,
                        "level": level_str,
                        "message": msg.strip()
                    })
    except Exception:
        pass

    return list(reversed(result))  # 最新的在前面


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


# ==================== 便捷异常记录函数 ====================
def log_exception(logger: logging.Logger, exc: Exception, context: str = "") -> str:
    """
    记录异常信息（包含完整堆栈）
    
    Args:
        logger: 日志器
        exc: 异常对象
        context: 上下文描述
    
    Returns:
        格式化的异常描述
    """
    trace = ''.join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
    full_msg = f"[异常] {context}: {type(exc).__name__}: {exc}\n{trace}" if context else f"[异常] {type(exc).__name__}: {exc}\n{trace}"
    logger.error(full_msg)
    return full_msg


def log_async_exception(logger: logging.Logger, exc: Exception, context: str = "") -> str:
    """
    异步函数中记录异常
    
    用法:
        try:
            await some_async_func()
        except Exception as e:
            log_async_exception(logger, e, "调用失败")
    
    Returns:
        格式化的异常描述
    """
    return log_exception(logger, exc, context)
