# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - Device 路由
"""

from fastapi import APIRouter, Depends

from devices.models import Device, RegisterDevice
from devices.service import get_device_service, DeviceService

router = APIRouter(prefix="/api/devices", tags=["devices"])


def get_service() -> DeviceService:
    return get_device_service()


@router.post("/register", response_model=Device)
async def register_device(
    data: RegisterDevice,
    service: DeviceService = Depends(get_service),
) -> Device:
    """
    注册设备
    """
    return service.register_device(data)


@router.get("", response_model=list[Device])
async def get_devices(
    online_only: bool = False,
    service: DeviceService = Depends(get_service),
) -> list[Device]:
    """
    获取设备列表
    """
    if online_only:
        return list(service.get_online_devices())
    return list(service.get_all_devices())


@router.get("/{device_id}", response_model=Device)
async def get_device(
    device_id: str,
    service: DeviceService = Depends(get_service),
) -> Device:
    """
    获取单个设备
    """
    return service.get_device(device_id)


@router.post("/{device_id}/heartbeat", response_model=Device)
async def heartbeat(
    device_id: str,
    service: DeviceService = Depends(get_service),
) -> Device:
    """
    设备心跳
    """
    return service.update_heartbeat(device_id)


@router.post("/{device_id}/offline")
async def set_offline(
    device_id: str,
    service: DeviceService = Depends(get_service),
) -> dict:
    """
    设置设备离线
    """
    service.set_offline(device_id)
    return {"status": "ok", "device_id": device_id}
