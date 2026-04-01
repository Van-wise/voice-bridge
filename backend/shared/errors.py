# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - 错误定义
Typed Error Hierarchy
"""

from typing import Any


class AppError(Exception):
    """基础错误类"""

    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class NotFoundError(AppError):
    """资源不存在"""

    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            message=f"{resource} not found: {resource_id}",
            code="NOT_FOUND",
            status_code=404,
            details={"resource": resource, "id": resource_id},
        )


class ValidationError(AppError):
    """输入验证失败"""

    def __init__(self, message: str, field: str | None = None) -> None:
        details = {"field": field} if field else {}
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=422,
            details=details,
        )


class DeviceOfflineError(AppError):
    """设备不在线"""

    def __init__(self, device_id: str) -> None:
        super().__init__(
            message=f"Device is offline: {device_id}",
            code="DEVICE_OFFLINE",
            status_code=503,
            details={"device_id": device_id},
        )


class ContentTooLargeError(AppError):
    """内容过大"""

    def __init__(self, size: int, max_size: int) -> None:
        super().__init__(
            message=f"Content size {size} exceeds maximum {max_size}",
            code="CONTENT_TOO_LARGE",
            status_code=413,
            details={"size": size, "max_size": max_size},
        )


class UnauthorizedError(AppError):
    """未授权"""

    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=401,
        )
