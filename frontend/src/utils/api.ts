/**
 * Voice Bridge API 客户端
 * 
 * 统一的 API 请求工具，自动处理：
 * - 认证头
 * - 错误处理
 * - 类型安全
 */

import { showErrorToast, type ApiResponse } from './errorHandler'

// ==================== 类型定义 ====================

export interface ApiOptions {
  /** 是否显示错误提示 */
  showError?: boolean
  /** 自定义错误消息 */
  errorMessage?: string
  /** 是否抛出异常 */
  throwError?: boolean
}

export interface ApiResult<T> {
  success: boolean
  data?: T
  error?: string
  message?: string
}

// ==================== 工具函数 ====================

/** 获取 API 基础地址 */
export function getApiBase(): string {
  return window.location.origin
}

/** 获取客户端 ID */
export function getClientId(): string {
  return localStorage.getItem('vb_client_id') || ('c' + Math.random().toString(36).substr(2, 9))
}

/** 判断是否本地访问 */
export function isLocalAccess(): boolean {
  const host = location.hostname
  return host === '127.0.0.1' || host === 'localhost'
}

// ==================== 请求工具 ====================

/**
 * 统一 GET 请求
 */
export async function apiGet<T = any>(
  path: string,
  options: ApiOptions = {}
): Promise<ApiResult<T>> {
  const { showError = true, errorMessage, throwError = false } = options

  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      headers: {
        'X-Client-ID': getClientId(),
        'X-Is-Local': isLocalAccess() ? 'true' : 'false'
      }
    })

    const data: ApiResponse<T> = await response.json()

    if (data.error) {
      const msg = errorMessage || data.message || data.error
      if (showError) showErrorToast(msg)
      if (throwError) throw new Error(msg)
      return { success: false, error: data.error, message: msg }
    }

    return { success: true, data: data as T }
  } catch (err) {
    const msg = err instanceof Error ? err.message : '网络请求失败'
    if (showError) showErrorToast(msg)
    if (throwError) throw err
    return { success: false, error: msg }
  }
}

/**
 * 统一 POST 请求
 */
export async function apiPost<T = any>(
  path: string,
  body: Record<string, any>,
  options: ApiOptions = {}
): Promise<ApiResult<T>> {
  const { showError = true, errorMessage, throwError = false } = options

  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Client-ID': getClientId()
      },
      body: JSON.stringify(body)
    })

    const data: ApiResponse<T> = await response.json()

    if (data.error) {
      const msg = errorMessage || data.message || data.error
      if (showError) showErrorToast(msg)
      if (throwError) throw new Error(msg)
      return { success: false, error: data.error, message: msg }
    }

    return { success: true, data: data as T }
  } catch (err) {
    const msg = err instanceof Error ? err.message : '网络请求失败'
    if (showError) showErrorToast(msg)
    if (throwError) throw err
    return { success: false, error: msg }
  }
}

/**
 * 带超时控制的请求
 */
export async function apiFetch<T = any>(
  path: string,
  options: RequestInit & { timeout?: number } = {}
): Promise<ApiResult<T>> {
  const { timeout = 10000, ...fetchOptions } = options

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        'X-Client-ID': getClientId(),
        'X-Is-Local': isLocalAccess() ? 'true' : 'false',
        ...fetchOptions.headers
      }
    })

    clearTimeout(timeoutId)

    const data: ApiResponse<T> = await response.json()

    if (data.error) {
      return { success: false, error: data.error, message: data.message }
    }

    return { success: true, data: data as T }
  } catch (err) {
    clearTimeout(timeoutId)
    const msg = err instanceof Error ? err.message : '请求失败'
    
    if (err instanceof Error && err.name === 'AbortError') {
      return { success: false, error: 'TIMEOUT', message: '请求超时' }
    }
    
    return { success: false, error: msg }
  }
}

// ==================== 特定业务 API ====================

export interface PollResponse {
  events: any[]
  ev: number
  text: string
  text_ver: number
  settings_ver: number
  devices: any[]
  local_ip: string
  current_port: number
}

export interface SyncResponse {
  success: boolean
  action: string
  auto_clear: boolean
}

export interface Settings {
  mode: 'auto' | 'manual'
  auto_clear: boolean
  auto_copy: boolean
  persist_history: boolean
  port: number
}

export interface Stats {
  total_syncs: number
  total_chars: number
  active_clients: number
  total_history: number
}

export interface HistoryResponse {
  items: any[]
  total: number
}

export interface LogResponse {
  logs: string[]
}

/** 轮询事件 */
export async function pollEvents(lastEv: number): Promise<ApiResult<PollResponse>> {
  return apiGet<PollResponse>(`/api/poll?last_ev=${lastEv}`, { showError: false })
}

/** 同步文本 */
export async function syncText(
  text: string,
  mode: string,
  autoClear: boolean
): Promise<ApiResult<SyncResponse>> {
  return apiPost<SyncResponse>('/api/sync', {
    text,
    mode,
    auto_clear: autoClear,
    manual: true
  })
}

/** 获取设置 */
export async function getSettings(): Promise<ApiResult<Settings>> {
  return apiGet<Settings>('/api/settings')
}

/** 保存设置 */
export async function saveSettings(settings: Partial<Settings>): Promise<ApiResult<{ _ver: number }>> {
  return apiPost('/api/settings', settings)
}

/** 获取统计 */
export async function getStats(): Promise<ApiResult<Stats>> {
  return apiGet<Stats>('/api/stats')
}

/** 获取历史 */
export async function getHistory(offset: number, limit: number): Promise<ApiResult<HistoryResponse>> {
  return apiGet<HistoryResponse>(`/api/history?offset=${offset}&limit=${limit}`)
}

/** 获取日志 */
export async function getLogs(): Promise<ApiResult<LogResponse>> {
  return apiGet<LogResponse>('/api/logs')
}

/** 清空剪贴板 */
export async function clearClipboard(): Promise<ApiResult<void>> {
  return apiPost('/api/clear', {})
}

/** 重启服务 */
export async function restartService(): Promise<ApiResult<void>> {
  return apiPost('/api/restart', {})
}

/** 检查端口可用性 */
export async function checkPort(port: number): Promise<ApiResult<{ available: boolean }>> {
  return apiPost('/api/port/check', { port })
}
