// -*- coding: utf-8 -*-
/**
 * Voice Bridge 前端统一日志工具
 *
 * 功能：
 *  - 结构化日志输出 [VB][LEVEL][tag] message
 *  - 按级别过滤（dev 模式全开，prod 模式仅 WARN/ERROR）
 *  - 每个标签可独立开关
 *  - 可选的 session ID（WebSocket 连接时注入，用于关联后端日志）
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
}

// ==================== 配置 ====================

const IS_DEV = import.meta.env.DEV

// 每个标签的日志级别，undefined 表示跟随全局级别
const _tagLevels: Partial<Record<string, LogLevel>> = {
  // 默认 DEBUG 在开发模式，INFO 在生产模式
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
  const dataStr = entry.data !== undefined ? ` ${JSON.stringify(entry.data)}` : ''
  return `[VB][${entry.level}][${entry.tag}]${sid} ${entry.message}${dataStr}`
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

function sendToBackend(entry: LogEntry): void {
  // 可选：将关键日志发送到后端（ WARN/ERROR 级别）
  // 当前暂不启用，保留接口以备后用
  if (entry.level === 'ERROR' || entry.level === 'WARN') {
    // navigator.sendBeacon('/api/logs/client', JSON.stringify(entry))
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
  setTagLevel,
}

export default logger
