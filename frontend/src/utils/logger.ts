// -*- coding: utf-8 -*-
/**
 * Voice Bridge 前端统一日志工具
 *
 * 功能：
 *  - 结构化日志输出 [VB][LEVEL][tag] message
 *  - 按级别过滤（dev 模式全开，prod 模式仅 WARN/ERROR）
 *  - 每个标签可独立开关
 *  - 可选的 session ID（WebSocket 连接时注入，用于关联后端日志）
 *  - 自动上报 ERROR/WARN 到后端 /api/log 接口
 *
 * 使用方法：
 *   import { logger } from '@/utils/logger'
 *   logger.info('MyComponent', '用户点击了按钮')
 *   logger.error('WebSocket', '连接失败', { retry: 3 })
 *
 *   // WebSocket 连接时注入 sessionId（后端 traceId 的前端版本）
 *   import { setSessionId } from '@/utils/logger'
 *   setSessionId('a1b2c3d4')
 */

// ==================== 类型定义 ====================

export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'

interface LogEntry {
  level: LogLevel
  tag: string
  message: string
  data?: unknown
  timestamp: number
  sessionId?: string
  traceId?: string
}

// ==================== 配置 ====================

const IS_DEV = import.meta.env.DEV

// 每个标签的日志级别，undefined 表示跟随全局级别
const _tagLevels: Partial<Record<string, LogLevel>> = {
  // 默认 DEBUG 在开发模式，INFO 在生产模式
}

// ==================== Trace ID（关联前后端） ====================

let _traceId: string | null = null

/**
 * 设置当前 Trace ID（由 API 模块自动设置）
 */
export function setTraceId(id: string | null): void {
  _traceId = id
}

export function getTraceId(): string | null {
  return _traceId
}

/**
 * 生成短 Trace ID
 */
export function generateTraceId(): string {
  return Math.random().toString(36).substring(2, 10)
}

// ==================== Session ID（关联后端 traceId） ====================

let _sessionId: string | null = null

/**
 * WebSocket 连接时由调用方注入 sessionId
 * 后端会返回 traceId，前端保存后可以前后端日志串起来
 */
export function setSessionId(id: string | null): void {
  _sessionId = id
}

export function getSessionId(): string | null {
  return _sessionId
}

// ==================== 内部工具 ====================

function shouldLog(tag: string, level: LogLevel): boolean {
  if (IS_DEV) return true
  const tagLevel = _tagLevels[tag]
  if (tagLevel) {
    const order: LogLevel[] = ['DEBUG', 'INFO', 'WARN', 'ERROR']
    return order.indexOf(level) >= order.indexOf(tagLevel)
  }
  // 全局：dev 全开，prod 只开 WARN/ERROR
  return IS_DEV || level === 'WARN' || level === 'ERROR'
}

function formatLevel(level: LogLevel): string {
  const icons: Record<LogLevel, string> = {
    DEBUG: '🔍',
    INFO: 'ℹ️',
    WARN: '⚠️',
    ERROR: '❌',
  }
  return icons[level] || level
}

function formatMessage(entry: LogEntry): string {
  const ts = new Date(entry.timestamp).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    fractionalSecondDigits: 3,
  })
  const sid = entry.sessionId ? `[${entry.sessionId}]` : ''
  const tid = entry.traceId ? `[T:${entry.traceId}]` : ''
  const dataStr = entry.data !== undefined ? ` ${JSON.stringify(entry.data)}` : ''
  return `[VB][${entry.level}][${entry.tag}]${sid}${tid} ${entry.message}${dataStr}`
}

function getCallerLocation(): string {
  try {
    throw new Error('trace')
  } catch (e) {
    const stack = (e as Error).stack?.split('\n') ?? []
    // stack[0] = Error, stack[1] = formatMessage, stack[2] = caller
    const caller = stack[3] ?? ''
    const match = caller.match(/\/(src\/[^:]+):(\d+):\d+/)
    if (match) {
      return `${match[1]}:${match[2]}`
    }
    return ''
  }
}

// ==================== 后端上报 ====================

let _deviceId: string | null = null

/**
 * 设置设备 ID（从 localStorage 获取）
 */
export function setDeviceId(id: string | null): void {
  _deviceId = id
}

/**
 * 上报日志到后端
 * ERROR 和 WARN 级别自动上报
 */
function sendToBackend(entry: LogEntry): void {
  // 只上报 ERROR 和 WARN
  if (entry.level !== 'ERROR' && entry.level !== 'WARN') {
    return
  }

  // 获取设备 ID
  if (!_deviceId) {
    _deviceId = localStorage.getItem('vb_client_id') || 'unknown'
  }

  // 构建上报数据
  const logData = {
    level: entry.level,
    message: entry.message,
    trace_id: entry.traceId || _traceId || '',
    device_id: _deviceId,
    extra: {
      tag: entry.tag,
      data: entry.data,
      session_id: entry.sessionId,
      url: window.location.href,
      user_agent: navigator.userAgent,
    }
  }

  // 使用 sendBeacon 确保可靠上报
  if (navigator.sendBeacon) {
    navigator.sendBeacon('/api/log', JSON.stringify(logData))
  } else {
    // 兜底：使用 fetch
    fetch('/api/log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(logData),
    }).catch(() => {})  // 静默失败，不影响主流程
  }
}

// ==================== 公开 API ====================

/**
 * 调试日志（仅开发模式可见）
 */
export function debug(tag: string, message: string, data?: unknown): void {
  if (!shouldLog(tag, 'DEBUG')) return
  const entry: LogEntry = {
    level: 'DEBUG',
    tag,
    message,
    data,
    timestamp: Date.now(),
    sessionId: _sessionId ?? undefined,
  }
  console.debug(formatMessage(entry))
}

/**
 * 普通信息日志
 */
export function info(tag: string, message: string, data?: unknown): void {
  if (!shouldLog(tag, 'INFO')) return
  const entry: LogEntry = {
    level: 'INFO',
    tag,
    message,
    data,
    timestamp: Date.now(),
    sessionId: _sessionId ?? undefined,
  }
  console.info(formatMessage(entry))
  sendToBackend(entry)
}

/**
 * 警告日志（开发 + 生产均可见）
 */
export function warn(tag: string, message: string, data?: unknown): void {
  if (!shouldLog(tag, 'WARN')) return
  const entry: LogEntry = {
    level: 'WARN',
    tag,
    message,
    data,
    timestamp: Date.now(),
    sessionId: _sessionId ?? undefined,
  }
  console.warn(formatMessage(entry))
  sendToBackend(entry)
}

/**
 * 错误日志（开发 + 生产均可见）
 */
export function error(tag: string, message: string, data?: unknown): void {
  if (!shouldLog(tag, 'ERROR')) return
  const entry: LogEntry = {
    level: 'ERROR',
    tag,
    message,
    data,
    timestamp: Date.now(),
    sessionId: _sessionId ?? undefined,
  }
  console.error(formatMessage(entry))
  sendToBackend(entry)
}

/**
 * 设置某个标签的最低日志级别
 * 示例: setTagLevel('WebSocket', 'DEBUG')
 */
export function setTagLevel(tag: string, level: LogLevel): void {
  _tagLevels[tag] = level
}

// ==================== 统一导出 ====================

/**
 * 对外使用的 logger 对象
 * 用法: logger.info('MyTag', 'message', { extra: 123 })
 */
export const logger = {
  debug,
  info,
  warn,
  error,
  setSessionId,
  getSessionId,
  setTraceId,
  getTraceId,
  generateTraceId,
  setTagLevel,
  setDeviceId,
}

export default logger
