# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - 虚拟麦克风 API 路由
"""

import logging
from fastapi import APIRouter

from devices.virtual_mic import vmic_manager

logger = logging.getLogger("vb.vmic.api")

router = APIRouter(prefix="/api/vmic", tags=["virtual_mic"])


@router.get("/status")
async def get_vmic_status():
    """获取虚拟麦克风状态"""
    return vmic_manager.get_status()


@router.post("/start")
async def start_vmic():
    """启动虚拟麦克风"""
    result = vmic_manager.start()
    logger.info(f"Virtual mic start: {result}")
    return result


@router.post("/stop")
async def stop_vmic():
    """停止虚拟麦克风"""
    result = vmic_manager.stop()
    logger.info(f"Virtual mic stop: {result}")
    return result


@router.get("/devices")
async def list_audio_devices():
    """列出所有音频输出设备"""
    import sounddevice as sd
    try:
        devices = sd.query_devices()
        if isinstance(devices, dict):
            devices = [devices]
        # 筛选有输出通道的设备
        output_devices = [
            {'index': d['index'], 'name': d['name'], 'channels': d.get('max_output_channels', d.get('output_channels', 0))}
            for d in devices
            if d.get('max_output_channels', d.get('output_channels', 0)) > 0
        ]
        return {'devices': output_devices}
    except Exception as e:
        return {'error': str(e), 'devices': []}
