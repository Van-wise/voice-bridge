# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - FFmpeg 音频路由 API
提供 FFmpeg 直接音频输出到虚拟设备的接口
"""

import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .ffmpeg_audio import ffmpeg_router

logger = logging.getLogger("vb.ffmpeg_router")

router = APIRouter(prefix="/api/ffmpeg", tags=["ffmpeg_audio"])


@router.get("/status")
async def get_ffmpeg_status():
    """
    获取 FFmpeg 音频路由状态
    """
    status = ffmpeg_router.get_status()
    return JSONResponse(status)


@router.post("/start")
async def start_ffmpeg_audio():
    """
    启动 FFmpeg 音频路由
    FFmpeg 会直接输出音频到虚拟声卡设备
    """
    result = ffmpeg_router.start()
    if result['success']:
        return JSONResponse(result)
    else:
        raise HTTPException(status_code=500, detail=result)


@router.post("/stop")
async def stop_ffmpeg_audio():
    """
    停止 FFmpeg 音频路由
    """
    result = ffmpeg_router.stop()
    return JSONResponse(result)
