# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - 错误定义
Typed Error Hierarchy with Structured Error Response
"""
from __future__ import annotations

import traceback
from typing import Any, Optional
from datetime import datetime

# ==================== 错误码常量 ====================

class ErrorCode:
    """错误码定义"""
    # 通用
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    
    # 设备相关
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_ALREADY_EXISTS = "DEVICE_ALREADY_EXISTS"
    
    # 剪贴板相关
    CLIPBOARD_EMPTY = "CLIPBOARD_EMPTY"
    CLIPBOARD_CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
    CLIPBOARD_TYPE_UNSUPPORTED = "UNSUPPORTED_TYPE"
    
    # 音频相关
    AUDIO_DEVICE_NOT_FOUND = "AUDIO_DEVICE_NOT_FOUND"
    AUDIO_STREAM_ERROR = "AUDIO_STREAM_ERROR"
    AUDIO_FORMAT_ERROR = "AUDIO_FORMAT_ERROR"
    
    # 系统相关
    DATABASE_ERROR = "DATABASE_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"


# ==================== 基础异常类 ====================

class AppError(Exception):
    """基础错误类 - 所有业务异常的基类"""

    def __init__(
        self,
        message: str,
        code: str = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        """转换为 API 响应字典"""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }
    
    def to_full_dict(self, trace_id: Optional[str] = None) -> dict[str, Any]:
        """转换为完整错误信息（包含调试信息）"""
        result = self.to_dict()
        if trace_id:
            result["trace_id"] = trace_id
        return result


# ==================== 通用异常 ====================

class NotFoundError(AppError):
    """资源不存在"""

    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            message=f"{resource} not found: {resource_id}",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
            details={"resource": resource, "id": resource_id},
        )


class ValidationError(AppError):
    """输入验证失败"""

    def __init__(self, message: str, field: str | None = None) -> None:
        details = {"field": field} if field else {}
        super().__init__(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
            details=details,
        )


class UnauthorizedError(AppError):
    """未授权"""

    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(
            message=message,
            code=ErrorCode.UNAUTHORIZED,
            status_code=401,
        )


class ForbiddenError(AppError):
    """禁止访问"""

    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(
            message=message,
            code=ErrorCode.FORBIDDEN,
            status_code=403,
        )


# ==================== 设备异常 ====================

class DeviceOfflineError(AppError):
    """设备不在线"""

    def __init__(self, device_id: str) -> None:
        super().__init__(
            message=f"Device is offline: {device_id}",
            code=ErrorCode.DEVICE_OFFLINE,
            status_code=503,
            details={"device_id": device_id},
        )


class DeviceNotFoundError(AppError):
    """设备不存在"""

    def __init__(self, device_id: str) -> None:
        super().__init__(
            message=f"Device not found: {device_id}",
            code=ErrorCode.DEVICE_NOT_FOUND,
            status_code=404,
            details={"device_id": device_id},
        )


# ==================== 剪贴板异常 ====================

class ClipboardEmptyError(AppError):
    """剪贴板为空"""

    def __init__(self) -> None:
        super().__init__(
            message="Clipboard is empty",
            code=ErrorCode.CLIPBOARD_EMPTY,
            status_code=400,
        )


class ContentTooLargeError(AppError):
    """内容过大"""

    def __init__(self, size: int, max_size: int) -> None:
        super().__init__(
            message=f"Content size {size} exceeds maximum {max_size}",
            code=ErrorCode.CLIPBOARD_CONTENT_TOO_LARGE,
            status_code=413,
            details={"size": size, "max_size": max_size},
        )


# ==================== 音频异常 ====================

class AudioDeviceNotFoundError(AppError):
    """音频设备未找到"""

    def __init__(self, device_name: str | None = None) -> None:
        super().__init__(
            message=f"Audio device not found: {device_name or 'default'}",
            code=ErrorCode.AUDIO_DEVICE_NOT_FOUND,
            status_code=503,
            details={"device": device_name},
        )


class AudioStreamError(AppError):
    """音频流错误"""

    def __init__(self, reason: str) -> None:
        super().__init__(
            message=f"Audio stream error: {reason}",
            code=ErrorCode.AUDIO_STREAM_ERROR,
            status_code=500,
            details={"reason": reason},
        )


# ==================== 系统异常 ====================

class DatabaseError(AppError):
    """数据库错误"""

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(
            message=f"Database error during {operation}: {reason}",
            code=ErrorCode.DATABASE_ERROR,
            status_code=500,
            details={"operation": operation, "reason": reason},
        )


# ==================== 全局异常处理 ====================

def get_error_handler():
    """
    获取全局异常处理器配置
    在 main.py 中使用:
    
    from shared.errors import get_error_handler, AppError
    from fastapi import Request
    from fastapi.responses import JSONResponse
    
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, error: AppError):
        return JSONResponse(
            status_code=error.status_code,
            content=error.to_dict(),
        )
    """
    pass


def format_exception(exc: Exception, include_traceback: bool = False) -> dict[str, Any]:
    """
    格式化异常信息
    
    Args:
        exc: 异常对象
        include_traceback: 是否包含堆栈信息
    
    Returns:
        错误信息字典
    """
    error_info = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    
    if include_traceback:
        error_info["traceback"] = traceback.format_exc()
    
    if isinstance(exc, AppError):
        error_info["code"] = exc.code
        error_info["details"] = exc.details
        error_info["timestamp"] = exc.timestamp
    else:
        error_info["code"] = ErrorCode.INTERNAL_ERROR
    
    return error_info
