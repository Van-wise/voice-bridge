/**
 * Voice Bridge 类型定义
 */

// ==================== 设备相关 ====================

export interface Device {
  id: string
  name?: string
  ip: string
  device_type: 'pc' | 'mobile'
  is_local?: boolean
  last_seen?: number
  first_seen?: number
}

export type DeviceType = 'pc' | 'mobile' | 'web'

// ==================== 剪贴板相关 ====================

export interface ClipboardItem {
  id?: string
  text: string
  time: number
  overwritten?: boolean
  hash?: string
  content_category?: ContentCategory
}

export type ContentCategory = 'url' | 'code' | 'file_path' | 'email' | 'phone' | 'id_card' | 'bank_card' | 'plain'

export interface HistoryFilter {
  category?: ContentCategory
  keyword?: string
  offset?: number
  limit?: number
}

// ==================== 设置相关 ====================

export interface Settings {
  mode: 'auto' | 'manual'
  auto_clear: boolean
  auto_copy: boolean
  persist_history: boolean
  port: number
}

export interface SettingsChange {
  key: keyof Settings
  value: any
}

// ==================== 事件相关 ====================

export interface AppEvent {
  ver: number
  type: EventType
  data: Record<string, any>
  ts: number
}

export type EventType = 'sync' | 'clear' | 'settings' | 'device_joined' | 'device_left'

// ==================== API 响应 ====================

export interface ApiResponse<T = any> {
  success?: boolean
  error?: string
  message?: string
  data?: T
  [key: string]: any
}

export interface PollResponse {
  events: AppEvent[]
  ev: number
  text: string
  text_ver: number
  settings_ver: number
  history_count?: number
  devices: Device[]
  local_ip: string
  current_port: number
}

export interface SyncResponse {
  success: boolean
  action: 'synced' | 'pasted' | 'copied' | 'paste_failed' | 'copy_failed'
  auto_clear: boolean
}

export interface Stats {
  total_syncs: number
  total_chars: number
  active_clients: number
  total_history: number
}

export interface HistoryResponse {
  items: ClipboardItem[]
  total: number
}

// ==================== 麦克风相关 ====================

export interface MicSettings {
  auto_play: boolean
  save_recordings: boolean
  notify_on_receive: boolean
  max_recordings: number
  quality_hint: 'low' | 'medium' | 'high'
}

// ==================== 错误相关 ====================

export interface ErrorInfo {
  message: string
  stack?: string
  componentStack?: string
  timestamp: number
  type: 'vue' | 'js' | 'promise' | 'resource'
}

// ==================== Toast 相关 ====================

export type ToastType = 'ok' | 'err' | 'warn' | 'loading' | 'info'

export interface ToastState {
  show: boolean
  message: string
  type: ToastType
  fading: boolean
}
