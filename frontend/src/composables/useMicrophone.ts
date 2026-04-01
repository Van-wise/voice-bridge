/**
 * Voice Bridge - 麦克风桥接 Hook
 * 手机麦克风 → 电脑音频播放
 */

import { ref, onUnmounted, computed } from 'vue'

interface AudioStreamOptions {
  sampleRate?: number
  channelCount?: 1 | 2
  bitsPerSample?: number
  codec?: 'opus' | 'pcm'
}

export interface MicrophoneState {
  isStreaming: boolean
  isConnecting: boolean
  error: string | null
  duration: number
  deviceId: string | null
}

export function useMicrophone(deviceId: string, options: AudioStreamOptions = {}) {
  // 配置
  const config = {
    sampleRate: options.sampleRate || 16000,
    channelCount: options.channelCount || 1,
    bitsPerSample: options.bitsPerSample || 16,
    codec: options.codec || 'opus',
  }

  // 状态
  const isStreaming = ref(false)
  const isConnecting = ref(false)
  const error = ref<string | null>(null)
  const duration = ref(0)
  const audioLevel = ref(0) // 音频音量级别 (0-100)

  // 内部变量
  let mediaStream: MediaStream | null = null
  let mediaRecorder: MediaRecorder | null = null
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let ws: WebSocket | null = null
  let durationTimer: number | null = null
  let levelAnimationFrame: number | null = null
  let reconnectTimer: number | null = null

  // 计算属性
  const state = computed<MicrophoneState>(() => ({
    isStreaming: isStreaming.value,
    isConnecting: isConnecting.value,
    error: error.value,
    duration: duration.value,
    deviceId: deviceId,
  }))

  /**
   * 检查麦克风功能是否可用
   */
  function checkMicrophoneAvailability(): { available: boolean; error: string | null } {
    // 检查 navigator.mediaDevices
    if (!navigator.mediaDevices) {
      return {
        available: false,
        error: '您的浏览器不支持麦克风功能。请使用 Chrome、Safari 或 Firefox 等现代浏览器，并确保通过 HTTPS 访问。'
      }
    }

    // 检查 getUserMedia
    if (typeof navigator.mediaDevices.getUserMedia !== 'function') {
      // 尝试旧版 API
      if (typeof (navigator as any).getUserMedia === 'function') {
        return { available: true, error: null }
      }
      return {
        available: false,
        error: '您的浏览器不支持 getUserMedia API。请更新到最新版本的 Chrome 或 Safari。'
      }
    }

    return { available: true, error: null }
  }

  /**
   * 获取 WebSocket URL
   */
  function getWsUrl(): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    return `${protocol}//${host}/ws/audio/${deviceId}`
  }

  /**
   * 初始化 WebSocket 连接
   */
  async function initWebSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      ws = new WebSocket(getWsUrl())

      ws.onopen = () => {
        console.log('[Mic] WebSocket connected')
        isConnecting.value = false
        resolve()
      }

      ws.onerror = (e) => {
        console.error('[Mic] WebSocket error', e)
        error.value = 'WebSocket 连接失败'
        isConnecting.value = false
        reject(e)
      }

      ws.onclose = () => {
        console.log('[Mic] WebSocket closed')
        if (isStreaming.value) {
          // 非正常断开，尝试重连
          scheduleReconnect()
        }
      }

      ws.onmessage = (event) => {
        // 电脑端不接收麦克风数据，这里主要用于状态同步
        try {
          const msg = JSON.parse(event.data)
          console.log('[Mic] Received message:', msg)
        } catch {
          // 忽略无法解析的消息
        }
      }
    })
  }

  /**
   * 请求麦克风权限并初始化
   */
  async function initMicrophone(): Promise<MediaStream> {
    try {
      // 检查 mediaDevices
      if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== 'function') {
        throw new Error('浏览器不支持麦克风功能')
      }

      // 请求麦克风权限
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true, // 回声消除
          noiseSuppression: true, // 降噪
          autoGainControl: true, // 自动增益
          channelCount: config.channelCount,
          sampleRate: config.sampleRate,
        }
      })

      // 设置音频分析器（用于音量检测）
      audioContext = new AudioContext({ sampleRate: config.sampleRate })
      const source = audioContext.createMediaStreamSource(mediaStream)
      analyser = audioContext.createAnalyser()
      analyser.fftSize = 256
      source.connect(analyser)

      // 开始音量检测
      startLevelMonitoring()

      return mediaStream
    } catch (e) {
      const err = e as Error
      if (err.name === 'NotAllowedError') {
        error.value = '麦克风权限被拒绝，请在浏览器设置中允许访问麦克风'
      } else if (err.name === 'NotFoundError') {
        error.value = '未找到麦克风设备'
      } else {
        error.value = `麦克风初始化失败: ${err.message}`
      }
      throw e
    }
  }

  /**
   * 开始音量监测
   */
  function startLevelMonitoring(): void {
    if (!analyser) return

    const dataArray = new Uint8Array(analyser.frequencyBinCount)

    function updateLevel() {
      if (!analyser || !isStreaming.value) return

      analyser.getByteFrequencyData(dataArray)
      const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length
      audioLevel.value = Math.min(100, Math.round(average * 100 / 255))

      levelAnimationFrame = requestAnimationFrame(updateLevel)
    }

    updateLevel()
  }

  /**
   * 停止音量监测
   */
  function stopLevelMonitoring(): void {
    if (levelAnimationFrame) {
      cancelAnimationFrame(levelAnimationFrame)
      levelAnimationFrame = null
    }
    audioLevel.value = 0
  }

  /**
   * 创建 MediaRecorder
   */
  function createMediaRecorder(stream: MediaStream): MediaRecorder {
    // 优先使用 opus 编码（如果浏览器支持）
    const mimeTypes = [
      'audio/webm;codecs=opus',
      'audio/opus',
      'audio/webm',
      'audio/mp4',
    ]

    let selectedMimeType = ''
    for (const mimeType of mimeTypes) {
      if (MediaRecorder.isTypeSupported(mimeType)) {
        selectedMimeType = mimeType
        console.log('[Mic] Using mime type:', selectedMimeType)
        break
      }
    }

    const recorder = new MediaRecorder(stream, {
      mimeType: selectedMimeType || undefined,
      audioBitsPerSecond: 32000, // 低比特率适合语音
    })

    // 数据块处理
    recorder.ondataavailable = async (event) => {
      if (event.data.size > 0 && ws && ws.readyState === WebSocket.OPEN) {
        // 将 Blob 转换为 ArrayBuffer
        const arrayBuffer = await event.data.arrayBuffer()

        // 转换为 Base64 发送
        const base64 = arrayBufferToBase64(arrayBuffer)

        ws.send(JSON.stringify({
          type: 'audio_chunk',
          audio: base64,
          timestamp: Date.now(),
          codec: selectedMimeType,
        }))
      }
    }

    return recorder
  }

  /**
   * ArrayBuffer 转 Base64
   */
  function arrayBufferToBase64(buffer: ArrayBuffer): string {
    const bytes = new Uint8Array(buffer)
    let binary = ''
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i])
    }
    return btoa(binary)
  }

  /**
   * 开始音频传输
   */
  async function startStreaming(): Promise<void> {
    if (isStreaming.value || isConnecting.value) {
      console.log('[Mic] Already streaming or connecting')
      return
    }

    error.value = null
    isConnecting.value = true

    // 检查麦克风是否可用
    const availability = checkMicrophoneAvailability()
    if (!availability.available) {
      error.value = availability.error
      isConnecting.value = false
      return
    }

    try {
      // 1. 初始化 WebSocket
      await initWebSocket()

      // 2. 初始化麦克风
      const stream = await initMicrophone()

      // 3. 创建 MediaRecorder
      mediaRecorder = createMediaRecorder(stream)

      // 4. 开始录制（请求数据的时间间隔：100ms）
      mediaRecorder.start(100)

      // 5. 发送开始信号
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'audio_start',
          timestamp: Date.now(),
          config: config,
        }))
      }

      // 6. 更新状态
      isStreaming.value = true
      duration.value = 0

      // 7. 开始计时
      durationTimer = window.setInterval(() => {
        duration.value++
      }, 1000)

      console.log('[Mic] Streaming started')

    } catch (e) {
      const err = e as Error
      error.value = err.message || '启动失败'
      isConnecting.value = false
      cleanup()
      throw e
    }
  }

  /**
   * 停止音频传输
   */
  function stopStreaming(): void {
    if (!isStreaming.value && !isConnecting.value) {
      return
    }

    // 发送停止信号
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'audio_stop',
        timestamp: Date.now(),
      }))
    }

    // 清理资源
    cleanup()

    console.log('[Mic] Streaming stopped')
  }

  /**
   * 清理资源
   */
  function cleanup(): void {
    // 停止 MediaRecorder
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop()
    }
    mediaRecorder = null

    // 停止音轨
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop())
      mediaStream = null
    }

    // 关闭 AudioContext
    if (audioContext) {
      audioContext.close()
      audioContext = null
    }
    analyser = null

    // 停止音量监测
    stopLevelMonitoring()

    // 清除计时器
    if (durationTimer) {
      clearInterval(durationTimer)
      durationTimer = null
    }

    // 关闭 WebSocket
    if (ws) {
      ws.close()
      ws = null
    }

    // 清除重连定时器
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }

    // 更新状态
    isStreaming.value = false
    isConnecting.value = false
    duration.value = 0
    audioLevel.value = 0
  }

  /**
   * 调度重连
   */
  function scheduleReconnect(): void {
    if (reconnectTimer || isStreaming.value) return

    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      if (isStreaming.value) {
        console.log('[Mic] Attempting to reconnect...')
        startStreaming().catch(e => {
          console.error('[Mic] Reconnect failed:', e)
        })
      }
    }, 3000)
  }

  /**
   * 切换麦克风状态
   */
  async function toggle(): Promise<void> {
    if (isStreaming.value) {
      stopStreaming()
    } else {
      await startStreaming()
    }
  }

  // 组件卸载时清理
  onUnmounted(() => {
    cleanup()
  })

  return {
    // 状态
    state,
    isStreaming,
    isConnecting,
    error,
    duration,
    audioLevel,

    // 方法
    startStreaming,
    stopStreaming,
    toggle,
    cleanup,
  }
}
