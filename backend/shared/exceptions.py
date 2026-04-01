# -*- coding: utf-8 -*-
"""
Voice Bridge 异常处理工具
========================
- 重试机制 (@with_retry)
- 安全执行 (@safe_execute)
- 异常转换 (@convert_exception)
- 完整的异常日志记录
"""
from __future__ import annotations

import asyncio
import functools
import time
import traceback as tb_module
from typing import Any, Callable, Type, TypeVar, Optional

from shared.errors import AppError, DatabaseError, DeviceOfflineError

# 类型变量
T = TypeVar("T")

# ==================== 日志器（延迟导入避免循环依赖）====================
_loggers_cache: dict = {}


def _get_logger(module_name: str):
    """获取模块日志器（带缓存）"""
    if module_name not in _loggers_cache:
        from shared.logging import get_logger
        _loggers_cache[module_name] = get_logger(module_name)
    return _loggers_cache[module_name]


# ==================== 重试机制 ====================

class RetryConfig:
    """重试配置"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 0.1,
        max_delay: float = 5.0,
        backoff_factor: float = 2.0,
        exceptions: tuple = (Exception,),
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.exceptions = exceptions


def with_retry(
    max_attempts: int = 3,
    initial_delay: float = 0.1,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
    log_retries: bool = True,
):
    """
    重试装饰器
    
    Args:
        max_attempts: 最大重试次数
        initial_delay: 初始延迟（秒）
        backoff_factor: 退避系数
        exceptions: 需要重试的异常类型
        log_retries: 是否记录重试日志
    
    用法:
        @with_retry(max_attempts=3, exceptions=(ConnectionError,))
        def connect():
            ...
    
    示例:
        @with_retry(max_attempts=5, initial_delay=1.0, backoff_factor=2.0)
        async def fetch_data():
            return await api.get()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            logger = _get_logger(func.__module__)
            delay = initial_delay
            last_exception: Optional[Exception] = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(
                            f"[重试耗尽] {func.__name__} 在 {max_attempts} 次尝试后失败: {type(e).__name__}: {e}"
                        )
                        break
                    
                    if log_retries:
                        logger.warning(
                            f"[重试] {func.__name__} 第 {attempt}/{max_attempts} 次失败: {type(e).__name__}, "
                            f"{delay:.1f}秒后重试..."
                        )
                    
                    await asyncio.sleep(min(delay, 5.0))
                    delay *= backoff_factor
            
            raise last_exception
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            logger = _get_logger(func.__module__)
            delay = initial_delay
            last_exception: Optional[Exception] = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(
                            f"[重试耗尽] {func.__name__} 在 {max_attempts} 次尝试后失败: {type(e).__name__}: {e}"
                        )
                        break
                    
                    if log_retries:
                        logger.warning(
                            f"[重试] {func.__name__} 第 {attempt}/{max_attempts} 次失败: {type(e).__name__}, "
                            f"{delay:.1f}秒后重试..."
                        )
                    
                    time.sleep(min(delay, 5.0))
                    delay *= backoff_factor
            
            raise last_exception
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ==================== 安全执行 ====================

def safe_execute(
    default: Any = None,
    exceptions: tuple = (Exception,),
    log_error: bool = True,
    log_level: str = "error",
):
    """
    安全执行装饰器
    捕获异常并返回默认值，同时记录完整堆栈
    
    Args:
        default: 异常时返回的默认值
        exceptions: 需要捕获的异常类型
        log_error: 是否记录错误日志
        log_level: 日志级别 "error" / "warning" / "info"
    
    用法:
        @safe_execute(default=[], log_error=True)
        def get_items():
            return db.query()
    
    示例:
        @safe_execute(default={}, log_error=True, log_level="warning")
        async def fetch_config():
            return await config_service.get()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T | Any:
            logger = _get_logger(func.__module__)
            
            try:
                return await func(*args, **kwargs)
            except exceptions as e:
                trace = ''.join(tb_module.format_exception(type(e), e, e.__traceback__))
                log_msg = f"[safe_execute] {func.__name__} 失败: {type(e).__name__}: {e}\n{trace}"
                
                if log_level == "warning":
                    logger.warning(log_msg)
                elif log_level == "info":
                    logger.info(log_msg)
                else:
                    logger.error(log_msg)
                
                return default
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T | Any:
            logger = _get_logger(func.__module__)
            
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                trace = ''.join(tb_module.format_exception(type(e), e, e.__traceback__))
                log_msg = f"[safe_execute] {func.__name__} 失败: {type(e).__name__}: {e}\n{trace}"
                
                if log_level == "warning":
                    logger.warning(log_msg)
                elif log_level == "info":
                    logger.info(log_msg)
                else:
                    logger.error(log_msg)
                
                return default
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ==================== 异常转换 ====================

def convert_exception(
    from_exceptions: tuple = (Exception,),
    to_exception_type: Type[AppError] = AppError,
    message: Optional[str] = None,
    log_conversion: bool = True,
):
    """
    异常转换装饰器
    将一种异常转换为另一种业务异常
    
    Args:
        from_exceptions: 源异常类型
        to_exception_type: 目标异常类型
        message: 自定义错误消息
        log_conversion: 是否记录转换日志
    
    用法:
        @convert_exception((ValueError, TypeError), AppError, "参数错误")
        def process(data):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            logger = _get_logger(func.__module__)
            
            try:
                return await func(*args, **kwargs)
            except from_exceptions as e:
                msg = message or str(e)
                exc_name = type(e).__name__
                
                if log_conversion:
                    logger.warning(f"[异常转换] {exc_name} → {to_exception_type.__name__}: {msg}")
                
                raise to_exception_type(
                    message=msg,
                    code=getattr(to_exception_type, '__name__', 'ERROR').replace("Error", "").upper(),
                )
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            logger = _get_logger(func.__module__)
            
            try:
                return func(*args, **kwargs)
            except from_exceptions as e:
                msg = message or str(e)
                exc_name = type(e).__name__
                
                if log_conversion:
                    logger.warning(f"[异常转换] {exc_name} → {to_exception_type.__name__}: {msg}")
                
                raise to_exception_type(
                    message=msg,
                    code=getattr(to_exception_type, '__name__', 'ERROR').replace("Error", "").upper(),
                )
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ==================== 业务异常辅助函数 ====================

def raise_device_offline(device_id: str) -> None:
    """抛出设备离线异常"""
    raise DeviceOfflineError(device_id)


def raise_database_error(operation: str, reason: str) -> None:
    """抛出数据库错误异常"""
    raise DatabaseError(operation=operation, reason=reason)


def require_online(func: Callable) -> Callable:
    """
    装饰器：要求设备在线
    
    用法:
        @require_online
        async def send_data(device_id: str, ...):
            ...
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        logger = _get_logger(func.__module__)
        device_id = None
        for val in args:
            if isinstance(val, str) and len(val) > 10:
                device_id = val
                break
        
        if device_id and not _check_device_online(device_id):
            logger.warning(f"[设备离线] {func.__name__} 无法执行，设备 {device_id[:8]}... 不在线")
            raise_device_offline(device_id)
        
        return await func(*args, **kwargs)
    
    return wrapper


def _check_device_online(device_id: str) -> bool:
    """检查设备是否在线"""
    try:
        from devices.service import get_device_service
        service = get_device_service()
        device = service.get_device(device_id)
        return device.is_online
    except Exception:
        return False


# ==================== 异常记录便捷函数 ====================

def log_exception(exc: Exception, context: str = "", logger: Optional[Any] = None) -> str:
    """
    记录异常信息，返回格式化字符串
    
    Args:
        exc: 异常对象
        context: 上下文描述
        logger: 可选的日志器，不提供则自动获取
    
    Returns:
        格式化的异常描述字符串
    """
    if logger is None:
        logger = _get_logger("exceptions")
    
    exc_type = type(exc).__name__
    exc_msg = str(exc)
    trace = ''.join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
    
    full_msg = f"[异常] {context}: {exc_type}: {exc_msg}\n{trace}" if context else f"[异常] {exc_type}: {exc_msg}\n{trace}"
    
    logger.error(full_msg)
    return full_msg


def try_getattr(obj: Any, attr_path: str, default: Any = None) -> Any:
    """
    安全获取嵌套属性
    
    用法:
        value = try_getattr(config, "database.host", "localhost")
        # 相当于 config.database.host，失败时返回 "localhost"
    
    Args:
        obj: 目标对象
        attr_path: 属性路径，如 "a.b.c"
        default: 默认值
    """
    try:
        parts = attr_path.split('.')
        result = obj
        for part in parts:
            result = getattr(result, part)
        return result
    except (AttributeError, TypeError):
        return default


def try_get(dictionary: dict, key_path: str, default: Any = None) -> Any:
    """
    安全获取嵌套字典值
    
    用法:
        value = try_get(config, "database.host", "localhost")
    """
    try:
        parts = key_path.split('.')
        result = dictionary
        for part in parts:
            result = result[part]
        return result
    except (KeyError, TypeError):
        return default
