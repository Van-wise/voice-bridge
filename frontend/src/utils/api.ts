/**
 * Voice Bridge API 客户端
 * 
 * 统一的 API 请求工具，自动处理：
 * - 认证头
 * - 错误处理
 * - 类型安全
 * - Trace ID 全链路追踪
 */

import { showErrorToast, type ApiResponse } from './errorHandler'
import logger from './logger'

// ==================== Trace ID 管理 ====================

/** 生成短 Trace ID（8位） */
function generateTraceId(): string {
  return Math.random().toString(36).substring(2, 10)
}

/** 当前请求的 Trace ID */
let _currentTraceId: string | null = null

/** 获取当前 Trace ID */
export function getTraceId(): string | null {
  return _currentTraceId
}

/** 设置当前 Trace ID */
export function setTraceId(id: string): void {
  _currentTraceId = id
}

// ==================== 请求拦截器 ====================

/** 请求开始钩子 */
const _requestStartHooks: Array<(traceId: string, method: string, path: string) => void> = []

/** 请求结束钩子 */
const _requestEndHooks: Array<(traceId: string, method: string, path: string, duration: number, ok: boolean) => void> = []

/** 注册请求开始钩子 */
export function onRequestStart(fn: (traceId: string, method: string, path: string) => void): void {
  _requestStartHooks.push(fn)
}

/** 注册请求结束钩子 */
export function onRequestEnd(fn: (traceId: string, method: string, path: string, duration: number, ok: boolean) => void): void {
  _requestEndHooks.push(fn)
}

// ==================== 类型定义 ====================

export interface ApiOptions {
  /** 是否显示错误提示 */
  showError?: boolean
  /** 自定义错误消息 */
  errorMessage?: string
  /** 是否抛出异常 */
  throwError?: boolean
  /** 自定义请求头 */
  headers?: Record<string, string>
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

/** 获取客户端 ID（统一使用 vb_device_id，与 WebSocket 连接保持一致） */
export function getClientId(): string {
  return localStorage.getItem('vb_device_id') || ('c' + Math.random().toString(36).substr(2, 9))
}

/** 判断是否本地访问 */
export function isLocalAccess(): boolean {
  const host = location.hostname
  return host === '127.0.0.1' || host === 'localhost'
}

// ==================== 请求工具 ====================

/**
 * 统一 GET 请求（带 Trace ID）
 */
export async function apiGet<T = any>(
  path: string,
  options: ApiOptions = {}
): Promise<ApiResult<T>> {
  const { showError = true, errorMessage, throwError = false } = options
  const traceId = generateTraceId()
  const startTime = performance.now()

  // 调用开始钩子
  _requestStartHooks.forEach(fn => fn(traceId, 'GET', path))

  // 记录日志
  logger.debug('API', `GET ${path}`, { traceId })

  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      headers: {
        'X-Client-ID': getClientId(),
        'X-Is-Local': isLocalAccess() ? 'true' : 'false',
        'X-Trace-ID': traceId,  // 添加 Trace ID
      }
    })

    const data: ApiResponse<T> = await response.json()
    const duration = Math.round(performance.now() - startTime)

    // 调用结束钩子
    _requestEndHooks.forEach(fn => fn(traceId, 'GET', path, duration, !data.error))

    if (data.error) {
      const msg = errorMessage || data.message || data.error
      logger.warn('API', `GET ${path} failed`, { traceId, duration, error: msg })
      if (showError) showErrorToast(msg)
      if (throwError) throw new Error(msg)
      return { success: false, error: data.error, message: msg }
    }

    logger.debug('API', `GET ${path} success`, { traceId, duration })
    return { success: true, data: data as T }
  } catch (err) {
    const duration = Math.round(performance.now() - startTime)
    const msg = err instanceof Error ? err.message : '网络请求失败'

    // 调用结束钩子
    _requestEndHooks.forEach(fn => fn(traceId, 'GET', path, duration, false))

    logger.error('API', `GET ${path} exception`, { traceId, duration, error: msg })
    if (showError) showErrorToast(msg)
    if (throwError) throw err
    return { success: false, error: msg }
  }
}

/**
 * 统一 POST 请求（带 Trace ID 和超时控制）
 */
export async function apiPost<T = any>(
  path: string,
  body: Record<string, any>,
  options: ApiOptions & { timeout?: number } = {}
): Promise<ApiResult<T>> {
  const { showError = true, errorMessage, throwError = false, timeout = 10000, headers = {} } = options
  const traceId = generateTraceId()
  const startTime = performance.now()

  // 调用开始钩子
  _requestStartHooks.forEach(fn => fn(traceId, 'POST', path))

  // 记录日志
  logger.debug('API', `POST ${path}`, { traceId, bodyKeys: Object.keys(body), timeout })

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Client-ID': getClientId(),
        'X-Trace-ID': traceId,
        ...headers,  // 合并自定义 headers
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    clearTimeout(timeoutId)
    const data: ApiResponse<T> = await response.json()
    const duration = Math.round(performance.now() - startTime)

    // 调用结束钩子
    _requestEndHooks.forEach(fn => fn(traceId, 'POST', path, duration, !data.error))

    if (data.error) {
      const msg = errorMessage || data.message || data.error
      logger.warn('API', `POST ${path} failed`, { traceId, duration, error: msg })
      if (showError) showErrorToast(msg)
      if (throwError) throw new Error(msg)
      return { success: false, error: data.error, message: msg }
    }

    logger.debug('API', `POST ${path} success`, { traceId, duration })
    return { success: true, data: data as T }
  } catch (err) {
    clearTimeout(timeoutId)
    const duration = Math.round(performance.now() - startTime)
    
    let msg = '网络请求失败'
    let errorCode = 'REQUEST_ERROR'
    
    if (err instanceof Error) {
      if (err.name === 'AbortError') {
        msg = '请求超时'
        errorCode = 'TIMEOUT'
        logger.warn('API', `POST ${path} timeout`, { traceId, duration, timeout })
      } else {
        msg = err.message
        logger.error('API', `POST ${path} exception`, { traceId, duration, error: msg })
      }
    }

    // 调用结束钩子
    _requestEndHooks.forEach(fn => fn(traceId, 'POST', path, duration, false))

    if (showError) showErrorToast(msg)
    if (throwError) throw err
    return { success: false, error: errorCode, message: msg }
  }
}

/**
 * 带超时控制的请求（带 Trace ID）
 */
export async function apiFetch<T = any>(
  path: string,
  options: RequestInit & { timeout?: number } = {}
): Promise<ApiResult<T>> {
  const { timeout = 10000, ...fetchOptions } = options
  const traceId = generateTraceId()
  const startTime = performance.now()

  // 调用开始钩子
  _requestStartHooks.forEach(fn => fn(traceId, 'FETCH', path))

  logger.debug('API', `FETCH ${path}`, { traceId, timeout })

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        'X-Client-ID': getClientId(),
        'X-Is-Local': isLocalAccess() ? 'true' : 'false',
        'X-Trace-ID': traceId,
        ...fetchOptions.headers
      }
    })

    clearTimeout(timeoutId)
    const duration = Math.round(performance.now() - startTime)

    // 调用结束钩子
    _requestEndHooks.forEach(fn => fn(traceId, 'FETCH', path, duration, response.ok))

    const data: ApiResponse<T> = await response.json()

    if (data.error) {
      logger.warn('API', `FETCH ${path} failed`, { traceId, duration, error: data.error })
      return { success: false, error: data.error, message: data.message }
    }

    logger.debug('API', `FETCH ${path} success`, { traceId, duration })
    return { success: true, data: data as T }
  } catch (err) {
    clearTimeout(timeoutId)
    const duration = Math.round(performance.now() - startTime)
    
    // 调用结束钩子
    _requestEndHooks.forEach(fn => fn(traceId, 'FETCH', path, duration, false))

    let msg = '请求失败'
    let errorCode = 'REQUEST_ERROR'
    
    if (err instanceof Error) {
      if (err.name === 'AbortError') {
        msg = '请求超时'
        errorCode = 'TIMEOUT'
        logger.warn('API', `FETCH ${path} timeout`, { traceId, duration, timeout })
      } else {
        msg = err.message
        logger.error('API', `FETCH ${path} exception`, { traceId, duration, error: msg })
      }
    }
    
    return { success: false, error: errorCode, message: msg }
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
