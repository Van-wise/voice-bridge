# -*- coding: utf-8 -*-
"""
Voice Bridge HTTP 请求中间件
- 简洁日志输出
- 过滤高频请求
"""
from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from shared.logging import generate_request_id, set_trace_id, clear_trace_id, get_logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    HTTP 请求日志中间件
    默认只记录：慢请求(>500ms)、错误请求、重要操作
    """

    # 慢请求阈值（毫秒）
    SLOW_THRESHOLD_MS = 500

    # 始终过滤的路径（高频轮询，不记录）
    ALWAYS_FILTER_PATHS = {
        "/api/poll",
        "/api/health",
        "/health",
    }
    
    # 心跳请求路径（也过滤）
    HEARTBEAT_PATH = "/api/admin/device/"

    # 需要记录的重要路径前缀
    IMPORTANT_PATH_PREFIXES = [
        "/sync",
        "/clipboard",
        "/audio",
        "/setup",
        "/admin",
        "/ws/",
        "/api/setup",
        "/api/cert",
        "/api/check-https",
    ]

    def __init__(self, app: ASGIApp, verbose: bool = False):
        super().__init__(app)
        self.verbose = verbose
        self.logger = get_logger("http")

    def _should_log(self, path: str, status_code: int, duration_ms: float) -> bool:
        """判断是否应该记录此请求"""
        # 始终过滤高频轮询
        if any(path.startswith(p) for p in self.ALWAYS_FILTER_PATHS):
            return False
        
        # 过滤心跳请求
        if self.HEARTBEAT_PATH in path:
            # 只在 verbose 模式或慢请求时记录心跳
            return self.verbose and duration_ms > self.SLOW_THRESHOLD_MS
        
        # verbose 模式下记录所有请求
        if self.verbose:
            return True
        
        # 记录错误请求
        if status_code >= 400:
            return True
        
        # 记录慢请求
        if duration_ms > self.SLOW_THRESHOLD_MS:
            return True
        
        # 记录重要路径
        if any(path.startswith(p) for p in self.IMPORTANT_PATH_PREFIXES):
            return True
        
        # 其他请求不记录
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # 生成 traceId
        request_id = generate_request_id()
        set_trace_id(request_id)

        start_time = time.perf_counter()
        client_ip = request.client.host if request.client else "-"
        method = request.method

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # 只记录重要请求
            if self._should_log(path, response.status_code, duration_ms):
                status = response.status_code
                duration_str = f"{duration_ms:.0f}ms"
                if duration_ms > 1000:
                    duration_str = f"{duration_ms/1000:.1f}s"

                if status >= 500:
                    self.logger.error(f"{method} {path} {status} {duration_str} {client_ip}")
                elif status >= 400:
                    self.logger.warning(f"{method} {path} {status} {duration_str} {client_ip}")
                else:
                    self.logger.info(f"{method} {path} {status} {duration_str} {client_ip}")

            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self.logger.error(f"{method} {path} ERROR {duration_ms:.0f}ms - {type(e).__name__}: {e}")
            raise

        finally:
            clear_trace_id()
