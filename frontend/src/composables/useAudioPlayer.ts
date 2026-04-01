/**
 * Voice Bridge - 音频播放器 Hook
 * 接收并播放来自手机的麦克风音频
 */

import { ref, onUnmounted, computed } from 'vue'

export interface AudioPlayerState {
  isPlaying: boolean
  isConnected: boolean
  error: string | null
  activeSources: string[]
}

export function useAudioPlayer(deviceId: string = 'pc') {
  // 状态
  const isPlaying = ref(false)
  const isConnected = ref(false)
  const error = ref<string | null>(null)
  const activeSources = ref<string[]>([])
  const currentSource = ref<string | null>(null)

  // 内部变量
  let audioContext: AudioContext | null = null
  let ws: WebSocket | null = null
  let sourceBuffer: AudioBuffer | null = null
  let gainNode: GainNode | null = null
  let reconnectTimer: number | null = null
  let audioQueue: AudioBuffer[] = []
  let isPlayingQueue = false
  let lastSource: string | null = null

  // 配置
  const SAMPLE_RATE = 16000
  const CHANNEL_COUNT = 1
  const MAX_QUEUE_SIZE = 10

  // 计算属性
  const state = computed<AudioPlayerState>(() => ({
    isPlaying: isPlaying.value,
    isConnected: isConnected.value,
    error: error.value,
    activeSources: activeSources.value,
  }))

  /**
   * 获取 WebSocket URL
   */
  function getWsUrl(): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    return `${protocol}//${host}/ws/audio/${deviceId}`
  }

  /**
   * 初始化音频上下文
   */
  function initAudioContext(): AudioContext {
    if (!audioContext) {
      audioContext = new AudioContext({ sampleRate: SAMPLE_RATE })

      // 创建增益节点
      gainNode = audioContext.createGain()
      gainNode.gain.value = 1.0
      gainNode.connect(audioContext.destination)
    }

    // 确保上下文正在运行
    if (audioContext.state === 'suspended') {
      audioContext.resume()
    }

    return audioContext
  }

  /**
   * Base64 转 ArrayBuffer
   */
  function base64ToArrayBuffer(base64: string): ArrayBuffer {
    const binary = atob(base64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i)
    }
    return bytes.buffer
  }

  /**
   * 解码并播放音频
   */
  async function playAudioChunk(base64Audio: string, codec?: string): Promise<void> {
    try {
      const ctx = initAudioContext()
      const arrayBuffer = base64ToArrayBuffer(base64Audio)

      // 创建 AudioBuffer
      // 注意：MediaRecorder 输出的格式是 webm/opus，需要特殊处理
      // 这里我们使用 AudioContext.decodeAudioData 来解码

      // 创建临时 blob 用于解码
      const mimeType = codec || 'audio/webm;codecs=opus'
      const blob = new Blob([arrayBuffer], { type: mimeType })

      try {
        sourceBuffer = await ctx.decodeAudioData(await blob.arrayBuffer())
      } catch (decodeError) {
        // 如果解码失败，尝试作为原始 PCM 数据处理
        console.warn('[Audio] Decode failed, trying raw PCM:', decodeError)
        // 这里可以添加 PCM 解码逻辑
        return
      }

      // 创建音频源
      const source = ctx.createBufferSource()
      source.buffer = sourceBuffer

      if (gainNode) {
        source.connect(gainNode)
      } else {
        source.connect(ctx.destination)
      }

      // 播放
      source.start()

      console.log('[Audio] Playing chunk, duration:', sourceBuffer.duration)

    } catch (e) {
      console.error('[Audio] Play error:', e)
      // 静默处理解码错误，避免频繁输出
    }
  }

  /**
   * 播放队列中的音频
   */
  async function playQueue(): Promise<void> {
    if (isPlayingQueue || audioQueue.length === 0) return

    isPlayingQueue = true

    while (audioQueue.length > 0 && isPlaying.value) {
      const buffer = audioQueue.shift()!
      try {
        const ctx = initAudioContext()
        const source = ctx.createBufferSource()
        source.buffer = buffer

        if (gainNode) {
          source.connect(gainNode)
        } else {
          source.connect(ctx.destination)
        }

        // 等待播放完成
        await new Promise<void>((resolve) => {
          source.onended = () => resolve()
          source.start()
        })
      } catch (e) {
        console.error('[Audio] Queue play error:', e)
      }
    }

    isPlayingQueue = false
  }

  /**
   * 初始化 WebSocket 连接
   */
  async function initWebSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      ws = new WebSocket(getWsUrl())

      ws.onopen = () => {
        console.log('[Audio] WebSocket connected')
        isConnected.value = true
        error.value = null
        resolve()
      }

      ws.onerror = (e) => {
        console.error('[Audio] WebSocket error', e)
        error.value = 'WebSocket 连接失败'
        isConnected.value = false
        reject(e)
      }

      ws.onclose = () => {
        console.log('[Audio] WebSocket closed')
        isConnected.value = false

        if (isPlaying.value) {
          scheduleReconnect()
        }
      }

      ws.onmessage = async (event) => {
        try {
          const msg = JSON.parse(event.data)
          const msgType = msg.type

          if (msgType === 'audio_chunk') {
            // 音频数据块
            if (msg.audio) {
              await playAudioChunk(msg.audio, msg.codec)
            }

            // 更新当前来源
            if (msg.source && msg.source !== currentSource.value) {
              currentSource.value = msg.source
            }

          } else if (msgType === 'audio_start') {
            console.log('[Audio] Audio stream started from:', msg.source)
            isPlaying.value = true
            activeSources.value = [...new Set([...activeSources.value, msg.source])]

          } else if (msgType === 'audio_stop') {
            console.log('[Audio] Audio stream stopped from:', msg.source)
            activeSources.value = activeSources.value.filter(s => s !== msg.source)

            if (activeSources.value.length === 0) {
              isPlaying.value = false
              currentSource.value = null
            } else {
              currentSource.value = activeSources.value[0]
            }

          } else if (msgType === 'audio_stream_started') {
            // 某设备开始音频传输
            console.log('[Audio] Device started streaming:', msg.device_id)
            activeSources.value = [...new Set([...activeSources.value, msg.device_id])]

          } else if (msgType === 'audio_stream_stopped') {
            // 某设备停止音频传输
            console.log('[Audio] Device stopped streaming:', msg.device_id)
            activeSources.value = activeSources.value.filter(s => s !== msg.device_id)

            if (activeSources.value.length === 0) {
              isPlaying.value = false
              currentSource.value = null
            }

          } else if (msgType === 'pong') {
            // 心跳响应，忽略
          }
        } catch (e) {
          console.error('[Audio] Message parse error:', e)
        }
      }
    })
  }

  /**
   * 开始接收音频
   */
  async function startReceiving(): Promise<void> {
    if (isConnected.value) {
      console.log('[Audio] Already connected')
      return
    }

    error.value = null

    try {
      // 初始化音频上下文（用于用户交互后才能播放音频）
      initAudioContext()

      // 连接 WebSocket
      await initWebSocket()

      console.log('[Audio] Started receiving')

    } catch (e) {
      const err = e as Error
      error.value = err.message || '启动失败'
      throw e
    }
  }

  /**
   * 停止接收音频
   */
  function stopReceiving(): void {
    // 发送停止信号（让服务器知道我们不再接收）
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'audio_stop',
        timestamp: Date.now(),
      }))
    }

    cleanup()
    console.log('[Audio] Stopped receiving')
  }

  /**
   * 清理资源
   */
  function cleanup(): void {
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

    // 清除音频队列
    audioQueue = []

    // 关闭音频上下文（不在这里关闭，让它保持打开状态）
    // if (audioContext) {
    //   audioContext.close()
    //   audioContext = null
    // }
    // gainNode = null

    // 更新状态
    isConnected.value = false
    isPlaying.value = false
    activeSources.value = []
    currentSource.value = null
  }

  /**
   * 调度重连
   */
  function scheduleReconnect(): void {
    if (reconnectTimer) return

    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      if (!isConnected.value) {
        console.log('[Audio] Attempting to reconnect...')
        startReceiving().catch(e => {
          console.error('[Audio] Reconnect failed:', e)
        })
      }
    }, 3000)
  }

  /**
   * 设置音量
   */
  function setVolume(volume: number): void {
    if (gainNode) {
      gainNode.gain.value = Math.max(0, Math.min(1, volume))
    }
  }

  /**
   * 切换接收状态
   */
  async function toggle(): Promise<void> {
    if (isConnected.value) {
      stopReceiving()
    } else {
      await startReceiving()
    }
  }

  // 组件卸载时清理
  onUnmounted(() => {
    cleanup()
  })

  return {
    // 状态
    state,
    isPlaying,
    isConnected,
    error,
    activeSources,
    currentSource,

    // 方法
    startReceiving,
    stopReceiving,
    toggle,
    setVolume,
    cleanup,
  }
}
