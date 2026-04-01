// Voice Bridge Frontend - Direct PCM Audio Bridge
// 方案：使用 Web Audio API 直接获取 PCM 数据，发送到后端
// 后端直接使用 sounddevice 播放，无需 FFmpeg 解码

import { ref } from 'vue'

// ─────────────────────────────────────────────────────────────────────────────
// 类型定义
// ─────────────────────────────────────────────────────────────────────────────
interface AudioBridgeState {
  stream: MediaStream | null
  audioContext: AudioContext | null
  analyser: AnalyserNode | null
  ws: WebSocket | null
  sourceNode: MediaStreamAudioSourceNode | null
  processor: ScriptProcessorNode | null
  isActive: boolean
  isConnecting: boolean
  volumeLevel: number
  error: string | null
}

// ─────────────────────────────────────────────────────────────────────────────
// 全局状态
// ─────────────────────────────────────────────────────────────────────────────
const state: AudioBridgeState = {
  stream: null,
  audioContext: null,
  analyser: null,
  ws: null,
  sourceNode: null,
  processor: null,
  isActive: false,
  isConnecting: false,
  volumeLevel: 0,
  error: null,
}

// VAD 检测阈值
const VAD_THRESHOLD = 0.01  // 1% 的音量阈值

// 采样率
const SAMPLE_RATE = 48000

// ─────────────────────────────────────────────────────────────────────────────
// 工具函数
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 计算音频块的 RMS 音量
 */
function calculateRMS(buffer: Float32Array): number {
  let sum = 0
  for (let i = 0; i < buffer.length; i++) {
    sum += buffer[i] * buffer[i]
  }
  return Math.sqrt(sum / buffer.length)
}

/**
 * 将 Float32Array 转换为 Int16Array (PCM 16bit)
 */
function float32ToInt16(float32Array: Float32Array): Int16Array {
  const int16Array = new Int16Array(float32Array.length)
  for (let i = 0; i < float32Array.length; i++) {
    // 限制范围到 [-1, 1]
    const s = Math.max(-1, Math.min(1, float32Array[i]))
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
  }
  return int16Array
}

// ─────────────────────────────────────────────────────────────────────────────
// 核心功能
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 启动音频桥接
 * 使用 Web Audio API 直接获取 PCM 数据，绕过 MediaRecorder
 */
export async function startAudioBridge(
  deviceId: string,
  onStatusChange: (status: Partial<AudioBridgeState>) => void
): Promise<void> {
  try {
    onStatusChange({ isConnecting: true, error: null })

    // 1. 获取麦克风权限
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: SAMPLE_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    })
    state.stream = stream

    // 2. 创建 AudioContext
    const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE })
    state.audioContext = audioContext

    // 3. 创建音频源
    const sourceNode = audioContext.createMediaStreamSource(stream)
    state.sourceNode = sourceNode

    // 4. 创建分析器（用于 VAD）
    const analyser = audioContext.createAnalyser()
    analyser.fftSize = 1024
    sourceNode.connect(analyser)
    state.analyser = analyser

    // 5. 创建 ScriptProcessorNode 获取 PCM 数据
    // 缓冲区大小: 4800 samples = 100ms @ 48kHz
    const bufferSize = 4800
    const processor = audioContext.createScriptProcessor(bufferSize, 1, 1)
    state.processor = processor

    // 处理音频数据
    processor.onaudioprocess = (event) => {
      const inputBuffer = event.inputBuffer
      const inputData = inputBuffer.getChannelData(0) // Float32Array, 范围 [-1, 1]

      // 计算音量
      const rms = calculateRMS(inputData)
      state.volumeLevel = rms

      // VAD 检测：如果音量太低，跳过
      if (rms < VAD_THRESHOLD) {
        return
      }

      // 转换为 Int16 PCM
      const pcmData = float32ToInt16(inputData)

      // 通过 WebSocket 发送
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        // 发送 PCM 数据（二进制）
        state.ws.send(pcmData.buffer)
      }
    }

    // 连接节点（只需要连接到 processor，不需要连接到 destination）
    sourceNode.connect(processor)
    // 注意：不连接到 audioContext.destination，避免回音

    // 6. 建立 WebSocket 连接
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${proto}//${window.location.host}/ws/audio/${deviceId}`
    const ws = new WebSocket(wsUrl)
    state.ws = ws

    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      console.log('[AudioBridge] WebSocket connected')
      state.isActive = true
      state.isConnecting = false
      onStatusChange({ isActive: true, isConnecting: false })

      // 发送开始信号
      ws.send(JSON.stringify({
        type: 'audio_start',
        format: 'pcm',
        sampleRate: SAMPLE_RATE,
        channels: 1,
        timestamp: Date.now()
      }))
    }

    ws.onmessage = (event) => {
      try {
        const msg = typeof event.data === 'string'
          ? JSON.parse(event.data)
          : null

        if (msg?.type === 'vmic_status' && !msg.success) {
          state.error = msg.error || msg.message
          onStatusChange({ error: state.error })
          stopAudioBridge()
        }
      } catch {}
    }

    ws.onerror = () => {
      state.error = 'WebSocket 连接错误'
      onStatusChange({ error: state.error, isConnecting: false })
    }

    ws.onclose = () => {
      if (state.isActive) {
        stopAudioBridge()
      }
    }

  } catch (error: any) {
    console.error('[AudioBridge] Failed to start:', error)
    state.error = error.message || '启动失败'
    onStatusChange({ error: state.error, isConnecting: false })
    cleanup()
  }
}

/**
 * 停止音频桥接
 */
export function stopAudioBridge(): void {
  cleanup()
}

/**
 * 清理资源
 */
function cleanup(): void {
  // 停止所有媒体轨道
  if (state.stream) {
    state.stream.getTracks().forEach(track => track.stop())
    state.stream = null
  }

  // 断开音频节点
  if (state.sourceNode) {
    try {
      state.sourceNode.disconnect()
    } catch {}
    state.sourceNode = null
  }

  if (state.processor) {
    try {
      state.processor.disconnect()
    } catch {}
    state.processor = null
  }

  if (state.analyser) {
    try {
      state.analyser.disconnect()
    } catch {}
    state.analyser = null
  }

  // 关闭 AudioContext
  if (state.audioContext) {
    state.audioContext.close()
    state.audioContext = null
  }

  // 关闭 WebSocket
  if (state.ws) {
    try {
      state.ws.close()
    } catch {}
    state.ws = null
  }

  state.isActive = false
  state.isConnecting = false
  state.volumeLevel = 0
}

/**
 * 获取当前状态
 */
export function getAudioBridgeState(): AudioBridgeState {
  return { ...state }
}
