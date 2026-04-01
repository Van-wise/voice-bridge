# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - FFmpeg 音频路由模块（方案A）
参考 toMic server.js 的直接音频路由架构

核心思路：不用 sounddevice，直接用 FFmpeg 把 PCM 数据输出到虚拟设备
数据流：WebSocket Opus → FFmpeg 解码+输出 → VB-Cable 虚拟麦克风

优势：
1. FFmpeg 更稳定，跨平台支持更好
2. 可以直接输出到 WASAPI/dsound 等后端
3. 音频处理更灵活（重采样、混音等）
"""

import asyncio
import logging
import os
import queue
import subprocess
import threading
from typing import Optional, Callable

logger = logging.getLogger("vb.ffmpeg_audio")


def _find_ffmpeg() -> str:
    """
    动态查找 FFmpeg 路径
    优先级：环境变量 > 项目目录 > 系统 PATH
    """
    import shutil as _shutil

    # 1. 环境变量
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. 项目目录
    project_ffmpeg = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ffmpeg_bin", "ffmpeg.exe")
    if os.path.exists(project_ffmpeg):
        return project_ffmpeg

    # 3. 系统 PATH
    system_ffmpeg = _shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    # 4. 回退到默认值
    return r"C:\ffmpeg_bin\ffmpeg.exe"


FFMPEG_PATH = _find_ffmpeg()


class FFmpegAudioRouter:
    """
    FFmpeg 音频路由器

    架构参考 toMic server.js:
    手机浏览器 Opus/WebM → WebSocket → FFmpeg 管道 → 虚拟声卡

    工作流程:
    1. 接收 Opus 音频块（来自 WebSocket）
    2. 通过 stdin 传给 FFmpeg
    3. FFmpeg 解码为 PCM 并直接输出到虚拟声卡设备
    4. Windows 系统把虚拟声卡识别为标准麦克风输入
    """

    def __init__(
        self,
        device_name: Optional[str] = None,
        sample_rate: int = 48000,
        channels: int = 1,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._target_device = device_name  # 如 "CABLE Input" 或 None（默认设备）

        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._queue: queue.Queue = queue.Queue(maxsize=200)
        self._lock = threading.Lock()

        # 统计
        self._bytes_processed = 0
        self._last_activity = 0

    def _get_ffmpeg_output_device_args(self) -> list[str]:
        """
        获取 FFmpeg 输出到虚拟设备的参数
        优先级：dsound > wasapi > waveout
        """
        if self._target_device:
            # 指定设备名
            # dsound 不支持指定设备名，只能用 wasapi 或 waveout
            return [
                "-f", "dshow",  # DirectShow (Windows)
                "-i", f"audio={self._target_device}",
            ]
        else:
            # 使用默认播放设备
            return []

    def _find_device_index(self) -> Optional[int]:
        """查找虚拟声卡设备索引"""
        try:
            # 使用 ffmpeg -list_devices true -f dshow dummy 列出设备
            cmd = [FFMPEG_PATH, "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )

            output = result.stdout + result.stderr
            logger.debug(f"FFmpeg device list:\n{output}")

            # 查找 CABLE Input 或 VB-Audio
            lines = output.split('\n')
            device_idx = None
            for i, line in enumerate(lines):
                if 'CABLE Input' in line or 'VB-Audio' in line or 'Virtual Cable' in line:
                    # 提取设备索引
                    if '(' in line:
                        idx_str = line.split('(')[-1].split(')')[0]
                        try:
                            device_idx = int(idx_str)
                            logger.info(f"Found virtual audio device: {line.strip()}")
                            return device_idx
                        except ValueError:
                            pass

            return None
        except Exception as e:
            logger.error(f"Error finding device: {e}")
            return None

    def start(self) -> dict:
        """
        启动 FFmpeg 音频路由

        Returns:
            dict: 启动结果 {success, device_index, device_name, message}
        """
        with self._lock:
            if self._proc is not None:
                return {
                    'success': True,
                    'message': f'FFmpeg 音频路由已在运行',
                    'sample_rate': self._sample_rate,
                }

            # 检查 FFmpeg
            if not os.path.exists(FFMPEG_PATH):
                logger.error(f"FFmpeg not found: {FFMPEG_PATH}")
                return {
                    'success': False,
                    'error': 'FFMPEG_NOT_FOUND',
                    'message': f'FFmpeg 未找到: {FFMPEG_PATH}',
                }

            # 清空队列
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

            try:
                # 方法1：使用 dshow 输出到虚拟设备（需要设备名称）
                # 这是最可靠的方式，让 FFmpeg 直接输出到 DirectShow 音频设备

                # 首先尝试用 am电影 来获取虚拟设备
                device_name = self._get_virtual_device_name()
                if device_name:
                    cmd = self._build_dshow_command(device_name)
                else:
                    # 方法2：回退到 waveout 或默认设备
                    cmd = self._build_waveout_command()

                logger.info(f"Starting FFmpeg audio router: {' '.join(cmd[:8])}...")

                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )

                self._running = True
                self._bytes_processed = 0
                self._last_activity = 0

                # 启动输出线程
                self._thread = threading.Thread(target=self._write_loop, daemon=True)
                self._thread.start()

                logger.info("FFmpeg audio router started successfully")
                return {
                    'success': True,
                    'message': 'FFmpeg 音频路由已启动',
                    'sample_rate': self._sample_rate,
                    'device': device_name or '默认设备',
                }

            except Exception as e:
                logger.error(f"Failed to start FFmpeg: {e}")
                self._cleanup()
                return {
                    'success': False,
                    'error': str(e),
                    'message': f'启动失败: {e}',
                }

    def _get_virtual_device_name(self) -> Optional[str]:
        """获取虚拟声卡设备名称"""
        # 常见的虚拟声卡设备名称
        # 注意：VB-Audio Virtual Cable 的播放设备叫 "CABLE Output"，不是 "CABLE Input"
        possible_names = [
            "CABLE Output (VB-Audio Virtual Cable)",
            "VB-Audio Virtual Cable",
            "CABLE Output",
            "VoiceMeeter Virtual Output",
            "VoiceMeeter AUX Output",
            "VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)",
            "CABLE Input (VB-Audio Virtual Cable)",
        ]

        try:
            # 用 ffmpeg -list_devices 查找
            cmd = [FFMPEG_PATH, "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )

            output = result.stderr + result.stdout

            for name in possible_names:
                if name in output:
                    logger.info(f"Found virtual device: {name}")
                    return name

            # 尝试模糊匹配
            if 'CABLE' in output or 'VB-Audio' in output or 'Virtual' in output:
                for line in output.split('\n'):
                    if 'audio' in line.lower() and ('cable' in line.lower() or 'virtual' in line.lower()):
                        # 提取设备名
                        name = line.split('"')[1] if '"' in line else line.strip()
                        if name and 'dummy' not in name:
                            logger.info(f"Found virtual device (fuzzy): {name}")
                            return name

        except Exception as e:
            logger.warning(f"Error finding device name: {e}")

        return None

    def _build_dshow_command(self, device_name: str) -> list[str]:
        """
        构建 DirectShow 输出命令
        FFmpeg 从 stdin 读取 PCM，然后通过 dshow 输出到音频设备
        """
        return [
            FFMPEG_PATH,
            "-loglevel", "error",
            # 输入：PCM 原始流
            "-f", "s16le",           # 输入格式：16bit little-endian PCM
            "-ar", str(self._sample_rate),  # 采样率
            "-ac", str(self._channels),     # 声道数
            "-i", "pipe:0",          # 从 stdin 读取
            # 输出：DirectSound
            "-f", "dsound",          # Windows DirectSound 输出
            f"audio={device_name}",  # 目标设备
        ]

    def _build_waveout_command(self) -> list[str]:
        """
        构建 waveout 输出命令（回退方案）
        """
        return [
            FFMPEG_PATH,
            "-loglevel", "error",
            "-f", "s16le",
            "-ar", str(self._sample_rate),
            "-ac", str(self._channels),
            "-i", "pipe:0",
            "-f", "waveout",         # Windows WaveOut 输出
        ]

    def stop(self) -> dict:
        """停止 FFmpeg 音频路由"""
        self._running = False
        self._cleanup()
        return {
            'success': True,
            'message': 'FFmpeg 音频路由已停止',
            'bytes_processed': self._bytes_processed,
        }

    def _cleanup(self) -> None:
        """清理资源"""
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.stdout.close()
                self._proc.stderr.close()
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None

    def _write_loop(self) -> None:
        """持续从队列读取 PCM 数据并写入 FFmpeg stdin"""
        logger.info("FFmpeg write loop started")

        silence_count = 0
        while self._running:
            try:
                # 从队列获取音频数据（最多等 50ms）
                try:
                    chunk = self._queue.get(timeout=0.05)
                    silence_count = 0
                    self._last_activity = 0
                except queue.Empty:
                    # 队列为空，写入静音
                    chunk = b'\x00' * 1920  # 20ms 静音 @ 48kHz mono s16le
                    silence_count += 1

                # 写入 FFmpeg stdin
                if self._proc and self._proc.poll() is None:
                    try:
                        self._proc.stdin.write(chunk)
                        self._proc.stdin.flush()
                        self._bytes_processed += len(chunk)
                        self._last_activity += 1
                    except BrokenPipeError:
                        logger.warning("FFmpeg process ended, restarting...")
                        break
                    except Exception as e:
                        logger.debug(f"Write error: {e}")

                # 如果连续 100 个静音块（约 2 秒无音频），停止输出线程
                if silence_count > 100 and self._bytes_processed > 0:
                    logger.info("No audio for 2 seconds, stopping...")
                    break

            except Exception as e:
                if self._running:
                    logger.error(f"Write loop error: {e}")

        logger.info(f"FFmpeg write loop stopped (processed {self._bytes_processed} bytes)")

    def write_audio(self, pcm_data: bytes) -> None:
        """
        接收 PCM 音频数据，加入队列

        Args:
            pcm_data: 48kHz, mono, 16bit PCM 原始字节
        """
        if not self._running:
            return

        try:
            # 确保数据长度正确（1920 bytes = 20ms @ 48kHz mono)
            expected_len = 1920  # 48k * 1ch * 2bytes * 0.02s

            if len(pcm_data) < expected_len:
                # 填充静音
                pcm_data = pcm_data + b'\x00' * (expected_len - len(pcm_data))
            elif len(pcm_data) > expected_len:
                # 截断
                pcm_data = pcm_data[:expected_len]

            # 非阻塞放入队列
            try:
                self._queue.put_nowait(pcm_data)
            except queue.Full:
                # 队列满了，丢弃最旧的
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(pcm_data)
                except queue.Empty:
                    pass

        except Exception as e:
            logger.debug(f"Audio write error: {e}")

    def is_active(self) -> bool:
        """是否正在运行"""
        return self._running and self._proc is not None and self._proc.poll() is None

    def get_status(self) -> dict:
        """获取状态"""
        return {
            'active': self.is_active(),
            'sample_rate': self._sample_rate,
            'channels': self._channels,
            'queue_size': self._queue.qsize(),
            'bytes_processed': self._bytes_processed,
            'last_activity_blocks': self._last_activity,
        }


class OpusToFFmpegDecoder:
    """
    Opus 解码器 + FFmpeg 输出组合

    数据流：WebSocket Opus → FFmpeg 解码 → PCM → FFmpegAudioRouter → 虚拟设备
    """

    def __init__(self, router: FFmpegAudioRouter) -> None:
        self._router = router
        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._queue: queue.Queue = queue.Queue(maxsize=200)

    def start(self) -> bool:
        """启动 Opus 解码器"""
        if not os.path.exists(FFMPEG_PATH):
            logger.error(f"FFmpeg not found: {FFMPEG_PATH}")
            return False

        if self._proc is not None:
            return True

        try:
            # Opus 解码命令
            cmd = [
                FFMPEG_PATH,
                "-loglevel", "error",
                "-f", "ogg",           # 输入格式：Ogg 容器
                "-i", "pipe:0",         # 从 stdin 读取
                "-ar", "48000",         # 输出采样率
                "-ac", "1",             # 单声道
                "-acodec", "pcm_s16le", # 16bit PCM
                "-f", "s16le",          # 输出格式
                "pipe:1",               # 输出到 stdout
            ]

            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )

            self._running = True

            # 启动读取线程
            threading.Thread(target=self._read_loop, daemon=True).start()

            logger.info("Opus decoder started")
            return True

        except Exception as e:
            logger.error(f"Failed to start Opus decoder: {e}")
            return False

    def _read_loop(self) -> None:
        """从 FFmpeg stdout 读取解码后的 PCM"""
        chunk_size = 1920  # 20ms @ 48kHz mono s16le

        while self._running:
            try:
                data = self._proc.stdout.read(chunk_size)
                if not data:
                    break

                # 交给路由器
                self._router.write_audio(bytes(data))

            except Exception as e:
                if self._running:
                    logger.error(f"Decoder read error: {e}")
                break

    def write_opus(self, opus_data: bytes) -> None:
        """写入 Opus 数据"""
        if self._proc is None or self._proc.poll() is not None:
            return

        try:
            self._proc.stdin.write(opus_data)
            self._proc.stdin.flush()
        except Exception as e:
            logger.debug(f"Opus write error: {e}")

    def stop(self) -> None:
        """停止解码器"""
        self._running = False
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.stdout.close()
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None


# 全局实例
ffmpeg_router = FFmpegAudioRouter()
