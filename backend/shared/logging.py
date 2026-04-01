# -*- coding: utf-8 -*-
"""
Voice Bridge 统一日志工具
- 基于 Python logging
- 支持 traceId 上下文（WebSocket 连接链路追踪）
- 文件日志写入 backend/logs/vb.log
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

# ==================== traceId 上下文 ====================
# WebSocket 连接级别的链路追踪 ID
_current_trace_id: ContextVar[Optional[str]] = ContextVar("current_trace_id", default=None)


def generate_trace_id() -> str:
    """生成一个新的 traceId（8位短码，便于日志阅读）"""
    return uuid.uuid4().hex[:8]


def set_trace_id(trace_id: str) -> None:
    """设置当前上下文的 traceId"""
    _current_trace_id.set(trace_id)


def get_trace_id() -> Optional[str]:
    """获取当前上下文的 traceId"""
    return _current_trace_id.get()


def clear_trace_id() -> None:
    """清除当前上下文的 traceId（连接结束时调用）"""
    _current_trace_id.set(None)


# ==================== 日志格式器 ====================
class VBFormatter(logging.Formatter):
    """
    统一日志格式:
    [时间][级别][模块] 消息

    如果上下文中存在 traceId，会追加 [trace=xxxx]
    """

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        trace_id = get_trace_id()
        if trace_id:
            msg = f"{msg} [trace={trace_id}]"
        return msg


class QuietConsoleFormatter(logging.Formatter):
    """
    控制台简洁格式（过滤 FastAPI 轮询日志）
    [时间] 消息
    """

    def __init__(self):
        # 不使用父类的 fmt，因为 format() 方法完全自己实现
        super().__init__(fmt="")

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        # 过滤 FastAPI 的 HTTP access log
        if record.levelno == logging.INFO:
            if "127.0.0.1" in msg or "::1" in msg:
                # 过滤掉 OPTIONS/GET/POST 等轮询请求
                return ""
        return f"{self.formatTime(record)} | {msg}"


# ==================== 日志初始化 ====================
def setup_logging(log_dir: Optional[str] = None, log_level: str = "INFO") -> logging.Logger:
    """
    初始化 Voice Bridge 日志系统

    - 控制台输出（简洁格式，过滤轮询）
    - 文件输出到 backend/logs/vb.log（完整格式，含 traceId）

    Args:
        log_dir: 日志目录，默认取 backend/logs/
        log_level: 日志级别，默认 INFO

    Returns:
        vb Logger 实例
    """
    if log_dir is None:
        # 默认放在 backend/logs/
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")

    # 确保日志目录存在
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    log_file = log_path / "vb.log"

    # 根日志器配置
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 移除已有的 handler（防止重复）
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # --- 控制台 handler（简洁格式） ---
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(QuietConsoleFormatter())
    console.addFilter(_QuietFilter())  # type: ignore
    root_logger.addHandler(console)

    # --- 文件 handler（完整格式，含 traceId） ---
    file_handler = logging.FileHandler(
        log_file,
        encoding="utf-8",
        mode="a",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        VBFormatter("[%(asctime)s][%(levelname)s][%(name)s] %(message)s", datefmt="%m-%d %H:%M:%S")
    )
    root_logger.addHandler(file_handler)

    # vb 日志器
    logger = logging.getLogger("vb")
    logger.info(f"日志系统初始化完成 | 文件: {log_file} | 级别: {log_level}")

    return logger


class _QuietFilter(logging.Filter):
    """过滤 FastAPI 的 HTTP 轮询日志"""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # 过滤: OPTIONS/GET/POST + 127.0.0.1 或 ::1
        if record.levelno == logging.INFO:
            if ("127.0.0.1" in msg or "::1" in msg) and any(
                m in msg for m in ("OPTIONS", "GET /", "POST /")
            ):
                return False
        return True


# ==================== 便捷日志获取 ====================
def get_logger(name: str) -> logging.Logger:
    """
    获取命名日志器，等价于 logging.getLogger(f"vb.{name}")
    推荐在每个模块顶部使用:
        from shared.logging import get_logger
        logger = get_logger("microphone")
    """
    return logging.getLogger(f"vb.{name}" if not name.startswith("vb") else name)


# ==================== 日志路径常量 ====================
def get_log_file_path() -> str:
    """返回日志文件绝对路径（供 /api/logs 端点使用）"""
    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    return os.path.join(log_dir, "vb.log")
