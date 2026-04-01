# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - 麦克风桥接模块 (重构版 v2)
手机浏览器 → WebSocket → 直接PCM数据 → sounddevice → 虚拟麦克风

架构:
  - 前端使用 Web Audio API 直接获取 PCM Float32 → Int16 → WebSocket
  - 后端直接使用 sounddevice OutputStream 播放，无需 FFmpeg 解码
  - 参考: toMic 的 SoX 方案，但使用 Python 原生实现
"""

import asyncio
import json
import logging
import struct
import numpy as np
from typing import Optional
from websockets.exceptions import ConnectionClosed, ConnectionClosedError
from asyncio.exceptions import IncompleteReadError

from fastapi import WebSocket as FWebSocket
from fastapi import WebSocketDisconnect

logger = logging.getLogger("vb.microphone")

# 音频参数（必须与前端一致）
SAMPLE_RATE = 48000
CHANNELS = 1
BYTES_PER_SAMPLE = 2  # 16bit PCM
CHUNK_SIZE = 4096  # ~85ms @ 48kHz = 4096 samples (前端 createScriptProcessor 缓冲区大小，必须是 2 的幂次方)
VMIC_CHUNK_SIZE = 960  # 20ms @ 48kHz = 960 samples (虚拟麦克风期望的块大小)


class AudioStreamManager:
    """音频流管理器（直接 PCM 方案）"""

    def __init__(self) -> None:
        self.audio_sources: dict[str, FWebSocket] = {}
        self._pcm_count = 0
        self._last_log_time = 0
        # 缓冲器：将前端发送的大块分成小块
        self._buffers: dict[str, bytearray] = {}
        # 每设备帧计数（用于链路统计）
        self._frame_counts: dict[str, int] = {}

    async def start_streaming(self, device_id: str, websocket: FWebSocket) -> None:
        """设备开始音频流"""
        await websocket.accept()
        self.audio_sources[device_id] = websocket

        # 启动 sounddevice 虚拟麦克风
        from devices.virtual_mic import vmic_manager
        status = vmic_manager.start()
        # 无论成功失败，都要通知客户端，让前端清除 vmicTimeout
        await websocket.send_json({
            'type': 'vmic_status',
            **status,
        })
        if status['success']:
            vmic_manager.add_client(device_id)
            self._frame_counts[device_id] = 0
            logger.info(
                f"Audio streaming STARTED | device={device_id} | "
                f"sample_rate={SAMPLE_RATE} | channels={CHANNELS} | "
                f"chunk_size={CHUNK_SIZE} | vmic_chunk={VMIC_CHUNK_SIZE}"
            )
        else:
            logger.warning(f"Virtual mic failed: {status.get('message', '')}")

        # 通知所有客户端
        from devices.websocket import manager
        await manager.broadcast({
            'type': 'audio_stream_started',
            'device_id': device_id,
        })

    def stop_streaming(self, device_id: str) -> None:
        """设备停止音频流"""
        if device_id in self.audio_sources:
            del self.audio_sources[device_id]
            
            # 统计本次连接的帧数
            frame_count = self._frame_counts.pop(device_id, 0)
            buffer_size = len(self._buffers.pop(device_id, bytearray()))
            logger.info(
                f"Audio streaming STOPPED | device={device_id} | "
                f"total_frames={frame_count} | buffer_remain={buffer_size} bytes"
            )

            # 清理虚拟麦克风
            from devices.virtual_mic import vmic_manager
            vmic_manager.remove_client(device_id)

            # 通知所有客户端
            from devices.websocket import manager
            asyncio.create_task(manager.broadcast({
                'type': 'audio_stream_stopped',
                'device_id': device_id,
            }))

    def write_pcm(self, pcm_data: bytes, device_id: str = "default") -> None:
        """写入 PCM 数据到虚拟麦克风（带缓冲功能）"""
        import time
        
        try:
            # 字节对齐到 2 字节
            byte_len = len(pcm_data)
            if byte_len % 2 != 0:
                byte_len = byte_len - 1
                if byte_len <= 0:
                    return
            
            # 获取或创建设备缓冲器
            if device_id not in self._buffers:
                self._buffers[device_id] = bytearray()
            
            buffer = self._buffers[device_id]
            buffer.extend(pcm_data[:byte_len])
            buffer_size_before = len(buffer)
            
            # 从缓冲器中取出完整的 VMIC_CHUNK_SIZE 块
            vmic_bytes_per_chunk = VMIC_CHUNK_SIZE * BYTES_PER_SAMPLE  # 1920 bytes
            
            while len(buffer) >= vmic_bytes_per_chunk:
                chunk = bytes(buffer[:vmic_bytes_per_chunk])
                del buffer[:vmic_bytes_per_chunk]
                
                # 写入虚拟麦克风
                from devices.virtual_mic import vmic_manager
                vmic_manager.write_audio(chunk)
                
                # 统计
                self._pcm_count += 1
                self._frame_counts[device_id] = self._frame_counts.get(device_id, 0) + 1
                
                # 每 500 帧打印一次统计（约 40 秒音频）
                if self._pcm_count % 500 == 0:
                    current_time = time.time()
                    if current_time - self._last_log_time > 1:
                        logger.info(
                            f"[PCM] Stats | device={device_id} | "
                            f"total_chunks={self._pcm_count} | "
                            f"buffer={buffer_size_before} bytes"
                        )
                        self._last_log_time = current_time
            
            # 限制缓冲器大小（防止内存泄漏）
            if len(buffer) > vmic_bytes_per_chunk * 10:
                logger.warning(
                    f"[PCM] Buffer overflow | device={device_id} | "
                    f"buffer_size={len(buffer)} | truncating to {vmic_bytes_per_chunk * 2} bytes"
                )
                del buffer[:len(buffer) - vmic_bytes_per_chunk]
                    
        except Exception as e:
            logger.error(f"[PCM] Write error: {e}")

    def get_streaming_devices(self) -> list[str]:
        """获取正在传输音频的设备"""
        return list(self.audio_sources.keys())


# 全局音频流管理器
audio_manager = AudioStreamManager()


async def audio_websocket_handler(websocket: FWebSocket, device_id: str) -> None:
    """音频 WebSocket 处理函数（直接 PCM 方案）"""
    logger.info(f"[WS] 🔌 Audio WebSocket connection request from device: {device_id}")
    logger.info(f"[WS] 🔌 Client host: {websocket.client}")
    logger.info(f"[WS] 🔌 WebSocket path: /ws/audio/{device_id}")
    await audio_manager.start_streaming(device_id, websocket)
    logger.info(f"[WS] 🔌 Audio WebSocket connection accepted for device: {device_id}")
    logger.info(f"[WS] 🔌 Waiting for audio_start message...")

    try:
        while True:
            raw = await websocket.receive()

            msg_type = raw.get('type', '')

            # FastAPI WebSocket 断开连接
            if msg_type == 'websocket.disconnect':
                break

            try:
                # 处理文本消息（JSON控制消息）
                msg_text = raw.get('text', '')
                if msg_text:
                    message = json.loads(msg_text)
                    control_type = message.get('type')

                    if control_type == 'audio_start':
                        logger.info(f"Device {device_id} started audio transmission (format: {message.get('format', 'unknown')})")
                        await websocket.send_json({'type': 'ack', 'action': 'audio_start'})

                    elif control_type == 'audio_stop':
                        logger.info(f"Device {device_id} stopped audio transmission")
                        await websocket.send_json({'type': 'ack', 'action': 'audio_stop'})

                # 处理二进制消息（PCM 数据）
                bytes_data = raw.get('bytes')
                if bytes_data:
                    # 直接 PCM 数据（带设备ID用于缓冲）
                    audio_manager.write_pcm(bytes_data, device_id)
                else:
                    # 如果既不是 JSON 也不是二进制数据
                    if not msg_text:
                        logger.warning(f"[WS] Unknown message type from {device_id}")

            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from {device_id}")

    except (WebSocketDisconnect, ConnectionClosed, ConnectionClosedError, IncompleteReadError):
        # 优雅断开 - 不打印为错误，只是正常的连接关闭
        logger.info(f"WebSocket connection closed for {device_id}")
    except Exception as e:
        logger.error(f"Audio WebSocket error for {device_id}: {e}")

    finally:
        audio_manager.stop_streaming(device_id)
