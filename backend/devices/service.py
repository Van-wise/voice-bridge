# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - Device 服务层
"""

import time
import uuid
from datetime import datetime
from typing import Sequence

from shared.database import get_database
from shared.errors import NotFoundError
from devices.models import Device, DeviceType, RegisterDevice


class DeviceService:
    """设备服务"""

    def __init__(self) -> None:
        self.db = get_database()

    def register_device(self, data: RegisterDevice) -> Device:
        """注册新设备或更新现有设备"""
        device_id = str(uuid.uuid4())
        now = time.time()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO devices
                (id, name, device_type, ip_address, last_seen, created_at, is_online)
                VALUES (
                    COALESCE((SELECT id FROM devices WHERE name = ? AND device_type = ?), ?),
                    ?, ?, ?, ?, ?, 1
                )
                """,
                (
                    data.name,
                    data.device_type.value,
                    device_id,
                    data.name,
                    data.device_type.value,
                    data.ip_address,
                    now,
                    now,
                ),
            )

            # 获取设备的实际 ID
            cursor.execute(
                "SELECT * FROM devices WHERE name = ? AND device_type = ?",
                (data.name, data.device_type.value),
            )
            row = cursor.fetchone()

        return self._row_to_device(row)

    def get_device(self, device_id: str) -> Device:
        """获取设备"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            row = cursor.fetchone()

        if not row:
            raise NotFoundError("Device", device_id)

        return self._row_to_device(row)

    def get_all_devices(self) -> Sequence[Device]:
        """获取所有设备"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM devices ORDER BY last_seen DESC")
            rows = cursor.fetchall()

        return [self._row_to_device(row) for row in rows]

    def get_online_devices(self) -> Sequence[Device]:
        """获取在线设备"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM devices WHERE is_online = 1 ORDER BY last_seen DESC"
            )
            rows = cursor.fetchall()

        return [self._row_to_device(row) for row in rows]

    def update_heartbeat(self, device_id: str) -> Device:
        """更新设备心跳"""
        now = time.time()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE devices SET last_seen = ?, is_online = 1 WHERE id = ?",
                (now, device_id),
            )

        return self.get_device(device_id)

    def set_offline(self, device_id: str) -> None:
        """设置设备离线"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE devices SET is_online = 0 WHERE id = ?",
                (device_id,),
            )

    def _row_to_device(self, row) -> Device:
        """将数据库行转换为 Device"""
        return Device(
            id=row["id"],
            name=row["name"],
            device_type=DeviceType(row["device_type"]),
            ip_address=row["ip_address"],
            last_seen=datetime.fromtimestamp(row["last_seen"]),
            created_at=datetime.fromtimestamp(row["created_at"]),
            is_online=bool(row["is_online"]),
        )


# 单例
_service: DeviceService | None = None


def get_device_service() -> DeviceService:
    """获取服务实例"""
    global _service
    if _service is None:
        _service = DeviceService()
    return _service
