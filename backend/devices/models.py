# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - Device 模型
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DeviceType(str, Enum):
    """设备类型"""
    DESKTOP = "desktop"
    MOBILE = "mobile"
    WEB = "web"


@dataclass
class Device:
    """设备"""
    id: str
    name: str
    device_type: DeviceType
    ip_address: str | None
    last_seen: datetime
    created_at: datetime
    is_online: bool = False


@dataclass
class RegisterDevice:
    """注册设备请求"""
    name: str
    device_type: DeviceType
    ip_address: str | None = None
