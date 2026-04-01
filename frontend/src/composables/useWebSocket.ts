// WebSocket Client
import { ref, onUnmounted } from 'vue'

interface WsMessage {
  type: string
  data?: unknown
  source?: string
}

export function useWebSocket(deviceId: string) {
  const connected = ref(false)
  const lastMessage = ref<WsMessage | null>(null)
  let ws: WebSocket | null = null
  let reconnectTimer: number | null = null
  let heartbeatTimer: number | null = null

  const connect = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    ws = new WebSocket(`${protocol}//${host}/ws/${deviceId}`)

    ws.onopen = () => {
      connected.value = true
      startHeartbeat()
    }

    ws.onmessage = (event) => {
      try {
        lastMessage.value = JSON.parse(event.data)
      } catch {
        console.error('Invalid JSON from WebSocket')
      }
    }

    ws.onclose = () => {
      connected.value = false
      stopHeartbeat()
      scheduleReconnect()
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  const send = (message: WsMessage) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message))
    }
  }

  const startHeartbeat = () => {
    heartbeatTimer = window.setInterval(() => {
      send({ type: 'ping' })
    }, 30000)
  }

  const stopHeartbeat = () => {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  const scheduleReconnect = () => {
    if (reconnectTimer) return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connect()
    }, 3000)
  }

  const disconnect = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    stopHeartbeat()
    ws?.close()
    ws = null
  }

  onUnmounted(disconnect)

  return {
    connected,
    lastMessage,
    connect,
    disconnect,
    send,
  }
}
