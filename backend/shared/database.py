# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - 数据库层
SQLite（基于开源项目最佳实践优化）
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
import logging

from .config import get_settings

logger = logging.getLogger("vb.database")


class Database:
    """SQLite 数据库管理器（增强版）"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库"""
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建表
        self._create_tables()
        # 执行迁移
        self._migrate()
        logger.info(f"Database initialized at: {self.db_path}")

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _create_tables(self) -> None:
        """创建所有表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 设备表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    device_type TEXT NOT NULL CHECK(device_type IN ('desktop', 'mobile', 'web')),
                    ip_address TEXT,
                    last_seen REAL NOT NULL,
                    created_at REAL NOT NULL,
                    is_online INTEGER DEFAULT 0,
                    group_id TEXT
                )
            """)

            # 剪贴板历史表（增强版）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clipboard_items (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    content_type TEXT NOT NULL CHECK(content_type IN ('text', 'image', 'file')),
                    device_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    
                    -- 增强字段
                    content_category TEXT DEFAULT 'plain',
                    hash TEXT NOT NULL,
                    preview TEXT DEFAULT '',
                    source_app TEXT DEFAULT '',
                    
                    -- 状态
                    is_favorite INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '[]',
                    is_deleted INTEGER DEFAULT 0,
                    
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                )
            """)

            # 索引（优化查询性能）
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clipboard_created
                ON clipboard_items(created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clipboard_device
                ON clipboard_items(device_id, created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clipboard_hash
                ON clipboard_items(hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_clipboard_category
                ON clipboard_items(content_category)
            """)

            # 设置表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # 设置引导设备表（setup专用，支持设备指纹）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS setup_devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT DEFAULT '',
                    device_fingerprint TEXT DEFAULT '',
                    last_ip TEXT DEFAULT '',
                    device_type TEXT DEFAULT 'mobile',
                    create_time REAL NOT NULL,
                    update_time REAL NOT NULL,
                    is_configured INTEGER DEFAULT 0
                )
            """)
            
            # 设备指纹索引（支持模糊匹配）
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_setup_fp 
                ON setup_devices(device_fingerprint)
            """)

            # 标签表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    color TEXT DEFAULT '#3b82f6',
                    created_at REAL NOT NULL
                )
            """)

            logger.debug("All tables created")

    def _migrate(self) -> None:
        """数据库迁移"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 检查是否需要迁移
            cursor.execute("PRAGMA table_info(clipboard_items)")
            columns = {row['name'] for row in cursor.fetchall()}
            
            # 如果缺少新字段，执行迁移
            new_fields = ['hash', 'preview', 'source_app', 'content_category']
            for field in new_fields:
                if field not in columns:
                    try:
                        if field == 'hash':
                            cursor.execute("ALTER TABLE clipboard_items ADD COLUMN hash TEXT NOT NULL DEFAULT ''")
                        elif field == 'preview':
                            cursor.execute("ALTER TABLE clipboard_items ADD COLUMN preview TEXT DEFAULT ''")
                        elif field == 'source_app':
                            cursor.execute("ALTER TABLE clipboard_items ADD COLUMN source_app TEXT DEFAULT ''")
                        elif field == 'content_category':
                            cursor.execute("ALTER TABLE clipboard_items ADD COLUMN content_category TEXT DEFAULT 'plain'")
                        logger.info(f"Migrated: added column {field}")
                    except Exception as e:
                        logger.warning(f"Migration warning for {field}: {e}")
            
            logger.info("Database migration completed")


# 全局数据库实例
_db: Database | None = None


def get_database() -> Database:
    """获取数据库实例（单例）"""
    global _db
    if _db is None:
        settings = get_settings()
        _db = Database(settings.database_path)
    return _db
