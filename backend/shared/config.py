# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - 配置管理
使用 Pydantic Settings，环境变量优先
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    """应用配置"""

    # 服务器
    host: str = "0.0.0.0"
    port: int = 7266          # HTTP 端口
    https_port: int = 7267    # HTTPS 端口

    # 数据库
    database_url: str = ""

    # CORS（允许所有来源，开发环境用）
    cors_origins: list[str] = ["*"]

    # WebSocket
    ws_heartbeat_interval: int = 30  # 秒

    # 剪贴板
    max_clipboard_content_size: int = 1024 * 1024  # 1MB
    max_history_items: int = 1000
    history_retention_days: int = 30

    # 文件上传
    upload_folder: str = "uploads"
    max_file_size: int = 50 * 1024 * 1024  # 50MB

    # 日志
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def database_path(self) -> Path:
        """数据库文件路径"""
        if self.database_url:
            return Path(self.database_url)
        return Path(__file__).parent.parent / "voice_bridge.db"


@lru_cache()
def get_settings() -> Settings:
    """获取配置（单例）"""
    return Settings()
