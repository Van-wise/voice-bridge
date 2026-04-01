# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - 虚拟麦克风模块
把手机麦克风音频流输出到 Windows 虚拟声卡设备
核心逻辑参考 toMic/AndroidMic 架构:
  手机浏览器(MediaRecorder/Opus) → WebSocket → Python(sounddevice) → VB-Audio虚拟麦克风
"""

import logging
import queue
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("vb.vmic")

# 尝试导入 sounddevice（核心依赖）
try:
    import sounddevice as sd
    SOUNDDEVICE_OK = True
except ImportError:
    SOUNDDEVICE_OK = False
    logger.warning("sounddevice not installed - virtual mic will not work")


class VirtualMicManager:
    """
    虚拟麦克风管理器

    工作原理（参考 toMic server.js）:
    1. 手机浏览器通过 WebSocket 发送 Opus/WebM 音频块
    2. FFmpeg 解码为 PCM (48kHz, mono, 16bit)
    3. sounddevice OutputStream 写入 VB-Audio 虚拟麦克风设备
    4. Windows 系统把 VB-Audio 识别为标准麦克风输入

    数据流:
    WebSocket 音频块 → 队列 → sounddevice OutputStream → 虚拟麦克风设备
    """

    def __init__(self) -> None:
        self._stream: Optional[sd.OutputStream] = None
        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._device_index: int = -1
        self._device_name: str = ""
        self._connected_clients: set = set()
        self._sample_rate = 48000
        self._channels = 1
        self._is_16ch = False  # 是否为 16ch 版本
        self._dtype = 'int16'
        self._chunk_size = 960  # 20ms @ 48kHz = 960 samples
        self._silence_buffer = np.zeros(self._chunk_size, dtype=np.int16)
        self._blocks_since_last_audio = 0
        self._is_active = False

    def find_virtual_cable(self) -> Optional[int]:
        """查找 VB-Audio Virtual Cable 设备索引"""
        if not SOUNDDEVICE_OK:
            return None

        try:
            devices = sd.query_devices()
            if isinstance(devices, dict):
                devices = [devices]

            # 优先查找普通版（2通道）CABLE Input，16ch 版本需要特殊处理
            # 普通版: "CABLE Input" 或 "CABLE In" (不带 16ch)
            # 16ch版: "CABLE In 16ch" 或 "CABLE Input 16ch"
            
            # 第一优先级：普通版 CABLE Input（2通道）
            for dev in devices:
                if dev.get('max_output_channels', 0) > 0 or dev.get('output_channels', 0) > 0:
                    name = dev.get('name', '').lower()
                    # 匹配 CABLE Input 但排除 16ch
                    if ('cable input' in name or 'cable in' in name) and '16ch' not in name:
                        idx = dev.get('index')
                        self._device_name = dev.get('name', '')
                        logger.info(f"Found virtual cable device (2ch): [{idx}] {self._device_name}")
                        return idx
            
            # 第二优先级：16ch 版本
            for dev in devices:
                if dev.get('max_output_channels', 0) > 0 or dev.get('output_channels', 0) > 0:
                    name = dev.get('name', '').lower()
                    if 'cable' in name and ('vb-audio' in name or 'virtual' in name):
                        idx = dev.get('index')
                        self._device_name = dev.get('name', '')
                        logger.info(f"Found virtual cable device (16ch): [{idx}] {self._device_name}")
                        self._is_16ch = True
                        return idx

            return None
        except Exception as e:
            logger.error(f"Error querying devices: {e}")
            return None

    def start(self) -> dict:
        """
        启动虚拟麦克风
        Returns:
            dict: 启动结果 {success, device_index, device_name, sample_rate, message}
        """
        if not SOUNDDEVICE_OK:
            return {
                'success': False,
                'error': 'sounddevice not installed',
                'message': '请运行: pip install sounddevice numpy',
            }

        if self._stream is not None:
            return {
                'success': True,
                'message': f'虚拟麦克风已在运行 (设备: {self._device_name})',
                'device_index': self._device_index,
                'device_name': self._device_name,
                'sample_rate': self._sample_rate,
            }

        # 查找虚拟声卡
        device_idx = self.find_virtual_cable()
        if device_idx is None:
            return {
                'success': False,
                'error': 'VIRTUAL_CABLE_NOT_FOUND',
                'message': '未找到 VB-Audio Virtual Cable，请先安装！\n下载地址: https://vb-audio.com/Cable/',
            }

        self._device_index = device_idx

        try:
            # 清空队列
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

            # 对于 16ch 设备，需要特殊处理
            # 尝试使用该设备的第一个子设备（ch1）或者使用 WASAPI 接口
            target_device = device_idx
            target_channels = self._channels
            
            if self._is_16ch:
                logger.info(f"[VMic] 16ch device detected, trying WASAPI interface...")
                # 尝试使用 WASAPI 接口（通常是更高的编号，如设备 22）
                # 但这里我们先用当前设备试试
                # 16ch 设备可能需要特定的通道映射
            
            # 创建 OutputStream（输出到虚拟麦克风设备）
            try:
                self._stream = sd.OutputStream(
                    device=target_device,
                    channels=target_channels,
                    samplerate=self._sample_rate,
                    dtype=self._dtype,
                    blocksize=self._chunk_size,
                    latency='low',
                )
            except Exception as stream_err:
                # 如果失败，尝试使用 WASAPI 接口
                logger.warning(f"[VMic] Direct stream failed: {stream_err}, trying WASAPI...")
                if self._is_16ch:
                    # 16ch 设备尝试查找对应的 WASAPI 版本
                    try:
                        devices = sd.query_devices()
                        for dev in devices:
                            # sounddevice.query_devices() 返回 dict，需用 .get() 访问
                            dev_name = dev.get('name', '')
                            dev_hostapi = str(dev.get('hostapi', '')).lower()
                            if 'cable input' in dev_name.lower() and 'wasapi' in dev_hostapi:
                                target_device = dev.get('index')
                                logger.info(f"[VMic] Using WASAPI device: [{target_device}] {dev_name}")
                                break
                    except:
                        pass
                    
                    self._stream = sd.OutputStream(
                        device=target_device,
                        channels=target_channels,
                        samplerate=self._sample_rate,
                        dtype=self._dtype,
                        blocksize=self._chunk_size,
                    )
                else:
                    raise
                    
            self._stream.start()

            # 启动音频播放线程
            self._running = True
            self._thread = threading.Thread(target=self._playback_loop, daemon=True)
            self._thread.start()

            self._is_active = True

            logger.info(f"Virtual mic started: device=[{device_idx}] {self._device_name}")
            return {
                'success': True,
                'device_index': device_idx,
                'device_name': self._device_name,
                'sample_rate': self._sample_rate,
                'message': f'虚拟麦克风已启动: {self._device_name}',
            }

        except Exception as e:
            logger.error(f"Failed to start virtual mic: {e}")
            self._cleanup()
            return {
                'success': False,
                'error': str(e),
                'message': f'启动失败: {e}',
            }

    def stop(self) -> dict:
        """停止虚拟麦克风"""
        self._is_active = False
        self._cleanup()
        return {
            'success': True,
            'message': '虚拟麦克风已停止',
        }

    def _cleanup(self) -> None:
        """清理资源"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._device_index = -1

    def _playback_loop(self) -> None:
        """音频播放线程（参考 toMic: SoX 播放逻辑）"""
        logger.info("Virtual mic playback loop started")
        write_count = 0
        last_queue_info_time = time.time()

        while self._running:
            try:
                # 从队列获取音频数据（最多等50ms）
                try:
                    chunk = self._queue.get(timeout=0.05)
                    self._blocks_since_last_audio = 0
                except queue.Empty:
                    # 队列为空，输出静音（保持流活跃）
                    chunk = self._silence_buffer
                    self._blocks_since_last_audio += 1

                # 写入虚拟设备
                if self._stream and self._stream.active:
                    self._stream.write(chunk)
                    write_count += 1
                    
                    # 每5秒打印一次统计
                    current_time = time.time()
                    if current_time - last_queue_info_time > 5:
                        queue_size = self._queue.qsize()
                        silence_count = self._blocks_since_last_audio
                        logger.info(f"[VMic] Stats: wrote={write_count}, queue={queue_size}, silence_blocks={silence_count}")
                        last_queue_info_time = current_time
                        write_count = 0

            except Exception as e:
                if self._running:
                    logger.error(f"Playback error: {e}")

        logger.info("Virtual mic playback loop stopped")

    def write_audio(self, pcm_data: bytes) -> None:
        """
        接收原始 PCM 音频数据，写入虚拟麦克风队列
        Args:
            pcm_data: 48kHz, mono, 16bit PCM 原始字节
        """
        if not self._running or self._stream is None:
            return

        try:
            # 把 bytes 转为 numpy array
            np_data = np.frombuffer(pcm_data, dtype=np.int16)
            
            # 计算音频数据的平均幅度（用于调试）
            avg_amplitude = float(np.mean(np.abs(np_data)))
            max_amplitude = int(np.max(np.abs(np_data)))

            # 如果数据长度不匹配 chunk_size，进行填充或截断
            if len(np_data) < self._chunk_size:
                # 填充
                padded = np.zeros(self._chunk_size, dtype=np.int16)
                padded[:len(np_data)] = np_data
                np_data = padded
            elif len(np_data) > self._chunk_size:
                np_data = np_data[:self._chunk_size]

            # 放入队列（非阻塞）
            try:
                self._queue.put_nowait(np_data)
            except queue.Full:
                # 队列满了，丢弃最旧的
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(np_data)
                except queue.Empty:
                    pass

        except Exception as e:
            logger.error(f"[VMic] Audio write error: {e}")

    def add_client(self, device_id: str) -> None:
        """添加客户端连接"""
        self._connected_clients.add(device_id)
        logger.info(f"Virtual mic client connected: {device_id} (total: {len(self._connected_clients)})")

    def remove_client(self, device_id: str) -> None:
        """移除客户端连接"""
        self._connected_clients.discard(device_id)
        logger.info(f"Virtual mic client disconnected: {device_id} (remaining: {len(self._connected_clients)})")

        # 如果没有客户端了，停止虚拟麦克风释放资源
        if len(self._connected_clients) == 0:
            logger.info("No more virtual mic clients, stopping virtual mic to save resources")
            self._cleanup()

    def is_active(self) -> bool:
        """是否正在运行"""
        return self._running and self._stream is not None

    def get_status(self) -> dict:
        """获取状态"""
        return {
            'active': self.is_active(),
            'device_index': self._device_index,
            'device_name': self._device_name,
            'clients': list(self._connected_clients),
            'queue_size': self._queue.qsize(),
            'sample_rate': self._sample_rate,
            'channels': self._channels,
        }


# 全局实例
vmic_manager = VirtualMicManager()
