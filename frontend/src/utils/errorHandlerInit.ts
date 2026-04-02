/**
 * 全局错误处理初始化
 * 
 * 在 main.ts 中导入并调用 initErrorHandler()
 */

import { errorCollector, setGlobalErrorHandler, initGlobalErrorHandler } from './errorHandler'
import { showErrorToast } from './errorHandler'

export { errorCollector, showErrorToast }

// ==================== 错误上报接口 ====================

interface ErrorReport {
  message: string
  stack?: string
  type: string
  timestamp: number
  userAgent?: string
  url?: string
  userId?: string
}

let _errorReportCallback: ((error: ErrorReport) => void) | null = null

/**
 * 设置错误上报回调
 * 可用于将错误上报到日志服务
 */
export function setErrorReportCallback(callback: (error: ErrorReport) => void) {
  _errorReportCallback = callback
}

/**
 * 上报错误到服务器
 */
async function reportError(errorInfo: { message: string; stack?: string; type: string; timestamp: number }) {
  const report: ErrorReport = {
    ...errorInfo,
    userAgent: navigator.userAgent,
    url: window.location.href,
    userId: localStorage.getItem('vb_client_id') || undefined
  }

  // 尝试上报到服务器
  try {
    await fetch('/api/error-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(report)
    }).catch(() => {}) // 静默失败
  } catch (e) {}

  // 调用自定义回调
  _errorReportCallback?.(report)
}

// ==================== 初始化 ====================

export function initErrorHandler() {
  // 设置全局错误处理器
  setGlobalErrorHandler((errorInfo) => {
    // 显示 toast
    if (errorInfo.type === 'vue' || errorInfo.type === 'js') {
      showErrorToast('操作失败，请重试')
    }
    
    // 上报错误（生产环境）
    if (import.meta.env.PROD) {
      reportError(errorInfo)
    }
  })

  // 初始化 Vue 全局错误处理
  initGlobalErrorHandler()

  console.log('[ErrorHandler] 全局错误处理已初始化')
}

// ==================== 便捷错误收集器 API ====================

export function getErrorCollector() {
  return {
    getErrors: () => errorCollector.getErrors(),
    clear: () => errorCollector.clear(),
    count: () => errorCollector.getErrors().length
  }
}
