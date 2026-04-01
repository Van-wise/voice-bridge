# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - WebSocket 管理
实时双向通信
"""

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("vb.websocket")


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self) -> None:
        # device_id -> WebSocket
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        """连接"""
        await websocket.accept()
        self.active_connections[device_id] = websocket
        logger.info(f"Device connected: {device_id} (total: {len(self.active_connections)})")

    def disconnect(self, device_id: str) -> None:
        """断开连接"""
        if device_id in self.active_connections:
            del self.active_connections[device_id]
            logger.info(f"Device disconnected: {device_id} (total: {len(self.active_connections)})")

    async def send_to_device(self, device_id: str, message: dict[str, Any]) -> bool:
        """发送消息到指定设备"""
        if device_id in self.active_connections:
            websocket = self.active_connections[device_id]
            try:
                await websocket.send_json(message)
                return True
            except Exception as e:
                logger.error(f"Failed to send to {device_id}: {e}")
                self.disconnect(device_id)
                return False
        return False

    async def broadcast(self, message: dict[str, Any], exclude: str | None = None) -> None:
        """广播消息到所有设备"""
        for device_id, websocket in list(self.active_connections.items()):
            if device_id == exclude:
                continue
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Failed to broadcast to {device_id}: {e}")
                self.disconnect(device_id)

    def is_online(self, device_id: str) -> bool:
        """检查设备是否在线"""
        return device_id in self.active_connections

    def get_online_devices(self) -> list[str]:
        """获取所有在线设备 ID"""
        return list(self.active_connections.keys())


# 全局连接管理器
manager = ConnectionManager()


async def websocket_handler(websocket: WebSocket, device_id: str) -> None:
    """WebSocket 处理函数"""
    await manager.connect(device_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await handle_ws_message(device_id, message)
    except WebSocketDisconnect:
        manager.disconnect(device_id)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON from {device_id}")
        manager.disconnect(device_id)


async def handle_ws_message(device_id: str, message: dict[str, Any]) -> None:
    """处理 WebSocket 消息"""
    msg_type = message.get("type")

    if msg_type == "ping":
        # 心跳响应
        await manager.send_to_device(device_id, {"type": "pong"})
    
    elif msg_type == "clipboard_sync":
        # 剪贴板同步 - 广播到其他设备
        await manager.broadcast(
            {
                "type": "clipboard_update",
                "data": message.get("data"),
                "source": device_id,
            },
            exclude=device_id,
        )

    elif msg_type == "sync_request":
        # 同步请求 - 设备请求最新数据
        # TODO: 从数据库获取最新数据并发送
        await manager.send_to_device(device_id, {
            "type": "sync_response",
            "data": {"status": "ok"}
        })

    else:
        logger.warning(f"Unknown message type: {msg_type}")
