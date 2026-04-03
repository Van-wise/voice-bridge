# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - WebSocket 管理
实时双向通信（重构版 - 解决连接泄漏和广播异常）
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("vb.websocket")


class ConnectionManager:
    """WebSocket 连接管理器（支持单设备单连接去重，带锁保护）"""

    def __init__(self) -> None:
        # device_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # IP 地址 -> device_id（用于 API 请求时识别设备）
        self._ip_to_device: Dict[str, str] = {}
        # device_id -> IP 地址
        self._device_to_ip: Dict[str, str] = {}
        # 加锁保护连接操作，避免并发修改
        self._lock = asyncio.Lock()
        # 正在关闭的连接（防止重复关闭）
        self._closing_connections: set = set()

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        """连接（自动去重：关闭旧连接再建立新连接，带锁保护）"""
        # 获取客户端 IP（尝试从 headers 中获取真实 IP）
        client_ip = None
        if websocket.client:
            client_ip = websocket.client.host
        
        # 尝试从 WebSocket scope headers 获取真实 IP
        try:
            headers = dict(websocket.scope.get('headers', []))
            # 尝试 X-Forwarded-For
            xff = headers.get(b'x-forwarded-for')
            if xff:
                # X-Forwarded-For 可能包含多个 IP，取第一个
                client_ip = xff.decode().split(',')[0].strip()
            else:
                # 尝试 X-Real-IP
                xri = headers.get(b'x-real-ip')
                if xri:
                    client_ip = xri.decode().strip()
        except Exception as e:
            logger.debug(f"[WS] 获取真实IP失败: {e}")
        
        async with self._lock:
            # 先关闭旧连接（如果存在）
            if device_id in self.active_connections:
                old_ws = self.active_connections[device_id]
                logger.warning(f"[WS] 设备 {device_id} 已有活跃连接，关闭旧连接（总数：{len(self.active_connections)}）")
                try:
                    self._closing_connections.add(device_id)
                    await asyncio.wait_for(old_ws.close(code=1000, reason="新连接替换旧连接"), timeout=1.0)
                    logger.info(f"[WS] 设备 {device_id} 旧连接已关闭")
                except asyncio.TimeoutError:
                    logger.warning(f"[WS] 关闭旧连接超时: {device_id}")
                except Exception as e:
                    logger.debug(f"[WS] 关闭旧连接异常: {e}")
                finally:
                    self._closing_connections.discard(device_id)
                    if device_id in self.active_connections:
                        del self.active_connections[device_id]
                    # 清理旧的 IP 映射
                    old_ip = self._device_to_ip.get(device_id)
                    if old_ip and self._ip_to_device.get(old_ip) == device_id:
                        del self._ip_to_device[old_ip]
                    if device_id in self._device_to_ip:
                        del self._device_to_ip[device_id]
            
            # 接受新连接
            await websocket.accept()
            self.active_connections[device_id] = websocket
            
            # 记录 IP 映射
            if client_ip:
                self._ip_to_device[client_ip] = device_id
                self._device_to_ip[device_id] = client_ip
        
        logger.info(f"[WS] 设备连接成功: {device_id} | IP: {client_ip} (总数: {len(self.active_connections)})")

    def disconnect(self, device_id: str) -> None:
        """断开连接（强制清理，解决连接泄漏）- 使用同步方式避免事件循环问题"""
        try:
            if device_id in self.active_connections:
                try:
                    # 直接关闭连接，不等待
                    ws = self.active_connections[device_id]
                    ws.close(code=1000, reason="主动断开")
                except Exception as e:
                    logger.debug(f"[WS] 关闭连接异常 {device_id}: {e}")
                finally:
                    # 无论关闭是否成功，都移除连接
                    if device_id in self.active_connections:
                        del self.active_connections[device_id]
                
                # 清理 IP 映射
                device_ip = self._device_to_ip.pop(device_id, None)
                if device_ip and self._ip_to_device.get(device_ip) == device_id:
                    del self._ip_to_device[device_ip]
                
                logger.info(f"[WS] 设备断开: {device_id} (总数: {len(self.active_connections)})")
        except Exception as e:
            logger.warning(f"[WS] 断开连接出错 {device_id}: {e}")
    
    async def async_disconnect(self, device_id: str) -> None:
        """异步断开连接（带锁保护）"""
        async with self._lock:
            if device_id in self._closing_connections:
                await asyncio.sleep(0.1)
            
            if device_id in self.active_connections:
                try:
                    ws = self.active_connections[device_id]
                    await asyncio.wait_for(ws.close(code=1000, reason="主动断开"), timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warning(f"[WS] 关闭连接超时: {device_id}")
                except Exception as e:
                    logger.warning(f"[WS] 关闭连接失败 {device_id}: {e}")
                finally:
                    if device_id in self.active_connections:
                        del self.active_connections[device_id]
            
            device_ip = self._device_to_ip.pop(device_id, None)
            if device_ip and self._ip_to_device.get(device_ip) == device_id:
                del self._ip_to_device[device_ip]
        
        logger.info(f"[WS] 设备断开: {device_id} (总数: {len(self.active_connections)})")

    async def send_to_device(self, device_id: str, message: dict[str, Any]) -> bool:
        """发送消息到指定设备（带超时）"""
        async with self._lock:
            if device_id not in self.active_connections:
                return False
            websocket = self.active_connections[device_id]
        
        try:
            await asyncio.wait_for(websocket.send_json(message), timeout=1.0)
            return True
        except asyncio.TimeoutError:
            logger.error(f"[WS] 发送超时，强制断开 {device_id}")
            await self.disconnect(device_id)
            return False
        except Exception as e:
            logger.error(f"[WS] 发送失败 {device_id}: {e}")
            await self.disconnect(device_id)
            return False

    async def broadcast(self, message: dict[str, Any], exclude: Optional[str] = None) -> None:
        """
        广播消息到所有设备（逐个连接捕获异常，避免一个连接失败阻塞全部）
        """
        # 先复制连接列表，避免广播中连接被修改
        async with self._lock:
            connections = list(self.active_connections.items())
        
        success_count = 0
        fail_count = 0
        
        for device_id, websocket in connections:
            # 排除源设备
            if device_id == exclude:
                continue
            
            try:
                # 异步发送（设置超时，避免卡死）
                await asyncio.wait_for(websocket.send_json(message), timeout=1.0)
                success_count += 1
            except asyncio.TimeoutError:
                logger.error(f"[WS] 设备 {device_id} 发送超时，强制断开")
                await self.async_disconnect(device_id)
                fail_count += 1
            except Exception as e:
                logger.error(f"[WS] 设备 {device_id} 发送失败: {e}")
                await self.async_disconnect(device_id)
                fail_count += 1
        
        logger.info(f"[WS] 广播完成：成功 {success_count} 台，失败 {fail_count} 台（排除 {exclude}）")

    def is_online(self, device_id: str) -> bool:
        """检查设备是否在线"""
        return device_id in self.active_connections
    
    def get_device_by_ip(self, ip: str) -> Optional[str]:
        """通过 IP 地址获取设备 ID"""
        return self._ip_to_device.get(ip)
    
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
        manager.disconnect(device_id)  # 使用同步方法，避免事件循环问题
        logger.info(f"[WS] 设备 {device_id} 主动断开")
    except json.JSONDecodeError:
        logger.error(f"[WS] Invalid JSON from {device_id}")
        manager.disconnect(device_id)
    except Exception as e:
        logger.error(f"[WS] 设备 {device_id} 异常: {e}", exc_info=True)
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
        logger.warning(f"[WS] Unknown message type: {msg_type}")
